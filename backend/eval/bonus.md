**Question (Q4):** A customer's tax ID failed revalidation. What is the fix?
**Known-correct source:** BM-005 / Troubleshooting (table row ERR-4501)
**The complete answer also requires** the prose caveat in BM-005 “The tax cache and why re-running the backfill too early does nothing”.

#### fixed_window

- top-1: `fixed_window::BM-005-tax-id-validation-migration.md::002` (score 0.9925, 897 chars)
- gold row ERR-4501 in top-1: **YES**
- 24-hour-cache caveat anywhere in the k=3 context: **YES**
- rank at which the caveat first appears: **2**
- caveat present in the generated answer: **NO**

Answer produced:

1. | ERR-4501 | Tax ID failed revalidation against the authority | Ask the customer to confirm the ID, correct it if wrong, then re-run the backfill with --force-tax-refresh |  
   `fixed_window::BM-005-tax-id-validation-migration.md::002`
2. | ERR-4503 | Exemption certificate has expired | Collect a new certificate and upload it in Billing then Tax then Certificates. The customer is taxable until it is uploaded |  
   `fixed_window::BM-005-tax-id-validation-migration.md::002`
3. | ERR-4502 | Tax authority endpoint was unreachable during the sweep | No action needed. The sweep retries the unreachable authority on the next daily run |  
   `fixed_window::BM-005-tax-id-validation-migration.md::002`

#### structure_aware

- top-1: `structure_aware::BM-005-tax-id-validation-migration.md::003` (score 1.0, 611 chars)
- gold row ERR-4501 in top-1: **YES**
- 24-hour-cache caveat anywhere in the k=3 context: **NO**
- rank at which the caveat first appears: **4**
- caveat present in the generated answer: **NO**

Answer produced:

1. | ERR-4501 | Tax ID failed revalidation against the authority | Ask the customer to confirm the ID, correct it if wrong, then re-run the backfill with --force-tax-refresh |  
   `structure_aware::BM-005-tax-id-validation-migration.md::003`
2. | ERR-4503 | Exemption certificate has expired | Collect a new certificate and upload it in Billing then Tax then Certificates. The customer is taxable until it is uploaded |  
   `structure_aware::BM-005-tax-id-validation-migration.md::003`
3. | ERR-4502 | Tax authority endpoint was unreachable during the sweep | No action needed. The sweep retries the unreachable authority on the next daily run |  
   `structure_aware::BM-005-tax-id-validation-migration.md::003`
