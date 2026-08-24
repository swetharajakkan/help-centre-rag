# Search-only dump — all 8 questions, both chunking strategies

Identical questions, identical embedding model (BAAI/bge-small-en-v1.5), identical BM25 params, identical fusion weight, k=5. The chunker is the only thing that differs.

## Q1 — What does ERR-4032 mean and what is the fix?
*Known-correct source:* **BM-002 / Troubleshooting (table row ERR-4032)*
*Hit criterion (pre-registered):* one chunk must contain all of `['ERR-4032', 're-add the payment method', 'Retry failed instruments']`

### fixed_window — **MISS**
```
#1  score=0.8412  dense=0.6549  bm25=5.2614   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::002
      ration date are deliberately
      skipped rather than re-tokenised, because the provider would reject the token
      at first use. Skipped cards are listed in the migration report as
      "deferred_expiring" and the customer is emailed a card-update link. A skipped
      card does not block the migration and does not need a support ticket.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4030 | Card network declined the tokenisation request | Ask the customer to re-enter the card in Billing then Payment methods; the old vault entry cannot be recovered |
      | ERR-4031 | SEPA mandate reference is older than the 36-month mandate validity limit | Collect a fresh mandate from the customer; the migration will pick it up on the next hourly sweep |
      | ERR-4032 | The stored payment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment

#2  score=0.7456  dense=0.7115  bm25=2.6363   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::004
      rker backs off and resumes within fifteen minutes |
      | ERR-4036 | Billing address country does not match the card issuing country and the provider requires a match | Update the billing address to the issuing country, then retry the instrument |
      | ERR-4037 | Payment method belongs to a workspace that was deleted mid-migration | No action needed. The instrument is dropped and the migration continues |
      | ERR-4038 | Customer revoked the mandate while re-tokenisation was in flight | Collect a fresh mandate. The migration does not retry revoked mandates automatically |
      | ERR-4039 | Legacy vault entry is encrypted with a key that has been rotated out | File a ticket with the vault entry id. Support cannot fix this from the console; a key-recovery job must be run by engineering |

#3  score=0.6853  dense=0.7097  bm25=2.0488   [developer-api]
  chunk_id: fixed_window::BM-006-api-webhook-migration.md::002
      ed by the migration.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4110 | Webhook endpoint returned a non-2xx during the post-cutover flush | No action needed for the first six hours; the flush retries with backoff. After six hours, replay from Developers then Webhooks then Replay |
      | ERR-4111 | Idempotency key reused within the workspace in the last 24 hours | Generate a fresh UUID per logical operation and retry. Do not derive the key from a request hash |
      | ERR-4112 | Client is still reading next_payment_attempt, which is null on v2 | Update the client to read the retry_schedule array. The field is not restored |
      | ERR-4113 | Webhook queue exceeded the 72-hour retention during an extended outage | The dropped events cannot be replayed. Reconcile by polling GET /v1/invoices for the affected window |
      | ERR-4114 | Request used a /v2 path that does not exist

#4  score=0.5922  dense=0.5606  bm25=5.3237   [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::000
      # Invoice Sync and Reconciliation Troubleshooting
      
      ## What invoice sync does
      
      During the dual-write phase Ledger v1 still owns closed invoices while
      Ledger v2 owns open usage. The invoice sync job runs every hour and copies
      closed v1 invoices into v2 as immutable historical records so that the
      customer sees one continuous invoice list. Sync copies the invoice header,
      the line items and the PDF checksum. It does not copy dunning state, credit
      notes or manual adjustments; those are migrated once, at cutover, by a
      separate backfill.
      
      ## Reading a partial invoice
      
      A partial invoice is an invoice where the header has been copied but at least
      one line item is still missing. Partial invoices are displayed with an amber
      "syncing" badge and are excluded from revenue reports until they complete. A
      partial invoice that has not completed within three hourly sweeps is
      automatically escalated to the

#5  score=0.5752  dense=0.6816  bm25=1.6888   [developer-api]
  chunk_id: fixed_window::BM-006-api-webhook-migration.md::003
      Reconcile by polling GET /v1/invoices for the affected window |
      | ERR-4114 | Request used a /v2 path that does not exist | Use the /v1 path. Ledger v2 is served from /v1 |
      | ERR-4115 | Signature verification failed after the customer rotated their secret mid-cutover | Re-issue the signing secret in Developers then Webhooks and update the endpoint. The migration itself does not rotate secrets |

```

### structure_aware — HIT at rank 1
```
#1  score=0.7861  dense=0.7031  bm25=4.0357   [payments]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::004
      Payment Method Migration Errors > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4032 | The stored payment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment method, then re-run the migration for that workspace only from the Migration panel using Retry failed instruments. Do not re-run the full workspace migration |
      | ERR-4033 | Duplicate token created because a manual re-queue raced the automatic retry chain | Delete the newer of the two tokens in the provider dashboard, then let the automatic chain finish. Do not delete the older token |

#2  score=0.7056  dense=0.7108  bm25=2.7533   [payments]
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::006
      Payment Method Migration Errors > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4037 | Payment method belongs to a workspace that was deleted mid-migration | No action needed. The instrument is dropped and the migration continues |
      | ERR-4038 | Customer revoked the mandate while re-tokenisation was in flight | Collect a fresh mandate. The migration does not retry revoked mandates automatically |
      | ERR-4039 | Legacy vault entry is encrypted with a key that has been rotated out | File a ticket with the vault entry id. Support cannot fix this from the console; a key-recovery job must be run by engineering |

#3  score=0.6787  dense=0.7087  bm25=2.4621   [payments]
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::005
      Payment Method Migration Errors > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4034 | ACH authorisation is missing a micro-deposit verification record | Re-run micro-deposit verification from Billing then Payment methods then Verify |
      | ERR-4035 | Provider returned a rate limit during a bulk re-tokenisation sweep | No action needed. The worker backs off and resumes within fifteen minutes |
      | ERR-4036 | Billing address country does not match the card issuing country and the provider requires a match | Update the billing address to the issuing country, then retry the instrument |

#4  score=0.6525  dense=0.6828  bm25=2.8734   [developer-api]
  chunk_id: structure_aware::BM-006-api-webhook-migration.md::004
      API and Webhook Changes for the Billing Migration > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4113 | Webhook queue exceeded the 72-hour retention during an extended outage | The dropped events cannot be replayed. Reconcile by polling GET /v1/invoices for the affected window |
      | ERR-4114 | Request used a /v2 path that does not exist | Use the /v1 path. Ledger v2 is served from /v1 |
      | ERR-4115 | Signature verification failed after the customer rotated their secret mid-cutover | Re-issue the signing secret in Developers then Webhooks and update the endpoint. The migration itself does not rotate secrets |

#5  score=0.6452  dense=0.6906  bm25=2.552    [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::004
      Tax ID Validation and the Tax Backfill > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4504 | Customer address is in a jurisdiction that v2 does not yet support | File a ticket. The customer is billed without tax until the jurisdiction is enabled |
      | ERR-4505 | Two customers in the workspace share the same tax ID | Merge or correct the duplicate customer records, then re-run the backfill with --force-tax-refresh |
      | ERR-4506 | Reverse-charge flag is set but the customer country is domestic | Clear the reverse-charge flag in Billing then Tax, then retry |

```

