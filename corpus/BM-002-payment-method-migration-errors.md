---
article_id: BM-002
title: Payment Method Migration Errors
product_area: payments
last_updated: 2026-08-02
---

# Payment Method Migration Errors

## Why payment methods have to move separately

Ledger v2 stores payment instruments as tokenised references held by the
payment service provider rather than as rows in our own vault. Every stored
card, SEPA mandate and ACH authorisation therefore has to be re-tokenised
before a workspace can leave the dual-write phase. Re-tokenisation is
initiated automatically when a workspace enters Phase 2 and normally finishes
within four hours for a workspace with fewer than five hundred stored
instruments.

Re-tokenisation never moves money. It exchanges an internal vault id for a
provider token. Customers are not charged, and no authorisation hold is
placed on the card. If a customer reports a pending charge during migration,
that charge is a real charge from ordinary usage and is unrelated to the
re-tokenisation job.

## Idempotency during retries

The re-tokenisation worker retries each instrument up to five times. Every
retry reuses the same idempotency key, which is derived from the internal
vault id and the migration run id. If you manually re-queue a single
instrument from the admin console while the automatic retry chain is still
in flight, the manual request carries a freshly generated idempotency key and
the provider will see two distinct requests for the same instrument. That is
what produces duplicate tokens. Wait for the automatic chain to exhaust its
five attempts before re-queueing anything by hand.

## Expired and soon-to-expire cards

Cards that expire within thirty days of the migration date are deliberately
skipped rather than re-tokenised, because the provider would reject the token
at first use. Skipped cards are listed in the migration report as
"deferred_expiring" and the customer is emailed a card-update link. A skipped
card does not block the migration and does not need a support ticket.

## Troubleshooting

| Error code | Cause | Fix |
| --- | --- | --- |
| ERR-4030 | Card network declined the tokenisation request | Ask the customer to re-enter the card in Billing then Payment methods; the old vault entry cannot be recovered |
| ERR-4031 | SEPA mandate reference is older than the 36-month mandate validity limit | Collect a fresh mandate from the customer; the migration will pick it up on the next hourly sweep |
| ERR-4032 | The stored payment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment method, then re-run the migration for that workspace only from the Migration panel using Retry failed instruments. Do not re-run the full workspace migration |
| ERR-4033 | Duplicate token created because a manual re-queue raced the automatic retry chain | Delete the newer of the two tokens in the provider dashboard, then let the automatic chain finish. Do not delete the older token |
| ERR-4034 | ACH authorisation is missing a micro-deposit verification record | Re-run micro-deposit verification from Billing then Payment methods then Verify |
| ERR-4035 | Provider returned a rate limit during a bulk re-tokenisation sweep | No action needed. The worker backs off and resumes within fifteen minutes |
| ERR-4036 | Billing address country does not match the card issuing country and the provider requires a match | Update the billing address to the issuing country, then retry the instrument |
| ERR-4037 | Payment method belongs to a workspace that was deleted mid-migration | No action needed. The instrument is dropped and the migration continues |
| ERR-4038 | Customer revoked the mandate while re-tokenisation was in flight | Collect a fresh mandate. The migration does not retry revoked mandates automatically |
| ERR-4039 | Legacy vault entry is encrypted with a key that has been rotated out | File a ticket with the vault entry id. Support cannot fix this from the console; a key-recovery job must be run by engineering |
