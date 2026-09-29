# API Reliability Lab

**Status:** Working local portfolio prototype · September 2026  
**Build:** Python, FastAPI, HTTPX, browser JavaScript, pytest · Developed with AI assistance

## The problem

An API timeout can hide a successful write. Retrying a work-order submission without knowing whether the provider accepted it can create a duplicate. Customer-facing engineers need to diagnose the failure, recover safely, and explain the next step.

## The demonstration

This lab uses synthetic utility work orders and a mock provider to demonstrate:

- Recovery after a response is lost following a successful write.
- Stable idempotency keys and rejection of conflicting payload reuse.
- Authentication and field-level validation before provider work.
- Retry-After handling, bounded backoff, and escalation after the retry limit.
- Signed webhook verification and duplicate-effect suppression.
- Correlation IDs, inspectable attempt traces, OpenAPI contracts, and cursor pagination.

## Evidence

- **38 automated tests passed** during initial validation, including 12 concurrent identical submissions producing one provider record.
- Browser demo verifies lost-response recovery, validation feedback, rate-limit waiting, and duplicate webhook handling.
- Source, request/response examples, and [interview walkthrough](WALKTHROUGH.md) explain decisions and tradeoffs.
- These are controlled functional checks; they are not load tests, uptime measurements, or production customer outcomes.

## Connection to my experience

My Emerson implementation work included environment configuration, API integration troubleshooting, testing, and customer training. This separate project makes related integration concepts inspectable in a public-safe setting. It does not reproduce employer code or claim to be a delivered customer system.

## What remains unproven

Durability across restarts, distributed concurrency, real network failure behavior, production authorization, and live vendor integrations are outside this version. See the [README limitations](README.md#deliberate-limits).

## Suggested portfolio card

**API Reliability Lab — Safe retries, duplicate prevention, and webhook verification**

An interactive Python integration lab showing how to diagnose failed requests, recover a lost response without duplicating a write, and process signed events safely. Includes OpenAPI documentation, failure traces, and 38 passing automated tests. Local prototype developed with AI assistance.

Suggested links after publishing: live demo or short recording · source code · test suite · this case study.