## Q2 — Reconciliation found a rounding difference above one cent on an invoice. What should I do?
*Known-correct source:* **BM-003 / Troubleshooting (table row ERR-4217)*
*Hit criterion (pre-registered):* one chunk must contain all of `['ERR-4217', 'reconciliation ticket', 'Do not adjust the invoice by hand']`

### fixed_window — HIT at rank 1
```
#1  score=1.0     dense=0.8282  bm25=25.5546  [invoicing]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::003
      the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the sync |
      | ERR-4216 | Sync ran while the invoice was being edited | No action needed. The next hourly sweep picks it up |
      | ERR-4217 | Reconciliation found a rounding difference above one cent | File a reconciliation ticket. Do not adjust the invoice by hand; hand adjustments break the cutover backfill |

#2  score=0.5185  dense=0.7781  bm25=6.7711   [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::001
      til they complete. A
      partial invoice that has not completed within three hourly sweeps is
      automatically escalated to the reconciliation queue.
      
      ## Credit notes are the common surprise
      
      Because credit notes are not copied hourly, a customer who received a credit
      note during the dual-write window will see a v2 invoice list whose totals are
      higher than the v1 totals until cutover completes. This is not a billing
      error and the difference resolves itself at cutover. Do not issue a second
      credit note to compensate; doing so creates a real double credit that has to
      be clawed back manually.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4210 | Invoice PDF checksum does not match after copy | Re-run the sync for that invoice from Invoicing then Sync then Retry invoice. The PDF is regenerated from the v1 source |
      | ERR-4211 | Line item references a product SKU that no

#3  score=0.459   dense=0.7275  bm25=9.5933   [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::000
      # Invoice Sync and Reconciliation Troubleshooting
      
      ## What invoice sync does
      
      During the dual-write phase Ledger v1 still owns closed invoices while
      Ledger v2 owns open usage. The invoice sync job runs every hour and copies
      closed v1 invoices into v2 as immutable historical records so that the
      customer sees one continuous invoice list. Sync copies the invoice header,
      the line items and the PDF checksum. It does not copy dunning state, credit
      notes or manual adjustments; those are migrated once, at cutover, by a
      separate backfill.
      
      ## Reading a partial invoice
      
      A partial invoice is an invoice where the header has been copied but at least
      one line item is still missing. Partial invoices are displayed with an amber
      "syncing" badge and are excluded from revenue reports until they complete. A
      partial invoice that has not completed within three hourly sweeps is
      automatically escalated to the

#4  score=0.3791  dense=0.7539  bm25=2.4607   [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::002
      then Retry invoice. The PDF is regenerated from the v1 source |
      | ERR-4211 | Line item references a product SKU that no longer exists in v2 | Map the retired SKU to its v2 replacement in Settings then Catalogue then SKU mapping, then retry |
      | ERR-4212 | Invoice is still open in Ledger v1 | No action needed. Only closed invoices are synced; it will copy after it closes |
      | ERR-4213 | Currency on the invoice is not enabled on the v2 workspace | Enable the currency in Settings then Billing then Currencies, then retry the sync |
      | ERR-4214 | Invoice total exceeds the per-invoice ceiling configured for the workspace | Raise the ceiling in Settings then Billing then Limits. If the ceiling is already at the plan maximum, file a ticket |
      | ERR-4215 | Manual adjustment on the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the

#5  score=0.2805  dense=0.6724  bm25=6.8656   [billing]
  chunk_id: fixed_window::BM-001-billing-migration-overview.md::003
      | ERR-4002 | Organisation owner account is unverified | Have the owner complete email verification, then retry from the Migration panel |
      | ERR-4003 | Shadow totals differ by more than 0.5 percent | Do not retry. File a reconciliation ticket with the workspace id; engineering must rebase the shadow ledger |
      | ERR-4004 | Workspace is on a legacy annual contract with custom terms | Contact your account manager to have the contract re-papered onto v2 terms before migrating |
      | ERR-4005 | Migration halted because usage spiked above the guardrail | Wait for the hourly window to close, then clear the halt from Billing then Advanced then Resume |

```

### structure_aware — HIT at rank 1
```
#1  score=1.0     dense=0.8007  bm25=27.0521  [invoicing]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::005
      Invoice Sync and Reconciliation Troubleshooting > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4216 | Sync ran while the invoice was being edited | No action needed. The next hourly sweep picks it up |
      | ERR-4217 | Reconciliation found a rounding difference above one cent | File a reconciliation ticket. Do not adjust the invoice by hand; hand adjustments break the cutover backfill |

#2  score=0.5544  dense=0.7548  bm25=7.6438   [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::002
      Invoice Sync and Reconciliation Troubleshooting > Credit notes are the common surprise
      
      Because credit notes are not copied hourly, a customer who received a credit
      note during the dual-write window will see a v2 invoice list whose totals are
      higher than the v1 totals until cutover completes. This is not a billing
      error and the difference resolves itself at cutover. Do not issue a second
      credit note to compensate; doing so creates a real double credit that has to
      be clawed back manually.

#3  score=0.5279  dense=0.7288  bm25=8.8084   [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::001
      Invoice Sync and Reconciliation Troubleshooting > Reading a partial invoice
      
      A partial invoice is an invoice where the header has been copied but at least
      one line item is still missing. Partial invoices are displayed with an amber
      "syncing" badge and are excluded from revenue reports until they complete. A
      partial invoice that has not completed within three hourly sweeps is
      automatically escalated to the reconciliation queue.

#4  score=0.5242  dense=0.7678  bm25=4.7265   [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::004
      Invoice Sync and Reconciliation Troubleshooting > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4213 | Currency on the invoice is not enabled on the v2 workspace | Enable the currency in Settings then Billing then Currencies, then retry the sync |
      | ERR-4214 | Invoice total exceeds the per-invoice ceiling configured for the workspace | Raise the ceiling in Settings then Billing then Limits. If the ceiling is already at the plan maximum, file a ticket |
      | ERR-4215 | Manual adjustment on the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the sync |

#5  score=0.4609  dense=0.7445  bm25=3.6307   [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::003
      Invoice Sync and Reconciliation Troubleshooting > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4210 | Invoice PDF checksum does not match after copy | Re-run the sync for that invoice from Invoicing then Sync then Retry invoice. The PDF is regenerated from the v1 source |
      | ERR-4211 | Line item references a product SKU that no longer exists in v2 | Map the retired SKU to its v2 replacement in Settings then Catalogue then SKU mapping, then retry |
      | ERR-4212 | Invoice is still open in Ledger v1 | No action needed. Only closed invoices are synced; it will copy after it closes |

```

