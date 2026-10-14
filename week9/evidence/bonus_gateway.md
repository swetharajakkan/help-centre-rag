# Bonus: one gateway, audited, with a scoped token

Agent config: `week9/mcp_config.gateway.json` — a single server. The gateway (`week9/gateway.py`) fans out to both upstreams listed in `week9/mcp_config.json`.

Tools the agent discovered through the gateway (4): `support-gateway__help-centre-rag_search_help_centre`, `support-gateway__help-centre-rag_get_article`, `support-gateway__ticket-history_get_ticket`, `support-gateway__ticket-history_get_escalation_history`

**User:** Show me the escalation history for TCK-4403.

## token `agent-full`

attached context: ['tickets://ticket-history/TCK-4403/escalations']

- tools/call `support-gateway__ticket-history_get_ticket({"ticket_id": "TCK-4403"})` → ok: `{"subject":"Proration charged twice after mid-cycle upgrade","customer":{"account":"BLUE-0412","name":"Bluefin Analytics","contact_email":"finance@bluefin.example"},"status":"escalated","priority":"urgent","product_area":"subscriptions","opened_at":"2026-09-27T10:21:00Z","message":"We upgraded seats`
- tools/call `support-gateway__help-centre-rag_search_help_centre({"query": "Proration charged twice after mid-cycle upgrade", "product_area": "subscriptions"})` → ok: `{"query":"Proration charged twice after mid-cycle upgrade","product_area":"subscriptions","hits":[{"rank":1,"chunk_id":"structure_aware::BM-004-subscription-proration-migration.md::000","article_id":"BM-004","title":"Subscription and Proration Behaviour After Migration","score":0.073,"relevance":"st`

**answer:** TCK-4403 (“Proration charged twice after mid-cycle upgrade”) is escalated with urgent priority. [TCK-4403] The customer wrote: “We upgraded seats mid-cycle during the migration window and were charged the proration twice.” [TCK-4403] It has been escalated 2 time(s); most recently on 2026-09-28 from L2-billing to L3-ledger-eng because dual-write produced two proration events; needs ledger engineering. [TCK-4403] Ledger v1 prorated subscription changes to the nearest whole day. [BM-004]

## token `agent-no-escalations`

attached context: none (denied or absent)

- tools/call `support-gateway__ticket-history_get_escalation_history({"ticket_id": "TCK-4403"})` → **isError**: `permission denied: this token lacks scope tickets:escalations, which ticket-history_get_escalation_history needs. Not retryable with this token. Call ticket-history_get_ticket for the ticket's status and escalation count instead, or hand the ticket to a colleague with escalation access.`
- tools/call `support-gateway__ticket-history_get_ticket({"ticket_id": "TCK-4403"})` → ok: `{"subject":"Proration charged twice after mid-cycle upgrade","customer":{"account":"BLUE-0412","name":"Bluefin Analytics","contact_email":"finance@bluefin.example"},"status":"escalated","priority":"urgent","product_area":"subscriptions","opened_at":"2026-09-27T10:21:00Z","message":"We upgraded seats`
- tools/call `support-gateway__help-centre-rag_search_help_centre({"query": "Proration charged twice after mid-cycle upgrade", "product_area": "subscriptions"})` → ok: `{"query":"Proration charged twice after mid-cycle upgrade","product_area":"subscriptions","hits":[{"rank":1,"chunk_id":"structure_aware::BM-004-subscription-proration-migration.md::000","article_id":"BM-004","title":"Subscription and Proration Behaviour After Migration","score":0.073,"relevance":"st`

**answer:** TCK-4403 (“Proration charged twice after mid-cycle upgrade”) is escalated with urgent priority. [TCK-4403] The customer wrote: “We upgraded seats mid-cycle during the migration window and were charged the proration twice.” [TCK-4403] It has been escalated 2 time(s); most recently on 2026-09-28 from L2-billing to L3-ledger-eng because dual-write produced two proration events; needs ledger engineering. [TCK-4403] Ledger v1 prorated subscription changes to the nearest whole day. [BM-004] Note: ticket-history_get_escalation_history({"ticket_id": "TCK-4403"}) failed: permission denied: this token lacks scope tickets:escalations, which ticket-history_get_escalation_history needs. Not retryable with this token. Call ticket-history_get_ticket for the ticket's status and escalation count instead, or hand the ticket to a colleague with escalation access.

## Audit lines written by this run (`week9/evidence/gateway_audit.log`)

```jsonl
{"ts": "2026-10-05T11:57:37+00:00", "caller": "help-centre-agent", "resource": "tickets://ticket-history/TCK-4403/escalations", "ticket_id": "TCK-4403", "outcome": "ok"}
{"ts": "2026-10-05T11:57:37+00:00", "caller": "help-centre-agent", "tool": "ticket-history_get_ticket", "ticket_id": "TCK-4403", "outcome": "ok"}
{"ts": "2026-10-05T11:57:42+00:00", "caller": "help-centre-agent", "tool": "help-centre-rag_search_help_centre", "ticket_id": null, "outcome": "ok"}
{"ts": "2026-10-05T11:57:42+00:00", "caller": "help-centre-agent-restricted", "resource": "tickets://ticket-history/TCK-4403/escalations", "ticket_id": "TCK-4403", "outcome": "denied:tickets:escalations"}
{"ts": "2026-10-05T11:57:42+00:00", "caller": "help-centre-agent-restricted", "tool": "ticket-history_get_escalation_history", "ticket_id": "TCK-4403", "outcome": "denied:tickets:escalations"}
{"ts": "2026-10-05T11:57:42+00:00", "caller": "help-centre-agent-restricted", "tool": "ticket-history_get_ticket", "ticket_id": "TCK-4403", "outcome": "ok"}
{"ts": "2026-10-05T11:57:42+00:00", "caller": "help-centre-agent-restricted", "tool": "help-centre-rag_search_help_centre", "ticket_id": null, "outcome": "ok"}
```
