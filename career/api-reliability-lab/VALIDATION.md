# Validation — September 29, 2026

## Automated

Command: `.venv/Scripts/python.exe -m pytest -q`

Result: **38 passed** in the locked environment. One Starlette deprecation warning concerns its HTTPX test-client adapter; no failing tests.

Coverage includes authentication, field validation, required idempotency keys, 429 Retry-After, transient recovery, lost responses after committed writes, payload/key conflicts, three-attempt limits, upstream authentication mapping, long-delay budgets, concurrent submissions, raw-body webhook signatures, stale/future events, conflicting and duplicate events, cursor pagination, credential-safe logs, and the OpenAPI security contract.

## Browser

- Explorer: raw provider 429 includes Retry-After and identifies the mock-provider source.
- Explorer: integration recovers through 429 → 201; trace records the one-second wait and both attempts.
- Explorer: malformed raw JSON returns server-side 422; changed payload with the same key returns 409; the current request copies as Bash cURL.
- Provider-probe tests cover seven scenarios, caller authentication, body limits, malformed JSON, replay after a lost response, conflict prevention, and the documented request/error contract.

- Lost-response scenario: HTTP 201 after simulated 504; two provider attempts, one new work order; original result recovered.
- Duplicate webhook: two HTTP 200 deliveries; second marked duplicate; completed order has `completion_count: 1`.
- Invalid payload: HTTP 422 with corrective feedback; no provider attempt.
- Rate limit: HTTP 429 then 201, with a one-second Retry-After wait displayed in the trace.
- Desktop layout visually inspected in the Codex browser. No mobile-specific viewport check was performed.

These results describe the synthetic local environment. They do not establish cloud reliability, real network behavior, external vendor compatibility, or production security.