## Q3 — Our client gets a 409 idempotency_reuse error on the billing API after migrating. What is the documented fix?
*Known-correct source:* **BM-006 / Troubleshooting (table row ERR-4111)*
*Hit criterion (pre-registered):* one chunk must contain all of `['ERR-4111', 'fresh UUID', 'Do not derive the key from a request hash']`

### fixed_window — HIT at rank 3
```
#1  score=1.0     dense=0.8013  bm25=12.4159  [developer-api]
  chunk_id: fixed_window::BM-006-api-webhook-migration.md::001
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
      | ERR-4110 | Webhook endpoint

#2  score=0.7884  dense=0.7918  bm25=7.8285   [developer-api]
  chunk_id: fixed_window::BM-006-api-webhook-migration.md::000
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
      was already used anywhere in the workspace

#3  score=0.6852  dense=0.7392  bm25=8.701    [developer-api]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-006-api-webhook-migration.md::002
      ed by the migration.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4110 | Webhook endpoint returned a non-2xx during the post-cutover flush | No action needed for the first six hours; the flush retries with backoff. After six hours, replay from Developers then Webhooks then Replay |
      | ERR-4111 | Idempotency key reused within the workspace in the last 24 hours | Generate a fresh UUID per logical operation and retry. Do not derive the key from a request hash |
      | ERR-4112 | Client is still reading next_payment_attempt, which is null on v2 | Update the client to read the retry_schedule array. The field is not restored |
      | ERR-4113 | Webhook queue exceeded the 72-hour retention during an extended outage | The dropped events cannot be replayed. Reconcile by polling GET /v1/invoices for the affected window |
      | ERR-4114 | Request used a /v2 path that does not exist

#4  score=0.4656  dense=0.7209  bm25=4.4891   [billing]
  chunk_id: fixed_window::BM-001-billing-migration-overview.md::003
      | ERR-4002 | Organisation owner account is unverified | Have the owner complete email verification, then retry from the Migration panel |
      | ERR-4003 | Shadow totals differ by more than 0.5 percent | Do not retry. File a reconciliation ticket with the workspace id; engineering must rebase the shadow ledger |
      | ERR-4004 | Workspace is on a legacy annual contract with custom terms | Contact your account manager to have the contract re-papered onto v2 terms before migrating |
      | ERR-4005 | Migration halted because usage spiked above the guardrail | Wait for the hourly window to close, then clear the halt from Billing then Advanced then Resume |

#5  score=0.4618  dense=0.7168  bm25=4.6589   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::001
      ge is a real charge from ordinary usage and is unrelated to the
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
      at first use.

```

### structure_aware — HIT at rank 2
```
#1  score=1.0     dense=0.8195  bm25=16.0058  [developer-api]
  chunk_id: structure_aware::BM-006-api-webhook-migration.md::001
      API and Webhook Changes for the Billing Migration > Idempotency keys on the billing API
      
      Ledger v2 enforces idempotency keys far more strictly than v1 did. In v1 an
      idempotency key was scoped to the endpoint, so the same key could be reused
      against POST /v1/invoices and POST /v1/charges without conflict. In v2 the key
      is scoped to the workspace and the whole billing surface. Reusing a key that
      was already used anywhere in the workspace within the last twenty-four hours
      returns 409 with an idempotency_reuse error body, even if the original request
      targeted a different endpoint. Client libraries that derive keys from a
      request hash rather than from a fresh UUID are the usual casualty. Generate a
      fresh UUID per logical operation.

#2  score=0.75    dense=0.7598  bm25=11.7959  [developer-api]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-006-api-webhook-migration.md::003
      API and Webhook Changes for the Billing Migration > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4110 | Webhook endpoint returned a non-2xx during the post-cutover flush | No action needed for the first six hours; the flush retries with backoff. After six hours, replay from Developers then Webhooks then Replay |
      | ERR-4111 | Idempotency key reused within the workspace in the last 24 hours | Generate a fresh UUID per logical operation and retry. Do not derive the key from a request hash |
      | ERR-4112 | Client is still reading next_payment_attempt, which is null on v2 | Update the client to read the retry_schedule array. The field is not restored |

#3  score=0.5918  dense=0.7484  bm25=7.5406   [billing]
  chunk_id: structure_aware::BM-001-billing-migration-overview.md::006
      Billing Migration Overview and Cutover Timeline > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4004 | Workspace is on a legacy annual contract with custom terms | Contact your account manager to have the contract re-papered onto v2 terms before migrating |
      | ERR-4005 | Migration halted because usage spiked above the guardrail | Wait for the hourly window to close, then clear the halt from Billing then Advanced then Resume |

#4  score=0.5314  dense=0.7498  bm25=5.5653   [developer-api]
  chunk_id: structure_aware::BM-006-api-webhook-migration.md::004
      API and Webhook Changes for the Billing Migration > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4113 | Webhook queue exceeded the 72-hour retention during an extended outage | The dropped events cannot be replayed. Reconcile by polling GET /v1/invoices for the affected window |
      | ERR-4114 | Request used a /v2 path that does not exist | Use the /v1 path. Ledger v2 is served from /v1 |
      | ERR-4115 | Signature verification failed after the customer rotated their secret mid-cutover | Re-issue the signing secret in Developers then Webhooks and update the endpoint. The migration itself does not rotate secrets |

#5  score=0.5193  dense=0.7756  bm25=3.636    [billing]
  chunk_id: structure_aware::BM-001-billing-migration-overview.md::005
      Billing Migration Overview and Cutover Timeline > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4001 | Workspace has an open dispute on a legacy invoice | Resolve or withdraw the dispute in Billing then Disputes, then re-queue the migration |
      | ERR-4002 | Organisation owner account is unverified | Have the owner complete email verification, then retry from the Migration panel |
      | ERR-4003 | Shadow totals differ by more than 0.5 percent | Do not retry. File a reconciliation ticket with the workspace id; engineering must rebase the shadow ledger |

```

