---
article_id: BM-003
title: Invoice Sync and Reconciliation Troubleshooting
product_area: invoicing
last_updated: 2026-08-05
---

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
| ERR-4211 | Line item references a product SKU that no longer exists in v2 | Map the retired SKU to its v2 replacement in Settings then Catalogue then SKU mapping, then retry |
| ERR-4212 | Invoice is still open in Ledger v1 | No action needed. Only closed invoices are synced; it will copy after it closes |
| ERR-4213 | Currency on the invoice is not enabled on the v2 workspace | Enable the currency in Settings then Billing then Currencies, then retry the sync |
| ERR-4214 | Invoice total exceeds the per-invoice ceiling configured for the workspace | Raise the ceiling in Settings then Billing then Limits. If the ceiling is already at the plan maximum, file a ticket |
| ERR-4215 | Manual adjustment on the invoice has no v2 equivalent adjustment type | Convert the adjustment to a credit note in Ledger v1, then retry the sync |
| ERR-4216 | Sync ran while the invoice was being edited | No action needed. The next hourly sweep picks it up |
| ERR-4217 | Reconciliation found a rounding difference above one cent | File a reconciliation ticket. Do not adjust the invoice by hand; hand adjustments break the cutover backfill |
