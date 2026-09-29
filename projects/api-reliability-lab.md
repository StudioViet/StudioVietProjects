# API Reliability Lab

**Career portfolio · Technical implementation / Customer success engineering**  
**Status:** Working local portfolio prototype · September 2026  
**Build:** Python, FastAPI, HTTPX, JavaScript, pytest · Developed with AI assistance

[Source and local setup](../career/api-reliability-lab/README.md) · [Tests](../career/api-reliability-lab/tests/test_api.py) · [OpenAPI contract](../career/api-reliability-lab/openapi.json) · [Career portfolio](../PORTFOLIO.md)

## The problem

An API timeout can hide a successful write. Retrying without knowing whether the provider accepted it can create a duplicate. A customer-facing engineer needs to identify the failure, recover safely, and explain the next step.

## What I built

A synthetic utility work-order integration with a deliberately fallible mock provider and two ways to inspect it:

- **Guided reliability lab:** Trigger failures and watch the retry decisions, order count, and webhook results.
- **Swagger-style API explorer:** Choose an endpoint from the live OpenAPI contract, edit headers and raw JSON, execute requests, and inspect actual statuses, response headers, error details, correlation IDs, retry traces, and cURL examples.

The provider probe makes one attempt without retries. The integration applies authentication, validation, and bounded recovery. This makes the boundary visible: a raw provider **429** can become a successful integration **201**, with both attempts preserved in the trace.

## Decisions demonstrated

| Failure | Response | Why it matters |
| --- | --- | --- |
| Response lost after the provider commits | Retry using the original idempotency key and recover the existing order | Avoid duplicate writes when the outcome is uncertain |
| Same key reused with different data | Return 409 | Prevent a key from identifying two different operations |
| Invalid caller token or malformed input | Return 401 or 422 with diagnostic details | Fix the request before creating provider work |
| Provider credentials rejected | Raw probe: 401; integration: 502 | Direct investigation to the integration configuration |
| Rate limit or temporary outage | Respect Retry-After and apply bounded backoff | Recover without unlimited retries or retrying too early |
| Tampered, expired, or repeated webhook | Verify raw-body HMAC and timestamp; suppress duplicate effects | Validate events before changing state |

## Evidence

- **38 automated tests passed** on September 29, 2026, including 12 concurrent identical submissions producing one provider record.
- Browser checks confirmed raw provider 429 with Retry-After and integration recovery through 429 → 201.
- Initial guided-lab checks verified lost-response recovery, invalid-payload feedback, and duplicate webhook handling.
- [Validation record](../career/api-reliability-lab/VALIDATION.md) and [interview walkthrough](../career/api-reliability-lab/WALKTHROUGH.md).

These are controlled functional checks, not load tests, production outcomes, or uptime measurements.

## Connection to my experience

My Emerson implementation work included environment configuration, API integration troubleshooting, testing, and customer training. This independent project makes related integration concepts inspectable using synthetic data. It does not reproduce employer code or claim to be a delivered customer system.

## Review it

Follow the [local setup](../career/api-reliability-lab/README.md#run-locally), then open `/explorer`. Run a rate-limit request through the provider probe and compare it with the integration endpoint. Next, submit successfully and change the body without changing the key to inspect a 409 conflict.

The source is published here. The interactive backend runs locally; it is not a public hosted API.

## Deliberate limits

In-memory state, single-process concurrency, injected failures, and a mock provider. No live Stedi, Rescale, utility, or customer systems are connected. Durability, distributed behavior, real socket failures, production authorization, and deployment hardening remain future work.