## Q4 — A customer's tax ID failed revalidation. What is the fix?
*Known-correct source:* **BM-005 / Troubleshooting (table row ERR-4501)*
*Hit criterion (pre-registered):* one chunk must contain all of `['ERR-4501', '--force-tax-refresh']`

### fixed_window — HIT at rank 1
```
#1  score=0.9925  dense=0.7632  bm25=10.7936  [tax-compliance]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::002
      empt customers
      
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
      | ERR-4504 | Customer address is in a jurisdiction that v2

#2  score=0.8923  dense=0.7668  bm25=8.4848   [tax-compliance]
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::000
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
      same result, and exits successfully with

#3  score=0.8609  dense=0.7668  bm25=7.8144   [tax-compliance]
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::001
      ill
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
      certificate expiry date is now

#4  score=0.7451  dense=0.7507  bm25=6.0567   [tax-compliance]
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::003
      Certificates. The customer is taxable until it is uploaded |
      | ERR-4504 | Customer address is in a jurisdiction that v2 does not yet support | File a ticket. The customer is billed without tax until the jurisdiction is enabled |
      | ERR-4505 | Two customers in the workspace share the same tax ID | Merge or correct the duplicate customer records, then re-run the backfill with --force-tax-refresh |
      | ERR-4506 | Reverse-charge flag is set but the customer country is domestic | Clear the reverse-charge flag in Billing then Tax, then retry |

#5  score=0.52    dense=0.714   bm25=2.8843   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::004
      rker backs off and resumes within fifteen minutes |
      | ERR-4036 | Billing address country does not match the card issuing country and the provider requires a match | Update the billing address to the issuing country, then retry the instrument |
      | ERR-4037 | Payment method belongs to a workspace that was deleted mid-migration | No action needed. The instrument is dropped and the migration continues |
      | ERR-4038 | Customer revoked the mandate while re-tokenisation was in flight | Collect a fresh mandate. The migration does not retry revoked mandates automatically |
      | ERR-4039 | Legacy vault entry is encrypted with a key that has been rotated out | File a ticket with the vault entry id. Support cannot fix this from the console; a key-recovery job must be run by engineering |

```

### structure_aware — HIT at rank 1
```
#1  score=1.0     dense=0.8258  bm25=12.9399  [tax-compliance]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::003
      Tax ID Validation and the Tax Backfill > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4501 | Tax ID failed revalidation against the authority | Ask the customer to confirm the ID, correct it if wrong, then re-run the backfill with --force-tax-refresh |
      | ERR-4502 | Tax authority endpoint was unreachable during the sweep | No action needed. The sweep retries the unreachable authority on the next daily run |
      | ERR-4503 | Exemption certificate has expired | Collect a new certificate and upload it in Billing then Tax then Certificates. The customer is taxable until it is uploaded |

#2  score=0.814   dense=0.775   bm25=10.2238  [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::000
      Tax ID Validation and the Tax Backfill > Why tax IDs are revalidated
      
      Ledger v1 validated a customer tax ID once, at the moment it was entered, and
      never rechecked it. Ledger v2 revalidates against the tax authority on a
      rolling ninety-day cycle. The migration therefore runs a one-off revalidation
      of every stored tax ID, and IDs that were accepted years ago under looser
      rules can come back invalid. An invalid tax ID does not block the migration,
      but it does mean the next invoice is issued without the reverse-charge
      treatment the customer expects.

#3  score=0.7744  dense=0.7926  bm25=8.4737   [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::004
      Tax ID Validation and the Tax Backfill > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4504 | Customer address is in a jurisdiction that v2 does not yet support | File a ticket. The customer is billed without tax until the jurisdiction is enabled |
      | ERR-4505 | Two customers in the workspace share the same tax ID | Merge or correct the duplicate customer records, then re-run the backfill with --force-tax-refresh |
      | ERR-4506 | Reverse-charge flag is set but the customer country is domestic | Clear the reverse-charge flag in Billing then Tax, then retry |

#4  score=0.6608  dense=0.7201  bm25=8.5259   [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::001
      Tax ID Validation and the Tax Backfill > The tax cache and why re-running the backfill too early does nothing
      
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

#5  score=0.5083  dense=0.6855  bm25=6.0093   [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::002
      Tax ID Validation and the Tax Backfill > Reverse charge and exempt customers
      
      Customers marked exempt in v1 are carried across as exempt. The exemption
      certificate expiry date is now enforced: an expired certificate makes the
      customer taxable at the next invoice, where v1 would have kept applying the
      exemption indefinitely.

```

## Q5 — How long does a workspace have to stay in the dual-write phase, and can support waive it?
*Known-correct source:* **BM-001 / Cutover phases*
*Hit criterion (pre-registered):* one chunk must contain all of `['minimum of seven days', 'cannot be waived']`

