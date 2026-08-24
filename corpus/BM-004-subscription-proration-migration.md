---
article_id: BM-004
title: Subscription and Proration Behaviour After Migration
product_area: subscriptions
last_updated: 2026-07-28
---

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
| ERR-4301 | Subscription has a proration mode that does not exist in v2 | Set the subscription to the closest supported mode in Subscriptions then Edit then Proration, then retry |
| ERR-4302 | Billing anchor is the 31st and the workspace migrated during a short month | No action needed at migration time. To restore the original anchor afterwards, file a ticket; the anchor cannot be reset from the UI |
| ERR-4303 | Subscription references a plan that was archived in v1 | Un-archive the plan, migrate, then re-archive it |
| ERR-4304 | Trial end timestamp is in the past but the trial is still marked active | Close the trial manually in Subscriptions then Edit then End trial, then retry the migration |
| ERR-4305 | Quantity on a metered subscription is negative because of a v1 adjustment | File a ticket with the subscription id. Negative quantities must be corrected in v1 before migration |
| ERR-4306 | Subscription is scheduled to change plan at the next renewal and the schedule has no v2 equivalent | Cancel the scheduled change, migrate, then re-create the schedule in v2 |
