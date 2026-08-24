---
article_id: BM-006
title: API and Webhook Changes for the Billing Migration
product_area: developer-api
last_updated: 2026-08-09
---

# API and Webhook Changes for the Billing Migration

## Versioned endpoints

Ledger v2 is served from the same /v1 API surface. There is no /v2 path. The
difference is visible in the response body: invoice objects gain an
engine_version field and a settled_at timestamp, and the deprecated
next_payment_attempt field is null for every workspace on Ledger v2. Clients
that treat a null next_payment_attempt as "no retry scheduled" will silently
stop retrying. Read the new retry_schedule array instead.

## Idempotency keys on the billing API

Ledger v2 enforces idempotency keys far more strictly than v1 did. In v1 an
idempotency key was scoped to the endpoint, so the same key could be reused
against POST /v1/invoices and POST /v1/charges without conflict. In v2 the key
is scoped to the workspace and the whole billing surface. Reusing a key that
was already used anywhere in the workspace within the last twenty-four hours
returns 409 with an idempotency_reuse error body, even if the original request
targeted a different endpoint. Client libraries that derive keys from a
request hash rather than from a fresh UUID are the usual casualty. Generate a
fresh UUID per logical operation.

## Webhook delivery during cutover

Webhooks are paused for the duration of Phase 3, which is under an hour.
Events generated while delivery is paused are queued, not dropped, and are
delivered in original order once cutover completes. The queue holds events for
seventy-two hours. Signature verification is unchanged and the signing secret
is not rotated by the migration.

## Troubleshooting

| Error code | Cause | Fix |
| --- | --- | --- |
| ERR-4110 | Webhook endpoint returned a non-2xx during the post-cutover flush | No action needed for the first six hours; the flush retries with backoff. After six hours, replay from Developers then Webhooks then Replay |
| ERR-4111 | Idempotency key reused within the workspace in the last 24 hours | Generate a fresh UUID per logical operation and retry. Do not derive the key from a request hash |
| ERR-4112 | Client is still reading next_payment_attempt, which is null on v2 | Update the client to read the retry_schedule array. The field is not restored |
| ERR-4113 | Webhook queue exceeded the 72-hour retention during an extended outage | The dropped events cannot be replayed. Reconcile by polling GET /v1/invoices for the affected window |
| ERR-4114 | Request used a /v2 path that does not exist | Use the /v1 path. Ledger v2 is served from /v1 |
| ERR-4115 | Signature verification failed after the customer rotated their secret mid-cutover | Re-issue the signing secret in Developers then Webhooks and update the endpoint. The migration itself does not rotate secrets |