### fixed_window — HIT at rank 1
```
#1  score=1.0     dense=0.7526  bm25=9.6476   [billing]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-001-billing-migration-overview.md::001
      ngines and compares totals. No customer-visible
      change. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage while
      Ledger v1 continues to own historical invoices. Phase 3 (cutover) disables
      Ledger v1 writes entirely. A workspace stays in Phase 2 for a minimum of seven
      days. The seven-day floor is not configurable by support and cannot be waived
      by an account manager; it exists so the shadow comparison has at least one
      full weekly billing boundary to check against.
      
      ## How to tell which engine a workspace is on
      
      Open Settings then Billing then Advanced. The Engine field reads either
      "Ledger v1" or "Ledger v2 (phase N)". The same value is exposed on the API at
      GET /v1/workspaces/{id}/billing with the field billing_engine_version.
      
      ## Migration status codes
      
      The status endpoint returns a coarse status string. These are not error codes;
      they describe where the workspace sits in

#2  score=0.8133  dense=0.7053  bm25=8.7926   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::000
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
      
      The

#3  score=0.7708  dense=0.6959  bm25=8.5244   [subscriptions]
  chunk_id: fixed_window::BM-004-subscription-proration-migration.md::001
      ews, is
      preserved exactly. Anchors that fall on the 29th, 30th or 31st behave
      differently in v2: v1 clamped these to the last day of a short month and then
      restored the original anchor the following month, whereas v2 clamps
      permanently. A subscription anchored to the 31st that renews in February will,
      after migration, stay anchored to the 28th or 29th for every subsequent
      period. Restoring the original anchor requires a support action and cannot be
      done from the customer-facing UI.
      
      ## Trials in flight
      
      A trial that is running when the workspace enters Phase 2 keeps its original
      end timestamp. Trials are not extended, shortened or restarted by the
      migration. If a trial ends during the dual-write window the resulting first
      invoice is issued by Ledger v2.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4301 | Subscription has a proration mode that does not

#4  score=0.7377  dense=0.7076  bm25=7.3471   [billing]
  chunk_id: fixed_window::BM-001-billing-migration-overview.md::000
      # Billing Migration Overview and Cutover Timeline
      
      ## What is changing
      
      Between 2026-07-01 and 2026-09-30 all workspaces move from the legacy billing
      engine (Ledger v1) to the new metered billing engine (Ledger v2). Ledger v2
      computes usage on a rolling hourly window instead of the nightly batch that
      Ledger v1 used. The practical effect for most customers is that invoice line
      items appear within 90 minutes of usage rather than the next morning.
      
      The migration is performed per workspace, not per organisation. A single
      organisation can therefore have some workspaces on Ledger v1 and some on
      Ledger v2 at the same time. This is expected and is the most common source of
      confusing invoice totals during the cutover window.
      
      ## Cutover phases
      
      Phase 1 (shadow) runs both engines and compares totals. No customer-visible
      change. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage

#5  score=0.6859  dense=0.7116  bm25=6.2377   [tax-compliance]
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::001
      ill
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
      certificate expiry date is now

```

### structure_aware — HIT at rank 1
```
#1  score=0.9613  dense=0.7427  bm25=9.2025   [billing]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-001-billing-migration-overview.md::001
      Billing Migration Overview and Cutover Timeline > Cutover phases
      
      Phase 1 (shadow) runs both engines and compares totals. No customer-visible
      change. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage while
      Ledger v1 continues to own historical invoices. Phase 3 (cutover) disables
      Ledger v1 writes entirely. A workspace stays in Phase 2 for a minimum of seven
      days. The seven-day floor is not configurable by support and cannot be waived
      by an account manager; it exists so the shadow comparison has at least one
      full weekly billing boundary to check against.

#2  score=0.8944  dense=0.7037  bm25=9.9091   [payments]
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::000
      Payment Method Migration Errors > Why payment methods have to move separately
      
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

#3  score=0.686   dense=0.71    bm25=5.7949   [subscriptions]
  chunk_id: structure_aware::BM-004-subscription-proration-migration.md::002
      Subscription and Proration Behaviour After Migration > Trials in flight
      
      A trial that is running when the workspace enters Phase 2 keeps its original
      end timestamp. Trials are not extended, shortened or restarted by the
      migration. If a trial ends during the dual-write window the resulting first
      invoice is issued by Ledger v2.

#4  score=0.6806  dense=0.672   bm25=7.5741   [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::001
      Tax ID Validation and the Tax Backfill > The tax cache and why re-running the backfill too early does nothing
      
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

#5  score=0.6174  dense=0.6675  bm25=6.6405   [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::000
      Invoice Sync and Reconciliation Troubleshooting > What invoice sync does
      
      During the dual-write phase Ledger v1 still owns closed invoices while
      Ledger v2 owns open usage. The invoice sync job runs every hour and copies
      closed v1 invoices into v2 as immutable historical records so that the
      customer sees one continuous invoice list. Sync copies the invoice header,
      the line items and the PDF checksum. It does not copy dunning state, credit
      notes or manual adjustments; those are migrated once, at cutover, by a
      separate backfill.

```

## Q6 — What happens to a subscription whose billing anchor is the 31st after it migrates during a short month?
*Known-correct source:* **BM-004 / Billing anchors*
*Hit criterion (pre-registered):* one chunk must contain all of `['v2 clamps permanently', 'cannot be done from the customer-facing UI']`

