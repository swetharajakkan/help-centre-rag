# Week 7 — Does this need to be an agent?

A client asked the question that should always come first: does resolving refund-chase tickets need a looping model-driven agent, or would a 3-step hard-coded workflow be faster, cheaper, and more debuggable?

Here are the four numbers over the exact same 10 tickets:

| Metric | Agent | Fixed Workflow | Winner | Note |
|---|:---:|:---:|:---:|---|
| **Pass rate** | **100% (10/10)** | 90% (9/10) | **Agent** | Workflow missed on multi-order duplicate charge (TCK-7009) |
| **P50 latency** | 1.32 s | **0.59 s** | **Workflow** | **2.2× faster** for the fixed workflow |
| **Total tokens** | 28,233 | **3,432** | **Workflow** | **8.2× fewer tokens** (Agent resends full history each lap) |
| **Cost / ticket** | $0.0183 | **$0.0039** | **Workflow** | **4.7× cheaper** for the fixed workflow |

---

## 1. The Decision Rule & Verdict (<150 words)

> **Verdict (121 words):**
> Decision rule: does the execution path vary with the input? Measured on 10 tickets, the agent's path varied on 2 (TCK-7009, TCK-7010). On TCK-7010 the path changed but the output did not. The 4 branch tickets (TCK-7004, TCK-7005, TCK-7006, TCK-7008) did not need it: the enum policy tool turns a missing, refunded, charged-back or over-limit order into a decision, so the fixed path handled them. The class that forces a variable path is the multi-order (duplicate-charge) ticket: the workflow fetched one order and refunded the wrong one (TCK-7009). Workflow: 9/10 pass, p50 0.59s, 3,432 tokens, $0.0039/ticket. Agent: 10/10, p50 1.32s, 28,233 tokens (8.2x), $0.0183/ticket (4.7x). Verdict: the fixed workflow is sufficient for single-order tickets; only multi-order tickets justify the agent's cost.

---

## 2. Third Tool Specification & Description Diff

### The Added Tool: `lookup_refund_policy`
- **Single responsibility:** Maps an order's facts to support policy SP-001 decisions. It does not fetch anything.
- **Typed enum parameters:**
  - `order_status`: `["paid", "refunded", "chargeback", "not_found"]`
  - `customer_tier`: `["standard", "priority"]`
  - `request_type`: `["refund", "duplicate_charge"]`
  - Output `decision`: `["refund_approved", "outside_window", "already_refunded", "needs_manager_approval", "escalate_missing_order", "escalate_chargeback"]`
- **Sharpening `get_order`:** In Week 6, `get_order` claimed it *"checks whether it can be refunded"*. With `lookup_refund_policy` added, this created a direct description overlap. `get_order` was sharpened to state explicitly: *"Fetches one billing order... Does not decide refund eligibility."*

```diff
--- get_order (before)
+++ get_order (after)
@@ -1,7 +1,7 @@
 {
   "name": "get_order",
-  "description": "Look up an order and check whether it can be refunded.",
+  "description": "Fetch one billing order by its id. Returns status, amount, product, charge time and days since purchase, or status not_found. Does not decide refund eligibility.",
   "input_schema": {
     "properties": {
-      "order_id": { "type": "string" }
+      "order_id": { "pattern": "^ORD-\\d{4}$", "type": "string" }
     },
     "required": ["order_id"],
     "type": "object"
   }
 }

+++ lookup_refund_policy (added)
@@ -0,0 +1,24 @@
+{
+  "name": "lookup_refund_policy",
+  "description": "Apply support policy SP-001 to one order's facts and return the refund decision and whether the ticket must be escalated. Does not fetch anything: pass the facts in.",
+  "input_schema": {
+    "type": "object",
+    "properties": {
+      "order_status": { "type": "string", "enum": ["paid", "refunded", "chargeback", "not_found"] },
+      "customer_tier": { "type": "string", "enum": ["standard", "priority"] },
+      "request_type": { "type": "string", "enum": ["refund", "duplicate_charge"] },
+      "days_since_purchase": { "type": ["integer", "null"], "minimum": 0 },
+      "amount_usd": { "type": ["number", "null"], "minimum": 0 }
+    },
+    "required": ["order_status", "customer_tier", "request_type"]
+  }
+}
```

---

## 3. The 4 Safety Budgets Enforced in the Loop

