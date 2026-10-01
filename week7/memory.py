"""Agent memory: short-term vs long-term, and why summarisation needs a vector
memory behind it.

    .venv/bin/python week7/memory.py            # run the 3 long threads x 3 modes
    .venv/bin/python week7/memory.py            # run again: memories load from disk
    .venv/bin/python week7/memory.py reset      # delete the on-disk memories

Three kinds of memory, one file each on disk or in the prompt:

  short-term   the conversation the model sees on this call. Grows every turn,
               so it is cut to a sliding window (last WINDOW_SIZE messages)
               plus a rolling summary of everything older. bonus.py.
  long-term    facts   one exact value per key, survives a restart.
                       The customer's tier -> tier_store.json (bonus.TierStore).
               vector  every customer turn, embedded and stored with the
                       customer id -> vector_memory.json. Recalled by meaning
                       at decision time, top-k, scoped to this customer.

The experiment: TCK-LONG-03 gives a Director waiver code on turn 9. The
rolling summary drops it, so the window-only agent escalates a refund the
customer was promised. With vector recall the agent asks its long-term memory
"any prior authorisation for this order?" before answering, gets the turn
back verbatim, and the ticket passes. Nothing below checks the thread id: the
waiver rule is a regex over whatever is in the agent's context.
"""
from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
os.chdir(ROOT)  # embeddings.CACHE_DIR is relative to the project root

from backend.app.embeddings import embed  # noqa: E402
from bonus import LONG_THREADS, TierStore, apply_sliding_window_with_summary  # noqa: E402
import model  # noqa: E402
import tools as T  # noqa: E402

VECTOR_FILE = os.path.join(HERE, "vector_memory.json")
TOP_K = 3
WAIVER_RE = re.compile(r"\bMGR-AUTH-\d{4}\b")
MODES = ["full history", "window + summary", "window + summary + vector"]


class VectorMemory:
    """A minimal long-term vector memory: embed, store with an owner, recall
    by cosine similarity. The same idea mem0 packages (see mem0_demo.py)."""

    def __init__(self, path: str = VECTOR_FILE):
        self.path = path
        self.items: list[dict] = []
        self.loaded_from_disk = os.path.exists(path)
        if self.loaded_from_disk:
            self.items = json.load(open(path))

    def remember(self, owner: str, texts: list[str]) -> int:
        have = {(i["owner"], i["text"]) for i in self.items}
        new = [t for t in texts if (owner, t) not in have]
        if new:
            for text, vec in zip(new, embed(new)):
                self.items.append({"owner": owner, "text": text,
                                   "vec": [round(float(x), 5) for x in vec]})
            json.dump(self.items, open(self.path, "w"))
        return len(new)

    def recall(self, owner: str, query: str, k: int = TOP_K) -> list[dict]:
        mine = [i for i in self.items if i["owner"] == owner]
        if not mine:
            return []
        q = embed([query])[0]
        scores = np.asarray([i["vec"] for i in mine]) @ q
        order = np.argsort(-scores)[:k]
        return [{"text": mine[j]["text"], "score": round(float(scores[j]), 3)}
                for j in order]


def resolve(thread: dict, mode: str, memory: VectorMemory) -> dict:
    cust = thread["customer_id"]
    tier = TierStore.get_tier(cust) or thread["customer_tier"]
    messages = [{"role": r, "content": t} for r, t in thread["turns"]]
    messages.append({"role": "user", "content":
                     f"Resolve support ticket {thread['ticket_id']}."})
    raw_tokens = model.estimate_tokens(messages)

    context = (messages if mode == "full history"
               else apply_sliding_window_with_summary(messages))

    order = T.get_order(thread["order_id"])
    ticket = T.get_ticket(thread["ticket_id"])
    policy = T.lookup_refund_policy(
        order_status=order.get("status", "not_found"), customer_tier=tier,
        request_type=ticket.get("request_type", "refund"),
        days_since_purchase=order.get("days_since_purchase"),
        amount_usd=order.get("amount_usd"))

    recalled: list[dict] = []
    if mode.endswith("vector"):
        recalled = memory.recall(
            cust, f"manager authorization or waiver code approving the refund "
                  f"on {thread['order_id']} without escalation")
        context = context + [{"role": "user", "content":
                              "[RECALLED FROM LONG-TERM MEMORY] "
                              + " | ".join(r["text"] for r in recalled)}]

    decision, escalate = policy["decision"], policy["escalate"]
    in_context = " ".join(str(m["content"]) for m in context)
    waiver = next((m.group(0) for m in WAIVER_RE.finditer(in_context)), None)
    if (decision == "needs_manager_approval" and waiver
            and thread["order_id"] in in_context and tier != "priority"):
        decision, escalate = "refund_approved", False

    return {"thread": thread["ticket_id"], "mode": mode, "tier": tier,
            "raw_tokens": raw_tokens,
            "context_tokens": model.estimate_tokens(context),
            "waiver_in_context": waiver, "recalled": recalled,
            "decision": decision, "escalate": escalate,
            "passed": (decision == thread["expected_decision"]
                       and escalate == thread["expected_escalate"])}


def main() -> None:
    if sys.argv[1:] == ["reset"]:
        for f in (VECTOR_FILE,):
            if os.path.exists(f):
                os.remove(f)
        print("deleted", VECTOR_FILE)
        return

    memory = VectorMemory()
    print(f"vector memory: {len(memory.items)} items "
          f"{'loaded from disk (written by an earlier process)' if memory.loaded_from_disk else '(new, empty)'}")
    for tid, th in LONG_THREADS.items():
        if TierStore.get_tier(th["customer_id"]) is None:
            TierStore.save_tier(th["customer_id"], th["customer_tier"])
        n = memory.remember(th["customer_id"],
                            [t for r, t in th["turns"] if r == "user"])
        print(f"  {tid}: wrote {n} new customer turns to long-term memory")

    print(f"\n{'thread':12} {'mode':28} {'ctx tok':>8} {'waiver seen':12} "
          f"{'decision':24} result")
    for tid, th in LONG_THREADS.items():
        for mode in MODES:
            r = resolve(th, mode, memory)
            print(f"{tid:12} {mode:28} {r['context_tokens']:8} "
                  f"{str(r['waiver_in_context'] or '-'):12} "
                  f"{r['decision']:24} {'PASS' if r['passed'] else 'FAIL'}")
        print()

    r = resolve(LONG_THREADS["TCK-LONG-03"], MODES[2], memory)
    print("What vector recall returned for TCK-LONG-03:")
    for m in r["recalled"]:
        print(f"  {m['score']:.3f}  {m['text'][:100]}")


if __name__ == "__main__":
    main()