### fixed_window — HIT at rank 2
```
#1  score=0.989   dense=0.7988  bm25=15.0606  [subscriptions]
  chunk_id: fixed_window::BM-004-subscription-proration-migration.md::002
      eshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4301 | Subscription has a proration mode that does not exist in v2 | Set the subscription to the closest supported mode in Subscriptions then Edit then Proration, then retry |
      | ERR-4302 | Billing anchor is the 31st and the workspace migrated during a short month | No action needed at migration time. To restore the original anchor afterwards, file a ticket; the anchor cannot be reset from the UI |
      | ERR-4303 | Subscription references a plan that was archived in v1 | Un-archive the plan, migrate, then re-archive it |
      | ERR-4304 | Trial end timestamp is in the past but the trial is still marked active | Close the trial manually in Subscriptions then Edit then End trial, then retry the migration |
      | ERR-4305 | Quantity on a metered subscription is negative because of a v1 adjustment | File a ticket with the subscription id.

#2  score=0.9883  dense=0.7944  bm25=15.3807  [subscriptions]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-004-subscription-proration-migration.md::001
      ews, is
      preserved exactly. Anchors that fall on the 29th, 30th or 31st behave
      differently in v2: v1 clamped these to the last day of a short month and then
      restored the original anchor the following month, whereas v2 clamps
      permanently. A subscription anchored to the 31st that renews in February will,
      after migration, stay anchored to the 28th or 29th for every subsequent
      period. Restoring the original anchor requires a support action and cannot be
      done from the customer-facing UI.
      
      ## Trials in flight
      
      A trial that is running when the workspace enters Phase 2 keeps its original
      end timestamp. Trials are not extended, shortened or restarted by the
      migration. If a trial ends during the dual-write window the resulting first
      invoice is issued by Ledger v2.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4301 | Subscription has a proration mode that does not

#3  score=0.9008  dense=0.7864  bm25=13.4492  [subscriptions]
  chunk_id: fixed_window::BM-004-subscription-proration-migration.md::000
      # Subscription and Proration Behaviour After Migration
      
      ## Proration changes at cutover
      
      Ledger v1 prorated subscription changes to the nearest whole day. Ledger v2
      prorates to the second. A customer who upgrades at 14:30 on the fifteenth of
      the month is charged for exactly the remaining seconds of the period rather
      than for the whole of the fifteenth. This means most upgrade invoices get
      slightly smaller after migration and most downgrade credits get slightly
      larger.
      
      Proration mode is set per subscription and is carried across unchanged. If a
      subscription was set to "no proration" in v1 it remains "no proration" in v2.
      The migration never silently changes a proration mode.
      
      ## Billing anchors
      
      The billing anchor, which is the day of the month the subscription renews, is
      preserved exactly. Anchors that fall on the 29th, 30th or 31st behave
      differently in v2: v1 clamped these to the

#4  score=0.3697  dense=0.7105  bm25=3.8168   [billing]
  chunk_id: fixed_window::BM-001-billing-migration-overview.md::000
      # Billing Migration Overview and Cutover Timeline
      
      ## What is changing
      
      Between 2026-07-01 and 2026-09-30 all workspaces move from the legacy billing
      engine (Ledger v1) to the new metered billing engine (Ledger v2). Ledger v2
      computes usage on a rolling hourly window instead of the nightly batch that
      Ledger v1 used. The practical effect for most customers is that invoice line
      items appear within 90 minutes of usage rather than the next morning.
      
      The migration is performed per workspace, not per organisation. A single
      organisation can therefore have some workspaces on Ledger v1 and some on
      Ledger v2 at the same time. This is expected and is the most common source of
      confusing invoice totals during the cutover window.
      
      ## Cutover phases
      
      Phase 1 (shadow) runs both engines and compares totals. No customer-visible
      change. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage

#5  score=0.2763  dense=0.6763  bm25=3.7314   [subscriptions]
  chunk_id: fixed_window::BM-004-subscription-proration-migration.md::003
      05 | Quantity on a metered subscription is negative because of a v1 adjustment | File a ticket with the subscription id. Negative quantities must be corrected in v1 before migration |
      | ERR-4306 | Subscription is scheduled to change plan at the next renewal and the schedule has no v2 equivalent | Cancel the scheduled change, migrate, then re-create the schedule in v2 |

```

### structure_aware — HIT at rank 1
```
#1  score=1.0     dense=0.8759  bm25=21.1078  [subscriptions]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-004-subscription-proration-migration.md::001
      Subscription and Proration Behaviour After Migration > Billing anchors
      
      The billing anchor, which is the day of the month the subscription renews, is
      preserved exactly. Anchors that fall on the 29th, 30th or 31st behave
      differently in v2: v1 clamped these to the last day of a short month and then
      restored the original anchor the following month, whereas v2 clamps
      permanently. A subscription anchored to the 31st that renews in February will,
      after migration, stay anchored to the 28th or 29th for every subsequent
      period. Restoring the original anchor requires a support action and cannot be
      done from the customer-facing UI.

#2  score=0.842   dense=0.7977  bm25=20.3814  [subscriptions]
  chunk_id: structure_aware::BM-004-subscription-proration-migration.md::003
      Subscription and Proration Behaviour After Migration > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4301 | Subscription has a proration mode that does not exist in v2 | Set the subscription to the closest supported mode in Subscriptions then Edit then Proration, then retry |
      | ERR-4302 | Billing anchor is the 31st and the workspace migrated during a short month | No action needed at migration time. To restore the original anchor afterwards, file a ticket; the anchor cannot be reset from the UI |
      | ERR-4303 | Subscription references a plan that was archived in v1 | Un-archive the plan, migrate, then re-archive it |

#3  score=0.493   dense=0.7479  bm25=9.5724   [subscriptions]
  chunk_id: structure_aware::BM-004-subscription-proration-migration.md::000
      Subscription and Proration Behaviour After Migration > Proration changes at cutover
      
      Ledger v1 prorated subscription changes to the nearest whole day. Ledger v2
      prorates to the second. A customer who upgrades at 14:30 on the fifteenth of
      the month is charged for exactly the remaining seconds of the period rather
      than for the whole of the fifteenth. This means most upgrade invoices get
      slightly smaller after migration and most downgrade credits get slightly
      larger.
      
      Proration mode is set per subscription and is carried across unchanged. If a
      subscription was set to "no proration" in v1 it remains "no proration" in v2.
      The migration never silently changes a proration mode.

#4  score=0.3558  dense=0.7223  bm25=5.7762   [subscriptions]
  chunk_id: structure_aware::BM-004-subscription-proration-migration.md::004
      Subscription and Proration Behaviour After Migration > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4304 | Trial end timestamp is in the past but the trial is still marked active | Close the trial manually in Subscriptions then Edit then End trial, then retry the migration |
      | ERR-4305 | Quantity on a metered subscription is negative because of a v1 adjustment | File a ticket with the subscription id. Negative quantities must be corrected in v1 before migration |
      | ERR-4306 | Subscription is scheduled to change plan at the next renewal and the schedule has no v2 equivalent | Cancel the scheduled change, migrate, then re-create the schedule in v2 |

#5  score=0.313   dense=0.7115  bm25=4.7948   [billing]
  chunk_id: structure_aware::BM-001-billing-migration-overview.md::000
      Billing Migration Overview and Cutover Timeline > What is changing
      
      Between 2026-07-01 and 2026-09-30 all workspaces move from the legacy billing
      engine (Ledger v1) to the new metered billing engine (Ledger v2). Ledger v2
      computes usage on a rolling hourly window instead of the nightly batch that
      Ledger v1 used. The practical effect for most customers is that invoice line
      items appear within 90 minutes of usage rather than the next morning.
      
      The migration is performed per workspace, not per organisation. A single
      organisation can therefore have some workspaces on Ledger v1 and some on
      Ledger v2 at the same time. This is expected and is the most common source of
      confusing invoice totals during the cutover window.

```

## Q7 — A customer's card expires next month. Does that block their billing migration?
*Known-correct source:* **BM-002 / Expired and soon-to-expire cards*
*Hit criterion (pre-registered):* one chunk must contain all of `['deferred_expiring', 'does not block the migration']`

