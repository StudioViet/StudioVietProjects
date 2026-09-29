import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import uuid

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .client import ProviderClient
from .models import CompletionEvent, Scenario, WebhookDelivery, WorkOrderInput
from .provider import create_provider

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DEMO_TOKEN = "demo-client-token"


def sign_event(secret: str, timestamp: int, raw: bytes) -> str:
    return hmac.new(secret.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()


def create_app(sleep=asyncio.sleep, jitter=None) -> FastAPI:
    app = FastAPI(title="API Reliability Lab", version="1.1.0",
                  description="Local portfolio sandbox. Synthetic work orders; mock provider; no employer systems. "
                  "Use the public demo bearer token `demo-client-token` unless LAB_CLIENT_TOKEN is set.")
    app.state.client_token = os.getenv("LAB_CLIENT_TOKEN", PUBLIC_DEMO_TOKEN)
    app.state.provider_token = secrets.token_hex(24)
    app.state.webhook_secret = secrets.token_hex(32)
    app.state.orders = {}
    app.state.events = {}
    app.state.lock = threading.Lock()
    provider = create_provider(app.state.provider_token)
    app.state.provider = provider
    app.state.provider_client = ProviderClient(provider, app.state.provider_token, sleep=sleep, jitter=jitter)
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not hmac.compare_digest(credentials.credentials.encode(), app.state.client_token.encode()):
            raise HTTPException(401, "Missing or invalid lab bearer token", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        proposed = request.headers.get("X-Request-ID", "")
        request.state.request_id = proposed if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", proposed) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        if "X-Lab-Response-Source" not in response.headers:
            response.headers["X-Lab-Response-Source"] = "integration"
        return response

    def error(request: Request, status: int, code: str, message: str, details=None, headers=None):
        return JSONResponse({"error": {"code": code, "message": message, "details": details or []},
                             "meta": {"request_id": request.state.request_id, "trace": []}},
                            status_code=status, headers=headers)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, "unauthorized" if exc.status_code == 401 else "request_error", str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Exclude the submitted input: validation responses must not echo secrets/data.
        details = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in exc.errors()]
        return error(request, 422, "validation_error", "Correct the request before retrying.", details)

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/explorer", include_in_schema=False)
    async def explorer():
        return FileResponse(ROOT / "static" / "explorer.html")

    @app.post("/api/v1/lab/provider-probe", dependencies=[Depends(authenticate)],
              tags=["Sandbox controls"], status_code=201,
              summary="Inspect one mock-provider attempt without retries",
              openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
                  "schema": WorkOrderInput.model_json_schema()}}}},
              responses={401: {"description": "Lab or provider authentication failed; inspect X-Lab-Response-Source"},
                         409: {"description": "Idempotency key reused with a different body"},
                         413: {"description": "Body exceeds 64 KiB"},
                         422: {"description": "Invalid headers or provider request body"},
                         429: {"description": "Provider rate limited; inspect Retry-After"},
                         503: {"description": "Provider unavailable"},
                         504: {"description": "Injected response loss; write outcome unknown to caller"}})
    async def provider_probe(request: Request,
                             idempotency_key: str = Header(pattern=r"^[a-zA-Z0-9_-]{8,128}$"),
                             x_lab_scenario: Scenario = Header(default="healthy")):
        """A fixed-target local inspection bridge, not a live external API or arbitrary URL proxy.

        Sends exactly one request to the mock provider. No retries, no integration order
        registration. Provider credentials stay on the server. Reuse the same key and body
        after a timeout to inspect safe replay. Scenario headers are teaching controls.
        """
        raw = await request.body()
        if len(raw) > 65536:
            return error(request, 413, "payload_too_large", "Probe body exceeds the lab's 64 KiB limit.")
        token = "invalid-demo-provider-token" if x_lab_scenario == "provider_auth" else app.state.provider_token
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=provider), base_url="http://mock-provider", timeout=2) as client:
            try:
                response = await client.post("/v1/work-orders", content=raw, headers={
                    "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key, "X-Lab-Scenario": x_lab_scenario,
                    "X-Request-ID": request.state.request_id})
            except httpx.TimeoutException:
                return error(request, 504, "provider_timeout", "Injected response loss after commit. Outcome unknown; retry with the same key and body.",
                             headers={"X-Lab-Response-Source": "transport-simulation"})
        headers = {"X-Lab-Response-Source": "mock-provider"}
        for name in ("Retry-After", "Idempotency-Replayed"):
            if name in response.headers:
                headers[name] = response.headers[name]
        return JSONResponse(response.json(), status_code=response.status_code, headers=headers)

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "local-sandbox"}

    @app.get("/api/v1/lab/stats", dependencies=[Depends(authenticate)], tags=["Sandbox controls"])
    async def stats():
        return {"provider_orders_created": len(provider.state.records), "accepted_orders": len(app.state.orders),
                "webhook_events_consumed": len(app.state.events)}

    @app.post("/api/v1/work-orders", dependencies=[Depends(authenticate)], status_code=201,
              tags=["Work orders"],
              responses={401: {"description": "Invalid caller credentials; provider not contacted"},
                         409: {"description": "Key reused with different data"}, 422: {"description": "Invalid input"},
                         502: {"description": "Provider credential/configuration failure"},
                         503: {"description": "Provider unavailable or retry budget exhausted"}})
    async def submit_order(body: WorkOrderInput, request: Request,
                           idempotency_key: str = Header(pattern=r"^[a-zA-Z0-9_-]{8,128}$"),
                           x_lab_scenario: Scenario = Header(default="healthy")):
        result = await app.state.provider_client.submit(body.model_dump(), idempotency_key,
                                                        x_lab_scenario, request.state.request_id)
        content = dict(result.body)
        headers = {"Idempotency-Replayed": str(result.replayed).lower()}
        status = result.status
        if status < 400:
            order = content["data"]
            with app.state.lock:
                app.state.orders.setdefault(order["id"], {**order, "completion_count": 0})
                content["data"] = dict(app.state.orders[order["id"]])
            headers["Location"] = f"/api/v1/work-orders/{order['id']}"
        elif status == 401:
            # The caller IS authenticated; the provider rejected the server's key.
            status = 502
            content = {"error": {"code": "provider_authentication_failed", "message": "The integration's provider credentials need attention."}}
        elif status == 429 and result.stop_reason == "wait_budget":
            status = 503
            headers["Retry-After"] = "60"
        content["meta"] = {"request_id": request.state.request_id, "trace": result.trace,
                           "stop_reason": result.stop_reason, "provider_status": result.status,
                           "provider_orders_created": len(provider.state.records)}
        return JSONResponse(content, status_code=status, headers=headers)

    @app.get("/api/v1/work-orders", dependencies=[Depends(authenticate)], tags=["Work orders"])
    async def list_orders(request: Request, limit: int = Query(default=10, ge=1, le=50), after: str | None = None):
        # Insertion sequence is stable for this append-only, single-process demo.
        position = 0
        if after:
            try:
                decoded = base64.b64decode(after.encode(), altchars=b"-_", validate=True).decode()
                if not decoded.startswith("order:"):
                    raise ValueError
                position = int(decoded[6:])
                if position < 0:
                    raise ValueError
            except (ValueError, UnicodeError):
                return error(request, 422, "invalid_cursor", "Use the next_cursor returned by this endpoint.")
        with app.state.lock:
            orders = [dict(o) for o in app.state.orders.values()]
        end = position + limit
        next_cursor = base64.urlsafe_b64encode(f"order:{end}".encode()).decode() if end < len(orders) else None
        return {"data": orders[position:end], "meta": {"next_cursor": next_cursor, "request_id": request.state.request_id}}

    @app.get("/api/v1/work-orders/{order_id}", dependencies=[Depends(authenticate)], tags=["Work orders"],
             responses={404: {"description": "Work order not found"}})
    async def get_order(order_id: str, request: Request):
        with app.state.lock:
            order = app.state.orders.get(order_id)
            result = dict(order) if order else None
        if result is None:
            return error(request, 404, "not_found", "No work order with this ID.")
        return {"data": result, "meta": {"request_id": request.state.request_id}}

    @app.post("/api/v1/webhooks/provider")
    async def receive_webhook(request: Request, x_webhook_timestamp: str = Header(default=""),
                              x_webhook_signature: str = Header(default="")):
        raw = await request.body()
        if len(raw) > 65536:
            return error(request, 413, "payload_too_large", "Webhook body exceeds the lab's 64 KiB limit.")
        if not re.fullmatch(r"[0-9]{1,12}", x_webhook_timestamp) or not re.fullmatch(r"[a-f0-9]{64}", x_webhook_signature):
            return error(request, 401, "invalid_signature", "Missing or malformed signing timestamp.")
        timestamp = int(x_webhook_timestamp)
        expected = sign_event(app.state.webhook_secret, timestamp, raw)
        if not hmac.compare_digest(expected, x_webhook_signature):
            return error(request, 401, "invalid_signature", "Signature does not match the raw body.")
        if abs(time.time() - timestamp) > 300:
            return error(request, 401, "expired_signature", "Signature is outside the five-minute window.")
        try:
            event = CompletionEvent.model_validate_json(raw)
        except ValidationError:
            return error(request, 422, "invalid_event", "Webhook does not match the event schema.")
        # Semantic fingerprint tolerates harmless JSON whitespace/order changes.
        digest = hashlib.sha256(json.dumps(event.model_dump(), sort_keys=True).encode()).hexdigest()
        with app.state.lock:
            previous = app.state.events.get(event.id)
            if previous:
                if previous != digest:
                    return error(request, 409, "event_conflict", "Event ID was reused with different contents.")
                return {"data": {"accepted": True, "duplicate": True}, "meta": {"request_id": request.state.request_id}}
            order = app.state.orders.get(event.work_order_id)
            if not order:
                return error(request, 404, "unknown_work_order", "Work order not found; event was not consumed.")
            if order["status"] != "completed":
                order["status"] = "completed"
                order["completion_count"] += 1
            app.state.events[event.id] = digest
        return {"data": {"accepted": True, "duplicate": False}, "meta": {"request_id": request.state.request_id}}

    @app.post("/api/v1/lab/webhook-deliveries", dependencies=[Depends(authenticate)], tags=["Sandbox controls"])
    async def deliver_webhook(body: WebhookDelivery):
        """Local test sender, not a production API. Secret never leaves the server."""
        event = {"id": body.event_id, "type": "work_order.completed", "work_order_id": body.work_order_id}
        raw = json.dumps(event, separators=(",", ":")).encode()
        timestamp = int(time.time()) - (600 if body.mode == "expired" else 0)
        signature = sign_event(app.state.webhook_secret, timestamp, raw)
        if body.mode == "tampered":
            raw += b" "  # Same parsed JSON; different signed bytes.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab") as client:
            response = await client.post("/api/v1/webhooks/provider", content=raw,
                                         headers={"Content-Type": "application/json", "X-Webhook-Timestamp": str(timestamp),
                                                  "X-Webhook-Signature": signature})
        return JSONResponse({"delivery_status": response.status_code, "event": event,
                             "response": response.json()}, status_code=response.status_code)

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    app.mount("/mock-provider", provider)
    return app


app = create_app()
