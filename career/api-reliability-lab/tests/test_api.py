import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from lab.app import PUBLIC_DEMO_TOKEN, create_app, sign_event
from lab.client import retry_after_seconds

PAYLOAD = {"external_reference": "DEMO-1042", "asset_id": "ASSET-0042", "action": "inspect", "priority": "normal"}
AUTH = {"Authorization": f"Bearer {PUBLIC_DEMO_TOKEN}"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("LAB_CLIENT_TOKEN", raising=False)
    waits = []
    async def sleep(delay):
        waits.append(delay)
    app = create_app(sleep=sleep, jitter=lambda: 0)
    with TestClient(app) as client:
        yield app, client, waits


def submit(client, scenario="healthy", key="test-key-0001", payload=None, **headers):
    return client.post("/api/v1/work-orders", json=PAYLOAD if payload is None else payload,
                       headers={**AUTH, "Idempotency-Key": key, "X-Lab-Scenario": scenario, **headers})


def signed(app, event, timestamp=None):
    raw = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time()) if timestamp is None else timestamp
    return raw, {"Content-Type": "application/json", "X-Webhook-Timestamp": str(timestamp),
                 "X-Webhook-Signature": sign_event(app.state.webhook_secret, timestamp, raw)}


def event_for(client, event_id="evt_one"):
    order_id = submit(client).json()["data"]["id"]
    return {"id": event_id, "type": "work_order.completed", "work_order_id": order_id}


def test_create_returns_resource_location_and_correlation(env):
    app, client, waits = env
    r = submit(client, **{"X-Request-ID": "support-case-42"})
    assert r.status_code == 201
    assert r.headers["Location"] == "/api/v1/work-orders/" + r.json()["data"]["id"]
    assert r.headers["X-Request-ID"] == r.json()["meta"]["request_id"] == "support-case-42"
    assert client.get(r.headers["Location"], headers=AUTH).json()["data"]["status"] == "queued"
    assert len(app.state.provider.state.records) == 1 and waits == []


def test_caller_authentication_stops_before_provider(env):
    app, client, _ = env
    r = submit(client, **{"Authorization": "Bearer invalid"})
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"
    assert app.state.provider.state.attempts == {}


def test_validation_is_actionable_and_does_not_echo_input(env):
    app, client, _ = env
    r = submit(client, payload={**PAYLOAD, "asset_id": "PRIVATE-BAD-INPUT"})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "body.asset_id"
    assert "PRIVATE-BAD-INPUT" not in r.text and app.state.provider.state.records == {}


def test_missing_idempotency_key_cannot_create(env):
    app, client, _ = env
    assert client.post("/api/v1/work-orders", json=PAYLOAD, headers=AUTH).status_code == 422
    assert not app.state.provider.state.records


def test_rate_limit_honors_retry_after(env):
    app, client, waits = env
    r = submit(client, "rate_limit")
    assert r.status_code == 201
    assert [x["status"] for x in r.json()["meta"]["trace"]] == [429, 201]
    assert waits == [1.0] and len(app.state.provider.state.records) == 1


def test_transient_outage_uses_backoff_and_recovers(env):
    app, client, waits = env
    r = submit(client, "unavailable")
    assert r.status_code == 201
    assert waits == [0.2, 0.4]
    assert [x["status"] for x in r.json()["meta"]["trace"]] == [503, 503, 201]


def test_lost_response_after_commit_does_not_duplicate(env):
    app, client, waits = env
    r = submit(client, "lost_response")
    assert r.status_code == 201 and r.headers["Idempotency-Replayed"] == "true"
    assert [x["status"] for x in r.json()["meta"]["trace"]] == [504, 201]
    assert len(app.state.provider.state.records) == len(app.state.orders) == 1
    assert waits == [0.2]


def test_identical_request_replays_original_result(env):
    app, client, _ = env
    first, second = submit(client), submit(client)
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert second.headers["Idempotency-Replayed"] == "true"
    assert len(app.state.provider.state.records) == 1