### fixed_window — HIT at rank 1
```
#1  score=1.0     dense=0.7545  bm25=9.776    [payments]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::002
      ration date are deliberately
      skipped rather than re-tokenised, because the provider would reject the token
      at first use. Skipped cards are listed in the migration report as
      "deferred_expiring" and the customer is emailed a card-update link. A skipped
      card does not block the migration and does not need a support ticket.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4030 | Card network declined the tokenisation request | Ask the customer to re-enter the card in Billing then Payment methods; the old vault entry cannot be recovered |
      | ERR-4031 | SEPA mandate reference is older than the 36-month mandate validity limit | Collect a fresh mandate from the customer; the migration will pick it up on the next hourly sweep |
      | ERR-4032 | The stored payment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment

#2  score=0.5889  dense=0.7066  bm25=5.4221   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::004
      rker backs off and resumes within fifteen minutes |
      | ERR-4036 | Billing address country does not match the card issuing country and the provider requires a match | Update the billing address to the issuing country, then retry the instrument |
      | ERR-4037 | Payment method belongs to a workspace that was deleted mid-migration | No action needed. The instrument is dropped and the migration continues |
      | ERR-4038 | Customer revoked the mandate while re-tokenisation was in flight | Collect a fresh mandate. The migration does not retry revoked mandates automatically |
      | ERR-4039 | Legacy vault entry is encrypted with a key that has been rotated out | File a ticket with the vault entry id. Support cannot fix this from the console; a key-recovery job must be run by engineering |

#3  score=0.546   dense=0.7004  bm25=5.0476   [subscriptions]
  chunk_id: fixed_window::BM-004-subscription-proration-migration.md::000
      # Subscription and Proration Behaviour After Migration
      
      ## Proration changes at cutover
      
      Ledger v1 prorated subscription changes to the nearest whole day. Ledger v2
      prorates to the second. A customer who upgrades at 14:30 on the fifteenth of
      the month is charged for exactly the remaining seconds of the period rather
      than for the whole of the fifteenth. This means most upgrade invoices get
      slightly smaller after migration and most downgrade credits get slightly
      larger.
      
      Proration mode is set per subscription and is carried across unchanged. If a
      subscription was set to "no proration" in v1 it remains "no proration" in v2.
      The migration never silently changes a proration mode.
      
      ## Billing anchors
      
      The billing anchor, which is the day of the month the subscription renews, is
      preserved exactly. Anchors that fall on the 29th, 30th or 31st behave
      differently in v2: v1 clamped these to the

#4  score=0.4949  dense=0.7043  bm25=3.8939   [tax-compliance]
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::002
      empt customers
      
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
      | ERR-4504 | Customer address is in a jurisdiction that v2

#5  score=0.4706  dense=0.6821  bm25=4.8372   [payments]
  chunk_id: fixed_window::BM-002-payment-method-migration-errors.md::003
      ayment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment method, then re-run the migration for that workspace only from the Migration panel using Retry failed instruments. Do not re-run the full workspace migration |
      | ERR-4033 | Duplicate token created because a manual re-queue raced the automatic retry chain | Delete the newer of the two tokens in the provider dashboard, then let the automatic chain finish. Do not delete the older token |
      | ERR-4034 | ACH authorisation is missing a micro-deposit verification record | Re-run micro-deposit verification from Billing then Payment methods then Verify |
      | ERR-4035 | Provider returned a rate limit during a bulk re-tokenisation sweep | No action needed. The worker backs off and resumes within fifteen minutes |
      | ERR-4036 | Billing address country does not match the card issuing

```

### structure_aware — HIT at rank 1
```
#1  score=1.0     dense=0.8142  bm25=9.7242   [payments]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::002
      Payment Method Migration Errors > Expired and soon-to-expire cards
      
      Cards that expire within thirty days of the migration date are deliberately
      skipped rather than re-tokenised, because the provider would reject the token
      at first use. Skipped cards are listed in the migration report as
      "deferred_expiring" and the customer is emailed a card-update link. A skipped
      card does not block the migration and does not need a support ticket.

#2  score=0.6628  dense=0.713   bm25=7.5245   [payments]
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::003
      Payment Method Migration Errors > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4030 | Card network declined the tokenisation request | Ask the customer to re-enter the card in Billing then Payment methods; the old vault entry cannot be recovered |
      | ERR-4031 | SEPA mandate reference is older than the 36-month mandate validity limit | Collect a fresh mandate from the customer; the migration will pick it up on the next hourly sweep |

#3  score=0.6137  dense=0.689   bm25=7.5477   [developer-api]
  chunk_id: structure_aware::BM-006-api-webhook-migration.md::004
      API and Webhook Changes for the Billing Migration > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4113 | Webhook queue exceeded the 72-hour retention during an extended outage | The dropped events cannot be replayed. Reconcile by polling GET /v1/invoices for the affected window |
      | ERR-4114 | Request used a /v2 path that does not exist | Use the /v1 path. Ledger v2 is served from /v1 |
      | ERR-4115 | Signature verification failed after the customer rotated their secret mid-cutover | Re-issue the signing secret in Developers then Webhooks and update the endpoint. The migration itself does not rotate secrets |

#4  score=0.5937  dense=0.6626  bm25=8.1797   [tax-compliance]
  chunk_id: structure_aware::BM-005-tax-id-validation-migration.md::000
      Tax ID Validation and the Tax Backfill > Why tax IDs are revalidated
      
      Ledger v1 validated a customer tax ID once, at the moment it was entered, and
      never rechecked it. Ledger v2 revalidates against the tax authority on a
      rolling ninety-day cycle. The migration therefore runs a one-off revalidation
      of every stored tax ID, and IDs that were accepted years ago under looser
      rules can come back invalid. An invalid tax ID does not block the migration,
      but it does mean the next invoice is issued without the reverse-charge
      treatment the customer expects.

#5  score=0.5749  dense=0.7136  bm25=5.9444   [subscriptions]
  chunk_id: structure_aware::BM-004-subscription-proration-migration.md::001
      Subscription and Proration Behaviour After Migration > Billing anchors
      
      The billing anchor, which is the day of the month the subscription renews, is
      preserved exactly. Anchors that fall on the 29th, 30th or 31st behave
      differently in v2: v1 clamped these to the last day of a short month and then
      restored the original anchor the following month, whereas v2 clamps
      permanently. A subscription anchored to the 31st that renews in February will,
      after migration, stay anchored to the 28th or 29th for every subsequent
      period. Restoring the original anchor requires a support action and cannot be
      done from the customer-facing UI.

```

