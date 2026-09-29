"""Retry only transient failures, and only with a provider-backed idempotency key."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger("reliability_lab")
RETRYABLE = {429, 502, 503, 504}


def retry_after_seconds(value: str | None, now: float) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        # NaN and infinity must not become unbounded sleeps.
        if 0 <= seconds < float("inf"):
            return seconds
        return None
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, dt.timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return None


@dataclass
class Result:
    status: int
    body: dict
    trace: list
    replayed: bool = False
    stop_reason: str = "complete"


class ProviderClient:
    def __init__(self, provider, token: str, sleep=asyncio.sleep, jitter=None):
        self.provider = provider
        self.token = token
        self.sleep = sleep
        self.jitter = jitter or (lambda: random.uniform(0, 0.08))

    async def submit(self, payload: dict, key: str, scenario: str, request_id: str) -> Result:
        trace = []
        total_wait = 0.0
        token = "deliberately-invalid" if scenario == "provider_auth" else self.token
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key,
                   "X-Lab-Scenario": scenario, "X-Request-ID": request_id}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.provider),
                                    base_url="http://mock-provider", timeout=2.0) as client:
            for attempt in range(1, 4):
                response = None
                try:
                    response = await client.post("/v1/work-orders", json=payload, headers=headers)
                    status = response.status_code
                    body = response.json()
                except httpx.TimeoutException:
                    status = 504
                    body = {"error": {"code": "provider_timeout", "message": "No response received; outcome may be unknown."}}
                row = {"attempt": attempt, "status": status, "request_id": request_id,
                       "delay_seconds": 0, "action": "", "replayed": False}
                trace.append(row)
                log.info("request_id=%s attempt=%s provider_status=%s", request_id, attempt, status)
                if status < 400:
                    row["replayed"] = response.headers.get("Idempotency-Replayed") == "true"
                    row["action"] = "Recovered the original result" if row["replayed"] else "Accepted"
                    return Result(status, body, trace, replayed=row["replayed"])
                if status not in RETRYABLE:
                    row["action"] = "Stop: this error needs a change, not a retry"
                    return Result(status, body, trace, stop_reason="non_retryable")
                if attempt == 3:
                    row["action"] = "Stop: three-attempt limit reached"
                    return Result(status, body, trace, stop_reason="attempt_limit")
                advised = retry_after_seconds(response.headers.get("Retry-After"), time.time()) if response is not None else None
                delay = advised if advised is not None else min(0.2 * 2 ** (attempt - 1) + self.jitter(), 1.0)
                if total_wait + delay > 3.0:
                    row["action"] = "Stop: Retry-After exceeds the interactive wait budget"
                    return Result(status, body, trace, stop_reason="wait_budget")
                row["delay_seconds"] = round(delay, 3)
                row["action"] = "Wait for Retry-After" if advised is not None else "Back off, then retry with the SAME key"
                total_wait += delay
                await self.sleep(delay)
        raise RuntimeError("Retry loop did not terminate")
