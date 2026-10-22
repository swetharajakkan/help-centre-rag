# Injected failure: policy-lookup worker returns 500 on C-01

Question: We have ERR-4502 on one account and ERR-4301 on another. Are these the same root cause?

Worker error: `HTTP 500: policy-lookup worker: internal server error`

Retried: no · degraded to partial: yes · synthesised as if answered: no

**What the orchestrator actually did: DEGRADED — no retry; it swallowed the 500, shipped a no-answer reply tagged [ESCALATED], and the customer-facing text never says a step failed.**

Judge on the failed run: FAIL (NOT_RESOLVED; assertions failed: none)

The refund sentence is in both replies: it comes from the shared reply template on the ticket's refund fields, not from the policy worker, so it is not evidence of synthesising past the failure.

## Reply shipped with the worker down

```
Hi, thanks for raising ticket TCK-4001.

I looked through our help-centre articles and could not find documentation covering your question.

Details: The policy-lookup step did not return an answer.

We have approved a refund of USD 41.50 for this charge.

[ESCALATED]

Best regards,
Billing Support
```

## Same case, worker healthy

```
Hi, thanks for raising ticket TCK-4001.

ERR-4301 means Subscription has a proration mode that does not exist in v2. Set the subscription to the closest supported mode in Subscriptions then Edit then Proration, then retry.

ERR-4502 means Tax authority endpoint was unreachable during the sweep. No action needed. The sweep retries the unreachable authority on the next daily run.

We have approved a refund of USD 41.50 for this charge.

[ESCALATED]

Best regards,
Billing Support
```