## Q8 — A customer got a credit note during dual-write and their v2 totals now look too high. Should we issue another credit note?
*Known-correct source:* **BM-003 / Credit notes are the common surprise*
*Hit criterion (pre-registered):* one chunk must contain all of `['Do not issue a second credit note', 'resolves itself at cutover']`

### fixed_window — HIT at rank 1
```
#1  score=1.0     dense=0.7842  bm25=20.3665  [invoicing]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::001
      til they complete. A
      partial invoice that has not completed within three hourly sweeps is
      automatically escalated to the reconciliation queue.
      
      ## Credit notes are the common surprise
      
      Because credit notes are not copied hourly, a customer who received a credit
      note during the dual-write window will see a v2 invoice list whose totals are
      higher than the v1 totals until cutover completes. This is not a billing
      error and the difference resolves itself at cutover. Do not issue a second
      credit note to compensate; doing so creates a real double credit that has to
      be clawed back manually.
      
      ## Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4210 | Invoice PDF checksum does not match after copy | Re-run the sync for that invoice from Invoicing then Sync then Retry invoice. The PDF is regenerated from the v1 source |
      | ERR-4211 | Line item references a product SKU that no

#2  score=0.5815  dense=0.7276  bm25=9.9628   [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::003
      the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the sync |
      | ERR-4216 | Sync ran while the invoice was being edited | No action needed. The next hourly sweep picks it up |
      | ERR-4217 | Reconciliation found a rounding difference above one cent | File a reconciliation ticket. Do not adjust the invoice by hand; hand adjustments break the cutover backfill |

#3  score=0.4563  dense=0.7034  bm25=7.6096   [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::002
      then Retry invoice. The PDF is regenerated from the v1 source |
      | ERR-4211 | Line item references a product SKU that no longer exists in v2 | Map the retired SKU to its v2 replacement in Settings then Catalogue then SKU mapping, then retry |
      | ERR-4212 | Invoice is still open in Ledger v1 | No action needed. Only closed invoices are synced; it will copy after it closes |
      | ERR-4213 | Currency on the invoice is not enabled on the v2 workspace | Enable the currency in Settings then Billing then Currencies, then retry the sync |
      | ERR-4214 | Invoice total exceeds the per-invoice ceiling configured for the workspace | Raise the ceiling in Settings then Billing then Limits. If the ceiling is already at the plan maximum, file a ticket |
      | ERR-4215 | Manual adjustment on the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the

#4  score=0.3453  dense=0.6676  bm25=7.012    [invoicing]
  chunk_id: fixed_window::BM-003-invoice-sync-troubleshooting.md::000
      # Invoice Sync and Reconciliation Troubleshooting
      
      ## What invoice sync does
      
      During the dual-write phase Ledger v1 still owns closed invoices while
      Ledger v2 owns open usage. The invoice sync job runs every hour and copies
      closed v1 invoices into v2 as immutable historical records so that the
      customer sees one continuous invoice list. Sync copies the invoice header,
      the line items and the PDF checksum. It does not copy dunning state, credit
      notes or manual adjustments; those are migrated once, at cutover, by a
      separate backfill.
      
      ## Reading a partial invoice
      
      A partial invoice is an invoice where the header has been copied but at least
      one line item is still missing. Partial invoices are displayed with an amber
      "syncing" badge and are excluded from revenue reports until they complete. A
      partial invoice that has not completed within three hourly sweeps is
      automatically escalated to the

#5  score=0.3164  dense=0.6987  bm25=2.6488   [tax-compliance]
  chunk_id: fixed_window::BM-005-tax-id-validation-migration.md::001
      ill
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
      certificate expiry date is now

```

### structure_aware — HIT at rank 1
```
#1  score=1.0     dense=0.8547  bm25=27.751   [invoicing]  ✅ CONTAINS ALL GOLD SPANS
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::002
      Invoice Sync and Reconciliation Troubleshooting > Credit notes are the common surprise
      
      Because credit notes are not copied hourly, a customer who received a credit
      note during the dual-write window will see a v2 invoice list whose totals are
      higher than the v1 totals until cutover completes. This is not a billing
      error and the difference resolves itself at cutover. Do not issue a second
      credit note to compensate; doing so creates a real double credit that has to
      be clawed back manually.

#2  score=0.468   dense=0.7049  bm25=10.6895  [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::004
      Invoice Sync and Reconciliation Troubleshooting > Troubleshooting
      
      | Error code | Cause | Fix |
      | --- | --- | --- |
      | ERR-4213 | Currency on the invoice is not enabled on the v2 workspace | Enable the currency in Settings then Billing then Currencies, then retry the sync |
      | ERR-4214 | Invoice total exceeds the per-invoice ceiling configured for the workspace | Raise the ceiling in Settings then Billing then Limits. If the ceiling is already at the plan maximum, file a ticket |
      | ERR-4215 | Manual adjustment on the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the sync |

#3  score=0.3658  dense=0.6485  bm25=9.6427   [invoicing]
  chunk_id: structure_aware::BM-003-invoice-sync-troubleshooting.md::000
      Invoice Sync and Reconciliation Troubleshooting > What invoice sync does
      
      During the dual-write phase Ledger v1 still owns closed invoices while
      Ledger v2 owns open usage. The invoice sync job runs every hour and copies
      closed v1 invoices into v2 as immutable historical records so that the
      customer sees one continuous invoice list. Sync copies the invoice header,
      the line items and the PDF checksum. It does not copy dunning state, credit
      notes or manual adjustments; those are migrated once, at cutover, by a
      separate backfill.

#4  score=0.2857  dense=0.6576  bm25=4.5222   [billing]
  chunk_id: structure_aware::BM-001-billing-migration-overview.md::001
      Billing Migration Overview and Cutover Timeline > Cutover phases
      
      Phase 1 (shadow) runs both engines and compares totals. No customer-visible
      change. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage while
      Ledger v1 continues to own historical invoices. Phase 3 (cutover) disables
      Ledger v1 writes entirely. A workspace stays in Phase 2 for a minimum of seven
      days. The seven-day floor is not configurable by support and cannot be waived
      by an account manager; it exists so the shadow comparison has at least one
      full weekly billing boundary to check against.

#5  score=0.2764  dense=0.6573  bm25=4.0373   [payments]
  chunk_id: structure_aware::BM-002-payment-method-migration-errors.md::000
      Payment Method Migration Errors > Why payment methods have to move separately
      
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

```