Implemented in `week7/agent.py`:
1. `max_iterations`: Maximum model calls per ticket run (default: 8).
2. `max_tokens`: Total tokens (`input_tokens + output_tokens`) across all laps (default: 20,000).
3. `max_cost_usd`: Cumulative cost limit in dollars (default: $0.25).
4. `max_wall_s`: Total elapsed wall-clock execution time (default: 20.0s).

### Clean Termination Log (`week7/budget_termination.log`)
When a limit is reached, the loop stops cleanly without crashing, hands the ticket to a human with `[ESCALATED]`, and logs the trigger:

```text
# week7 budget termination log
# ticket:          TCK-7009
# budgets:         {"max_iterations": 8, "max_tokens": 2500, "max_cost_usd": 0.25, "max_wall_s": 20.0}
# budget reached:  max_tokens  (configured limit 2500, observed 2745)
# outcome:         terminated cleanly, handed to a human
# model calls:     4   tokens: 2745   cost: $0.01625   wall: 2.05s

{"t": 0.0, "system": "agent", "ticket_id": "TCK-7009", "event": "start", "budgets": {"max_iterations": 8, "max_tokens": 2500, "max_cost_usd": 0.25, "max_wall_s": 20.0}}
{"t": 0.569, "system": "agent", "ticket_id": "TCK-7009", "event": "model_call", "n": 1, "stop_reason": "tool_use", "tokens_total": 511, "cost_usd": 0.003035}
{"t": 0.612, "system": "agent", "ticket_id": "TCK-7009", "event": "tool_call", "tool": "get_ticket", "args": {"ticket_id": "TCK-7009"}}
{"t": 0.823, "system": "agent", "ticket_id": "TCK-7009", "event": "model_call", "n": 2, "stop_reason": "tool_use", "tokens_total": 1146, "cost_usd": 0.00669}
{"t": 0.868, "system": "agent", "ticket_id": "TCK-7009", "event": "tool_call", "tool": "get_order", "args": {"order_id": "ORD-5109"}}
{"t": 1.078, "system": "agent", "ticket_id": "TCK-7009", "event": "model_call", "n": 3, "stop_reason": "tool_use", "tokens_total": 1881, "cost_usd": 0.010845}
{"t": 1.119, "system": "agent", "ticket_id": "TCK-7009", "event": "tool_call", "tool": "get_order", "args": {"order_id": "ORD-5110"}}
{"t": 1.419, "system": "agent", "ticket_id": "TCK-7009", "event": "model_call", "n": 4, "stop_reason": "tool_use", "tokens_total": 2745, "cost_usd": 0.016245}
{"t": 1.419, "system": "agent", "ticket_id": "TCK-7009", "event": "budget_exceeded", "budget": "max_tokens", "limit": 2500, "observed": 2745}
{"t": 1.419, "system": "agent", "ticket_id": "TCK-7009", "event": "terminated_cleanly", "handed_off_to": "human", "llm_calls": 4, "tokens_total": 2745, "cost_usd": 0.016245}
```

---

## 4. Bonus Challenge: 30-Turn Threads & Fact Persistence

Implemented in `week7/bonus.py`:
1. **Fact Persistence:** Persists customer tier to disk (`week7/tier_store.json`), which survives full process restarts.
2. **Context Window Management:** Sliding window (keeps last 6 messages) + rolling summarisation reduces active tokens by ~70% across 30 turns.
3. **Failure Analysis across 3 Long Threads:**
   - `TCK-LONG-01`: Priority tier customer with 30 turns -> **PASS** (Tier preserved across restart).
   - `TCK-LONG-02`: Standard tier customer with 30 turns -> **PASS** (Correctly refuses expired refund).
   - `TCK-LONG-03`: Customer with Director waiver code `MGR-AUTH-8821` on turn 12 -> **FAIL**.
     - **Detail destroyed by summarisation:** Waiver authorization code `MGR-AUTH-8821` was compressed out of context by turn 26.
     - **Outcome:** The agent was unaware of the waiver and defaulted to escalating an order >$100 to manager approval, violating the agreed pre-approval contract.

---

## 5. How to Run

```bash
# Agent on 1 ticket or all 10
.venv/bin/python week7/agent.py
.venv/bin/python week7/agent.py TCK-7004

# Fixed workflow on all 10
.venv/bin/python week7/workflow.py

# Re-run the race (generates race.csv and race.json)
.venv/bin/python week7/race.py

# Run budget termination demo (writes budget_termination.log)
.venv/bin/python week7/budget_demo.py

# Run Bonus Challenge (30 turns, tier persistence, failure study)
.venv/bin/python week7/bonus.py
```
