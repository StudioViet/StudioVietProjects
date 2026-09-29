"""Deliberately fallible provider. No real utility/customer systems are contacted."""

import hashlib
import hmac
import json
import threading
import uuid

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from .models import WorkOrderInput


def fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def provider_error(status: int, code: str, message: str, headers=None):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


def create_provider(token: str) -> FastAPI:
    app = FastAPI(title="Mock work-order provider", version="1.0.0")
    app.state.records = {}
    app.state.attempts = {}
    app.state.lock = threading.Lock()

    @app.post("/v1/work-orders", status_code=201)
    async def create_order(
        body: WorkOrderInput,
        authorization: str = Header(default=""),
        idempotency_key: str = Header(min_length=8, max_length=128),
        x_lab_scenario: str = Header(default="healthy"),
    ):
        if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            return provider_error(401, "invalid_credentials", "Provider credentials were rejected.")
        payload = body.model_dump()
        digest = fingerprint(payload)
        # No await inside this lock: reservation + creation is atomic in this process.
        with app.state.lock:
            saved = app.state.records.get(idempotency_key)
            if saved:
                if saved["fingerprint"] != digest:
                    return provider_error(409, "idempotency_conflict", "This key belongs to a different payload.")
                return JSONResponse({"data": saved["order"]}, status_code=201,
                                    headers={"Idempotency-Replayed": "true"})
            attempt = app.state.attempts.get(idempotency_key, 0) + 1
            app.state.attempts[idempotency_key] = attempt
            if x_lab_scenario == "rate_limit" and attempt == 1:
                return provider_error(429, "rate_limited", "Try again after the advertised delay.", {"Retry-After": "1"})
            if x_lab_scenario == "long_rate_limit":
                return provider_error(429, "rate_limited", "The provider requires a longer wait.", {"Retry-After": "60"})
            if x_lab_scenario == "permanent_failure" or (x_lab_scenario == "unavailable" and attempt <= 2):
                return provider_error(503, "temporarily_unavailable", "Provider temporarily unavailable.")
            order = {"id": "wo_" + uuid.uuid4().hex[:12], **payload, "status": "queued"}
            app.state.records[idempotency_key] = {"fingerprint": digest, "order": order}
        if x_lab_scenario == "lost_response" and attempt == 1:
            # Inject at the transport boundary AFTER the provider commits the order.
            # This is a simulated network failure, not an actual socket timeout.
            raise httpx.ReadTimeout("Simulated response loss after commit")
        return JSONResponse({"data": order}, status_code=201,
                            headers={"Idempotency-Replayed": "false", "Location": f"/v1/work-orders/{order['id']}"})

    return app
