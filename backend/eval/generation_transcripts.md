## Cited answers (3 answerable)

### Q1 — What does ERR-4032 mean and what is the fix?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-002-payment-method-migration-errors.md::004, structure_aware::BM-002-payment-method-migration-errors.md::006, structure_aware::BM-002-payment-method-migration-errors.md::005`

**Answer (one citation per claim):**

1. | ERR-4032 | The stored payment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment method, then re-run the migration for that workspace only from the Migration panel using Retry failed instruments. Do not re-run the full workspace migration |
   - **cite:** `structure_aware::BM-002-payment-method-migration-errors.md::004` → BM-002 (BM-002-payment-method-migration-errors.md), section “Troubleshooting”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

### Q3 — Our client gets a 409 idempotency_reuse error on the billing API after migrating. What is the documented fix?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-006-api-webhook-migration.md::001, structure_aware::BM-006-api-webhook-migration.md::003, structure_aware::BM-001-billing-migration-overview.md::006`

**Answer (one citation per claim):**

1. Reusing a key that was already used anywhere in the workspace within the last twenty-four hours returns 409 with an idempotency_reuse error body, even if the original request targeted a different endpoint.
   - **cite:** `structure_aware::BM-006-api-webhook-migration.md::001` → BM-006 (BM-006-api-webhook-migration.md), section “Idempotency keys on the billing API”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

2. In v1 an idempotency key was scoped to the endpoint, so the same key could be reused against POST /v1/invoices and POST /v1/charges without conflict.
   - **cite:** `structure_aware::BM-006-api-webhook-migration.md::001` → BM-006 (BM-006-api-webhook-migration.md), section “Idempotency keys on the billing API”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

3. Ledger v2 enforces idempotency keys far more strictly than v1 did.
   - **cite:** `structure_aware::BM-006-api-webhook-migration.md::001` → BM-006 (BM-006-api-webhook-migration.md), section “Idempotency keys on the billing API”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

### Q5 — How long does a workspace have to stay in the dual-write phase, and can support waive it?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-001-billing-migration-overview.md::001, structure_aware::BM-002-payment-method-migration-errors.md::000, structure_aware::BM-004-subscription-proration-migration.md::002`

**Answer (one citation per claim):**

1. A workspace stays in Phase 2 for a minimum of seven days.
   - **cite:** `structure_aware::BM-001-billing-migration-overview.md::001` → BM-001 (BM-001-billing-migration-overview.md), section “Cutover phases”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

2. The seven-day floor is not configurable by support and cannot be waived by an account manager; it exists so the shadow comparison has at least one full weekly billing boundary to check against.
   - **cite:** `structure_aware::BM-001-billing-migration-overview.md::001` → BM-001 (BM-001-billing-migration-overview.md), section “Cutover phases”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

3. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage while Ledger v1 continues to own historical invoices.
   - **cite:** `structure_aware::BM-001-billing-migration-overview.md::001` → BM-001 (BM-001-billing-migration-overview.md), section “Cutover phases”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

## Refusal transcripts (3 out-of-corpus)

### U1 — What is the refund SLA for a disputed invoice during the billing migration?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-001-billing-migration-overview.md::000, structure_aware::BM-001-billing-migration-overview.md::005, structure_aware::BM-003-invoice-sync-troubleshooting.md::000`

**REFUSED.**

```
The indexed articles do not cover this (grounding coverage 0.47 < floor 0.65). No retrieved chunk contains: refund, sla. The retrieved chunks are on the same topic but do not state the thing asked for.
```

### U2 — How do I roll a workspace back from Ledger v2 to Ledger v1 after cutover completes?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-001-billing-migration-overview.md::000, structure_aware::BM-001-billing-migration-overview.md::002, structure_aware::BM-001-billing-migration-overview.md::001`

**REFUSED.**

```
The indexed articles do not cover this (grounding coverage 0.59 < floor 0.65). No retrieved chunk contains: back, complet. The retrieved chunks are on the same topic but do not state the thing asked for.
```

### U3 — What does error ERR-4099 mean and how do I fix it?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-003-invoice-sync-troubleshooting.md::005, structure_aware::BM-001-billing-migration-overview.md::005, structure_aware::BM-002-payment-method-migration-errors.md::004`

**REFUSED.**

```
The indexed articles do not cover this (grounding coverage 0.15 < floor 0.65). No retrieved chunk contains: err-4099, doe. The retrieved chunks are on the same topic but do not state the thing asked for.
```

**Citation audit: 7/7 claims have a chunk_id that resolves AND a quote verbatim in that chunk.**

**Refusal audit: 3/3 out-of-corpus questions refused.**
