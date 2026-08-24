---
article_id: BM-001
title: Billing Migration Overview and Cutover Timeline
product_area: billing
last_updated: 2026-07-14
---

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
they describe where the workspace sits in the pipeline.

| Status | Meaning | Typical duration |
| --- | --- | --- |
| pending | Queued, not yet started | Up to 72 hours |
| shadow | Phase 1, comparing totals | 3 to 10 days |
| dual_write | Phase 2, v2 authoritative for new usage | Minimum 7 days |
| cutover | Phase 3, v1 writes disabled | Under 1 hour |
| complete | Fully on Ledger v2 | Terminal |
| halted | Stopped by an automated guardrail | Until support acts |

## Troubleshooting

| Error code | Cause | Fix |
| --- | --- | --- |
| ERR-4001 | Workspace has an open dispute on a legacy invoice | Resolve or withdraw the dispute in Billing then Disputes, then re-queue the migration |
| ERR-4002 | Organisation owner account is unverified | Have the owner complete email verification, then retry from the Migration panel |
| ERR-4003 | Shadow totals differ by more than 0.5 percent | Do not retry. File a reconciliation ticket with the workspace id; engineering must rebase the shadow ledger |
| ERR-4004 | Workspace is on a legacy annual contract with custom terms | Contact your account manager to have the contract re-papered onto v2 terms before migrating |
| ERR-4005 | Migration halted because usage spiked above the guardrail | Wait for the hourly window to close, then clear the halt from Billing then Advanced then Resume |