def test_key_reuse_with_changed_payload_returns_conflict(env):
    app, client, waits = env
    submit(client)
    r = submit(client, payload={**PAYLOAD, "priority": "urgent"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_conflict"
    assert len(app.state.provider.state.records) == 1 and waits == []


def test_same_payload_with_new_key_is_a_new_operation(env):
    app, client, _ = env
    submit(client, key="operation-one")
    submit(client, key="operation-two")
    assert len(app.state.provider.state.records) == 2


def test_retry_exhaustion_stops_at_three(env):
    app, client, waits = env
    r = submit(client, "permanent_failure")
    assert r.status_code == 503 and r.json()["meta"]["stop_reason"] == "attempt_limit"
    assert len(r.json()["meta"]["trace"]) == 3 and len(waits) == 2
    assert len(app.state.provider.state.records) == 0


def test_upstream_401_is_not_misreported_as_caller_auth_error(env):
    _, client, waits = env
    r = submit(client, "provider_auth")
    assert r.status_code == 502 and r.json()["meta"]["provider_status"] == 401
    assert r.json()["error"]["code"] == "provider_authentication_failed" and waits == []


def test_long_retry_after_is_not_shortened(env):
    app, client, waits = env
    r = submit(client, "long_rate_limit")
    assert r.status_code == 503 and r.headers["Retry-After"] == "60"
    assert r.json()["meta"]["stop_reason"] == "wait_budget"
    assert waits == [] and not app.state.provider.state.records


def test_concurrent_same_key_creates_once(env):
    app, _, _ = env
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await asyncio.gather(*[client.post("/api/v1/work-orders", json=PAYLOAD,
                        headers={**AUTH, "Idempotency-Key": "concurrent-key"}) for _ in range(12)])
    results = asyncio.run(run())
    assert all(r.status_code == 201 for r in results)
    assert len({r.json()["data"]["id"] for r in results}) == 1
    assert len(app.state.provider.state.records) == 1


def test_webhook_completes_once_even_with_duplicate_delivery(env):
    app, client, _ = env
    event = event_for(client)
    raw, headers = signed(app, event)
    first = client.post("/api/v1/webhooks/provider", content=raw, headers=headers)
    second = client.post("/api/v1/webhooks/provider", content=raw, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["duplicate"] is False and second.json()["data"]["duplicate"] is True
    assert app.state.orders[event["work_order_id"]]["completion_count"] == 1


def test_raw_body_tampering_is_rejected_before_state_changes(env):
    app, client, _ = env
    event = event_for(client)
    raw, headers = signed(app, event)
    r = client.post("/api/v1/webhooks/provider", content=raw + b" ", headers=headers)
    assert r.status_code == 401
    assert app.state.orders[event["work_order_id"]]["status"] == "queued"
    assert not app.state.events


@pytest.mark.parametrize("offset", [-600, 600])
def test_stale_and_future_signed_events_are_rejected(env, offset):
    app, client, _ = env
    raw, headers = signed(app, event_for(client), int(time.time()) + offset)
    r = client.post("/api/v1/webhooks/provider", content=raw, headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "expired_signature"
    assert not app.state.events


def test_malformed_timestamp_does_not_raise_server_error(env):
    _, client, _ = env
    r = client.post("/api/v1/webhooks/provider", content=b"{}",
                    headers={"X-Webhook-Timestamp": "9" * 1000, "X-Webhook-Signature": "a" * 64})
    assert r.status_code == 401


def test_new_event_for_completed_order_does_not_repeat_side_effect(env):
    app, client, _ = env
    event = event_for(client)
    for name in ["evt_first", "evt_second"]:
        raw, headers = signed(app, {**event, "id": name})
        assert client.post("/api/v1/webhooks/provider", content=raw, headers=headers).status_code == 200
    assert app.state.orders[event["work_order_id"]]["completion_count"] == 1


def test_conflicting_event_id_is_rejected(env):
    app, client, _ = env
    event = event_for(client)
    raw, headers = signed(app, event)
    client.post("/api/v1/webhooks/provider", content=raw, headers=headers)
    raw, headers = signed(app, {**event, "work_order_id": "wo_000000000000"})
    assert client.post("/api/v1/webhooks/provider", content=raw, headers=headers).status_code == 409


def test_unknown_order_event_is_not_consumed(env):
    app, client, _ = env
    raw, headers = signed(app, {"id": "evt_unknown", "type": "work_order.completed", "work_order_id": "wo_000000000000"})
    assert client.post("/api/v1/webhooks/provider", content=raw, headers=headers).status_code == 404
    assert not app.state.events


def test_cursor_pagination_covers_all_orders_without_duplicates(env):
    _, client, _ = env
    for i in range(5):
        submit(client, key=f"paginate-key-{i}")
    ids, cursor = [], None
    while True:
        params = {"limit": 2}
        if cursor:
            params["after"] = cursor
        r = client.get("/api/v1/work-orders", params=params, headers=AUTH).json()
        ids.extend(x["id"] for x in r["data"])
        cursor = r["meta"]["next_cursor"]
        if not cursor:
            break
    assert len(ids) == len(set(ids)) == 5
    assert client.get("/api/v1/work-orders?after=invalid!!", headers=AUTH).status_code == 422


def test_webhook_lab_controls_do_not_expose_secret(env):
    app, client, _ = env
    event = event_for(client)
    for mode, code in [("tampered", 401), ("expired", 401), ("valid", 200)]:
        r = client.post("/api/v1/lab/webhook-deliveries", headers=AUTH,
                        json={"work_order_id": event["work_order_id"], "event_id": "evt_demo", "mode": mode})
        assert r.status_code == code
        assert app.state.webhook_secret not in r.text and app.state.provider_token not in r.text


def test_retry_after_numeric_date_and_invalid_values():
    now = 1_790_000_000
    assert retry_after_seconds("2", now) == 2
    assert retry_after_seconds(format_datetime(datetime.fromtimestamp(now + 8, timezone.utc)), now) == 8
    for value in [None, "nonsense", "-2", "nan", "inf"]:
        assert retry_after_seconds(value, now) is None


def test_structured_logs_do_not_contain_credentials_or_body(env, caplog):
    app, client, _ = env
    with caplog.at_level("INFO", logger="reliability_lab"):
        submit(client, "lost_response")
    assert "provider_status=504" in caplog.text and "provider_status=201" in caplog.text
    assert app.state.provider_token not in caplog.text
    assert PUBLIC_DEMO_TOKEN not in caplog.text and PAYLOAD["asset_id"] not in caplog.text


def test_openapi_exposes_contract_and_bearer_scheme(env):
    _, client, _ = env
    spec = client.get("/openapi.json").json()
    operation = spec["paths"]["/api/v1/work-orders"]["post"]
    assert "HTTPBearer" in spec["components"]["securitySchemes"]
    assert any("HTTPBearer" in item for item in operation["security"])
    assert {"201", "409", "422", "502", "503"}.issubset(operation["responses"])


@pytest.mark.parametrize("scenario,status,source", [
    ("healthy", 201, "mock-provider"), ("rate_limit", 429, "mock-provider"),
    ("unavailable", 503, "mock-provider"), ("permanent_failure", 503, "mock-provider"),
    ("provider_auth", 401, "mock-provider"), ("long_rate_limit", 429, "mock-provider"),
    ("lost_response", 504, "transport-simulation"),
])
def test_probe_preserves_failure_boundary_without_retry(env, scenario, status, source):
    app, client, waits = env
    r = client.post("/api/v1/lab/provider-probe", json=PAYLOAD,
                    headers={**AUTH, "Idempotency-Key": "probe-one", "X-Lab-Scenario": scenario})
    assert r.status_code == status and r.headers["X-Lab-Response-Source"] == source
    assert waits == [] and app.state.orders == {}
    assert all(n == 1 for n in app.state.provider.state.attempts.values())
    assert app.state.provider_token not in r.text and app.state.webhook_secret not in r.text
    if status == 429:
        assert r.headers["Retry-After"] == ("60" if scenario == "long_rate_limit" else "1")


def test_probe_auth_and_body_limit_stop_before_provider(env):
    app, client, _ = env
    headers = {"Idempotency-Key": "probe-auth"}
    r = client.post("/api/v1/lab/provider-probe", json=PAYLOAD, headers=headers)
    assert r.status_code == 401 and r.headers["X-Lab-Response-Source"] == "integration"
    r = client.post("/api/v1/lab/provider-probe", content=b"x" * 65537, headers={**headers, **AUTH})
    assert r.status_code == 413 and not app.state.provider.state.attempts


def test_probe_raw_invalid_json_is_validated_by_provider(env):
    _, client, _ = env
    r = client.post("/api/v1/lab/provider-probe", content='{"broken":',
                    headers={**AUTH, "Idempotency-Key": "probe-json", "Content-Type": "application/json"})
    assert r.status_code == 422 and r.headers["X-Lab-Response-Source"] == "mock-provider"
    assert r.json()["detail"][0]["type"] == "json_invalid"


def test_probe_lost_response_replay_then_conflict(env):
    app, client, _ = env
    headers = {**AUTH, "Idempotency-Key": "probe-replay", "X-Lab-Scenario": "lost_response"}
    assert client.post("/api/v1/lab/provider-probe", json=PAYLOAD, headers=headers).status_code == 504
    replay = client.post("/api/v1/lab/provider-probe", json=PAYLOAD, headers=headers)
    assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
    conflict = client.post("/api/v1/lab/provider-probe", json={**PAYLOAD, "priority": "urgent"}, headers=headers)
    assert conflict.status_code == 409 and len(app.state.provider.state.records) == 1
    assert app.state.orders == {}


def test_explorer_contract_describes_probe_errors_and_body(env):
    _, client, _ = env
    op = client.get("/openapi.json").json()["paths"]["/api/v1/lab/provider-probe"]["post"]
    assert {"201", "401", "409", "413", "422", "429", "503", "504"} <= op["responses"].keys()
    assert "asset_id" in op["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert client.get("/explorer").status_code == 200
