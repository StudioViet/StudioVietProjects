# Explain the lab in an interview

## 20-second introduction

“I built an AI-assisted API reliability lab around a synthetic utility work-order integration. The interesting case is when the provider creates an order but its response is lost. The lab shows how a stable idempotency key recovers the original result without creating a second order. It also demonstrates authentication, validation, bounded retries, and signed webhook handling.”

This is a portfolio build, distinct from professional delivery at Emerson. Attribute the assisted build honestly and be prepared to explain or change the logic.

## Three-minute demonstration

1. **Establish the problem.** A customer submits a work order. The provider commits it; the response never arrives. The integration knows the outcome is uncertain, not that creation failed.
2. **Run “Response lost after commit.”** Point to the 504 then 201 trace, two attempts, and one new provider order. Show the returned ID and `Idempotency-Replayed: true`.
3. **Open `lab/provider.py`.** Explain that the key is associated with a canonical payload fingerprint and the original result. The lookup and creation occur under one lock. The response-loss injection happens after creation.
4. **Explain the boundary.** The duplicate guarantee depends on provider behavior. Adding an Idempotency-Key header to a vendor that ignores it does not make POST safe to retry.
5. **Run a non-retryable case.** Invalid data is rejected with 422 and a field name. An invalid caller token returns 401. Neither should reach the provider.
6. **Run “Rate limit.”** The client waits for Retry-After. Contrast the long-delay case: it stops rather than retrying earlier than permitted.
7. **Deliver a webhook twice.** Both valid deliveries receive 200. The second reports duplicate; `completion_count` stays at one. A tampered raw body fails signature verification before state changes.
8. **Close with the real-world next step.** Move state into transactional storage, add a durable event inbox, isolate tenants, and test real network behavior before considering production use.

## Questions a technical interviewer may ask

| Question | Answer to understand, not memorize |
|---|---|
| Why not generate a new key for each retry? | It would identify a new operation and can create duplicates. Reuse the original key for the same logical operation. |
| What if the payload changes? | Return 409 rather than silently returning a result for a different operation. |
| Is this exactly-once delivery? | No. Delivery can repeat. The provider deduplicates writes and the receiver suppresses duplicate effects within the retained single-process state. |
| Why do a provider's 401 and a caller's 401 produce different results? | The caller may be authenticated while the integration's provider credential is invalid. Report the correct failure boundary; don't tell the customer to fix the wrong token. |
| Why cap retries? | Bound latency and avoid amplifying an outage. Backoff and jitter spread the work; they do not fix a permanent problem. |
| Why verify the raw webhook body? | Reformatting JSON changes the bytes. Verify the received bytes with the shared secret before parsing and applying effects. |
| Why verify time as well as a signature? | A valid signed payload could be captured and replayed. A time window limits stale replay; event-ID deduplication handles repeats within the window. |
| Are in-memory locks production-safe? | They protect this process only. Multi-worker deployments need a durable shared store and atomic uniqueness/transaction guarantees. |
| What if a completion event arrives early? | This lab returns 404 without consuming the event. Production should use a durable inbox with retry/reconciliation rather than assume ordering. |
| What happens when the service restarts? | Current state and deduplication history disappear. The lab does not claim durable idempotency. |
| What would you tell a customer during an outage? | State the affected operation, confirmed facts, uncertainty, current owner, and next update. Use the request ID to connect the conversation to technical evidence. |

## Customer update example

“Your submission reached the provider, but the response was lost. We retried using the original operation key and recovered the same work-order ID. The trace shows one order was created. I'll use request ID X to review the response failure and confirm whether other submissions were affected.”

Only use the “one order” conclusion when provider evidence supports it. Without idempotency support or a lookup path, a timeout can remain ambiguous.

## Small improvements to implement personally

- Add a new failure scenario and explain why it is or isn't retryable.
- Write a test for two concurrent webhook deliveries and demonstrate one effect.
- Add a transactional SQLite store and a restart test for idempotency persistence.
- Replace the in-process provider transport with a separate local HTTP server and test a genuine delayed response.

Each change should produce a before/after explanation, a meaningful test, and a clear limitation. These are optional next iterations, not claims about the current version.
