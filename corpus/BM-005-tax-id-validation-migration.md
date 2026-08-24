---
article_id: BM-005
title: Tax ID Validation and the Tax Backfill
product_area: tax-compliance
last_updated: 2026-08-11
---

# Tax ID Validation and the Tax Backfill

## Why tax IDs are revalidated

Ledger v1 validated a customer tax ID once, at the moment it was entered, and
never rechecked it. Ledger v2 revalidates against the tax authority on a
rolling ninety-day cycle. The migration therefore runs a one-off revalidation
of every stored tax ID, and IDs that were accepted years ago under looser
rules can come back invalid. An invalid tax ID does not block the migration,
but it does mean the next invoice is issued without the reverse-charge
treatment the customer expects.

## The tax cache and why re-running the backfill too early does nothing

Validation results are written to a tax cache with a hard twenty-four hour
time to live. The backfill reads from that cache. If you re-run the backfill
before the entry has expired, the job reads the cached failure, reports the
same result, and exits successfully with no change. It does not log a warning
and it does not tell you it read from cache, so it looks exactly like a
genuine second failure. Always check the cache_written_at timestamp on the
tax record before re-running, and wait until twenty-four hours have elapsed
since that timestamp. Support engineers lose a great deal of time to this
because a no-op run and a real failed run are indistinguishable in the UI.

There is no supported way to flush the tax cache early. Requests to purge it
are declined because a purge would re-hit the tax authority for every stored
ID in the workspace and trip the authority's own rate limits.

## Reverse charge and exempt customers

Customers marked exempt in v1 are carried across as exempt. The exemption
certificate expiry date is now enforced: an expired certificate makes the
customer taxable at the next invoice, where v1 would have kept applying the
exemption indefinitely.

## Troubleshooting

| Error code | Cause | Fix |
| --- | --- | --- |
| ERR-4501 | Tax ID failed revalidation against the authority | Ask the customer to confirm the ID, correct it if wrong, then re-run the backfill with --force-tax-refresh |
| ERR-4502 | Tax authority endpoint was unreachable during the sweep | No action needed. The sweep retries the unreachable authority on the next daily run |
| ERR-4503 | Exemption certificate has expired | Collect a new certificate and upload it in Billing then Tax then Certificates. The customer is taxable until it is uploaded |
| ERR-4504 | Customer address is in a jurisdiction that v2 does not yet support | File a ticket. The customer is billed without tax until the jurisdiction is enabled |
| ERR-4505 | Two customers in the workspace share the same tax ID | Merge or correct the duplicate customer records, then re-run the backfill with --force-tax-refresh |
| ERR-4506 | Reverse-charge flag is set but the customer country is domestic | Clear the reverse-charge flag in Billing then Tax, then retry |
