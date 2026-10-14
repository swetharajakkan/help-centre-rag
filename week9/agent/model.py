"""Where the AI runs: here, in the host. Never in an MCP server.

Two engines behind one call, `complete(system, messages, tools)`, both taking
and returning Messages-API-shaped blocks (text / tool_use / tool_result):

  ClaudeModel   claude-opus-5-5 through the Anthropic SDK. Used whenever
                ANTHROPIC_API_KEY (or another SDK credential) is configured.
  OfflineModel  a deterministic planner for this checkout, which has no key.
                Same contract as weeks 6-8: it sees ONLY the conversation it
                is handed -- the user text, attached context, the tool list
                from tools/list and the tool results. It cannot import a
                server, read tickets.json or peek at the corpus.

How the offline planner picks a tool, all from discovered metadata:

  * identifiers in the user's text (e.g. TCK-4403, BM-4) are routed to a
    tool with a single required *_id argument, scored by the argument's
    JSON-schema `pattern`, by the id prefix appearing in the tool's
    description (a docstring that says "ids look like TCK-nnnn" helps), and
    by words of the tool's name appearing in the user's text;
  * with no identifier, every tool with a `query` argument gets the question
    (help centre, uploaded documents, ...), and the best-scored hits win;
  * after a record with a `subject` comes back, it searches with that subject
    to ground the answer.

How it handles an error -- the behaviour requirement 5 measures:

  * the error names an id shape ("ids look like BM-nnn"): reshape the id and
    call again;
  * the error names another tool ("call search_help_centre"): call that;
  * the error says retrying will not help: stop and report it;
  * anything else ("Error 3"): resend the identical call, up to 3 attempts,
    then give up -- which is what a model does with an opaque error.

Its final turn is the responder's JSON contract: {"answer", "kind",
"claims": [{"text", "source_id", "quote", "facts"}]}.
"""
from __future__ import annotations

import json
import math
import os
import re

MODEL_ID = os.environ.get("HELP_CENTRE_MODEL", "claude-opus-5-5")
PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK = 4.00, 20.00     # claude-opus-5-5 list

# Upper-case prefix, so "Phase 2" is not an id but "BM-4" and "TCK 4403" are.
IDENT = re.compile(r"\b([A-Z]{2,5})(?:-| )?(\d{1,6})\b")
CONTEXT_RE = re.compile(r'<context uri="([^"]+)" server="([^"]+)">\n(.*?)\n</context>', re.S)
SHAPE_HINT = re.compile(r"look like ([A-Z]+)-(n+)")
CALL_HINT = re.compile(r"\b[Cc]all ([a-z][a-z0-9_-]+)")
NO_RETRY = re.compile(r"do not retry|retrying will not help|instead of retrying|"
                      r"not retryable|permission denied", re.I)
MAX_SAME_ATTEMPTS = 3
# Cross-encoder points below the best hit beyond which a hit is dropped.
MARGIN = 1.5


def estimate_tokens(obj) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, default=str)
    return max(1, math.ceil(len(text) / 4))


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in * PRICE_IN_PER_MTOK + tokens_out * PRICE_OUT_PER_MTOK) / 1e6


# --------------------------------------------------------------- routing

def id_param(tool: dict) -> str | None:
    """The single required *_id string argument of a lookup tool, if any."""
    schema = tool.get("input_schema") or {}
    req = schema.get("required") or []
    props = schema.get("properties") or {}
    if len(req) == 1 and req[0].endswith("_id") and props.get(req[0], {}).get("type") == "string":
        return req[0]
    return None


def query_param(tool: dict) -> str | None:
    props = (tool.get("input_schema") or {}).get("properties") or {}
    return "query" if "query" in props else None


def short(name: str) -> str:
    return name.split("__", 1)[-1]


def identifiers(text: str) -> list[str]:
    """Things that look like record ids, as the user wrote them (BM-4, TCK-4403)."""
    out = []
    for m in IDENT.finditer(text):
        prefix = m.group(1).upper()
        if prefix in {"ID", "NO", "IS"}:
            continue
        out.append(f"{prefix}-{m.group(2)}")
    return list(dict.fromkeys(out))


STOPWORDS = set("a an and are as at be by can do does for from how i if in is it my of on "
                "or our the this to was what when where which who why will with you your".split())


def _stems(text: str) -> set[str]:
    """Crude stems (first five letters), so "paused" meets "pause"."""
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in STOPWORDS and len(w) > 1}


def route_id(ident: str, tools: list[dict], user_text: str = "") -> list[tuple[int, dict]]:
    """Lookup tools that could take this id, best first, with their scores."""
    prefix = ident.split("-")[0] + "-"
    words = set(re.findall(r"[a-z]+", user_text.lower()))
    scored = []
    for t in tools:
        p = id_param(t)
        if not p:
            continue
        prop = t["input_schema"]["properties"][p]
        score = 0
        if prop.get("pattern") and re.search(prop["pattern"], ident):
            score += 3
        if prefix in (t.get("description") or "") or prefix in (prop.get("description") or ""):
            score += 2
        name_words = set(short(t["name"]).split("_")) - {"get", "by", "id"}
        score += len(name_words & words) + len({w.rstrip("s") for w in name_words}
                                                & {w.rstrip("s") for w in words})
        if score:
            # fewer name words = the plain record fetch, preferred on a tie
            scored.append((score * 10 - len(name_words), t))
    scored.sort(key=lambda st: -st[0])
    return scored


# --------------------------------------------------------------- Claude

class ClaudeModel:
    name = MODEL_ID

    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic()

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        resp = self.client.beta.messages.create(
            model=MODEL_ID, max_tokens=16000, system=system, messages=messages,
            tools=tools, output_config={"effort": "medium"},
            # On a policy decline the API re-runs the request on a fallback
            # model inside the same call instead of stopping.
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        content = [b.model_dump(mode="json", exclude_none=True) for b in resp.content]
        return {"content": content, "stop_reason": resp.stop_reason, "model": resp.model,
                "usage": {"input_tokens": resp.usage.input_tokens,
                          "output_tokens": resp.usage.output_tokens}}


# --------------------------------------------------------------- offline

class OfflineModel:
    name = "offline-mcp-planner"

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        content = self._step(messages, tools)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return {"content": content, "stop_reason": stop, "model": self.name,
                "usage": {"input_tokens": estimate_tokens({"s": system, "t": tools, "m": messages}),
                          "output_tokens": estimate_tokens(content)}}

    # -- reading the conversation

    @staticmethod
    def _read(messages):
        first = messages[0]["content"]
        blocks = first if isinstance(first, list) else [{"type": "text", "text": first}]
        raw = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        context = [{"uri": u, "server": s, "text": t} for u, s, t in CONTEXT_RE.findall(raw)]
        user_text = CONTEXT_RE.sub("", raw).strip()
        calls, pairs = {}, []
        for msg in messages[1:]:
            if not isinstance(msg["content"], list):
                continue
            for b in msg["content"]:
                if b.get("type") == "tool_use":
                    calls[b["id"]] = b
                elif b.get("type") == "tool_result":
                    text = b["content"] if isinstance(b["content"], str) else \
                        "\n".join(x.get("text", "") for x in b["content"])
                    pairs.append((calls[b["tool_use_id"]], bool(b.get("is_error")), text))
        return user_text, context, pairs

    @staticmethod
    def _use(n: int, name: str, args: dict) -> list[dict]:
        return [{"type": "tool_use", "id": f"toolu_{n:02d}", "name": name, "input": args}]

    # -- one step

    def _step(self, messages, tools):
        user_text, context, pairs = self._read(messages)
        by_name = {t["name"]: t for t in tools}
        n = len(pairs) + 1
        done = {(c["name"], json.dumps(c["input"], sort_keys=True)) for c, err, _ in pairs if not err}
        tried = [(c["name"], json.dumps(c["input"], sort_keys=True)) for c, _, _ in pairs]
        notes = []

        # 1. React to the last error, if the last call failed.
        if pairs and pairs[-1][1]:
            call, _, err = pairs[-1]
            nxt = self._recover(call, err, by_name, user_text, tried)
            if nxt:
                return self._use(n, *nxt)
            key = (call["name"], json.dumps(call["input"], sort_keys=True))
            streak = 0
            for c, e, _ in reversed(pairs):
                if e and (c["name"], json.dumps(c["input"], sort_keys=True)) == key:
                    streak += 1
                else:
                    break
            if not NO_RETRY.search(err) and streak < MAX_SAME_ATTEMPTS:
                return self._use(n, call["name"], call["input"])   # opaque: resend
        for c, e, txt in pairs:
            if e and not any(c2["name"] == c["name"] and not e2 for c2, e2, _ in pairs):
                notes.append(f"{short(c['name'])}({json.dumps(c['input'])}) failed: {txt}")

        # 2. Plan the next call from what is known so far.
        results = [json.loads(t) for c, e, t in pairs if not e and t.strip().startswith("{")]
        for name, args in self._plan(user_text, context, results, tools):
            key = (name, json.dumps(args, sort_keys=True))
            if key not in done and key not in tried:
                return self._use(n, name, args)

        # 3. Nothing left to call: answer.
        return [{"type": "text", "text": json.dumps(self._answer(user_text, context, results, notes))}]

    def _recover(self, call, err, by_name, user_text, tried):
        args = dict(call["input"])
        m = SHAPE_HINT.search(err)
        p = id_param(by_name.get(call["name"], {}))
        if m and p and isinstance(args.get(p), str):
            digits = re.sub(r"\D", "", args[p])
            if digits and len(digits) <= len(m.group(2)):
                fixed = f"{m.group(1)}-{digits.zfill(len(m.group(2)))}"
                key = (call["name"], json.dumps({**args, p: fixed}, sort_keys=True))
                if fixed != args[p] and key not in tried:
                    return call["name"], {**args, p: fixed}
        for hinted in CALL_HINT.findall(err):
            target = next((t for t in by_name if short(t) == hinted), None)
            if not target or target == call["name"]:
                continue
            tp = id_param(by_name[target])
            if query_param(by_name[target]):
                nxt = {"query": user_text}
            elif tp and p and isinstance(args.get(p), str):
                nxt = {tp: args[p]}          # same record, through the named tool
            else:
                continue
            if (target, json.dumps(nxt, sort_keys=True)) not in tried:
                return target, nxt
        return None

    def _plan(self, user_text, context, results, tools):
        # What the host already attached, by the last segment of each URI
        # (tickets://.../TCK-4403/escalations -> "escalations").
        attached = {c["uri"].rstrip("/").rsplit("/", 1)[-1].lower() for c in context}
        words = set(re.findall(r"[a-z]+", user_text.lower()))
        plan, ids = [], identifiers(user_text)
        for ident in ids:
            ranked = [t for _, t in route_id(ident, tools, user_text)]
            if not ranked:
                continue

            def distinct(t):
                own = set(short(t["name"]).split("_")) - {"get"}
                others = set().union(*(set(short(o["name"]).split("_")) for o in ranked if o is not t))
                return own - others

            def in_context(t):
                return any(a.startswith(w[:8]) for w in distinct(t) for a in attached)

            # Never spend a turn fetching what is already in the prompt.
            fresh = [t for t in ranked if not in_context(t)] or ranked[:1]
            best = fresh[0]
            plan.append((best["name"], {id_param(best): ident}))
            # A second lookup only when the user asked for what it returns.
            for t in fresh[1:]:
                if any(w in words or w[:8] in " ".join(words) for w in distinct(t)):
                    plan.append((t["name"], {id_param(t): ident}))
        searches = [t for t in tools if query_param(t)]
        search = searches[0] if searches else None
        if search:
            props = search["input_schema"].get("properties", {})
            records = [r for r in results if isinstance(r.get("subject"), str)]
            if records:
                r = records[0]
                args = {"query": r["subject"]}
                if "product_area" in props and r.get("product_area"):
                    args["product_area"] = r["product_area"]
                plan.append((search["name"], args))
            elif not ids or not plan:
                # Every discovered search tool gets the question: each server
                # holds different sources, and the answer keeps the best hits.
                plan.extend((t["name"], {"query": user_text}) for t in searches)
        return plan

    # -- the responder's final JSON

    @staticmethod
    def _sentence(text: str, query: str = "", best_match: bool = False) -> tuple[str, str]:
        """(claim text, verbatim quote) from a chunk. Prose: its first
        sentence -- or, with best_match (uploaded documents, whose paragraphs
        have no lead sentence written to summarise them), the sentence sharing
        most word stems with the query, the first one on a tie. A
        troubleshooting table: the row sharing most words with the
        query. The chunker's "Title > Section" breadcrumb line is skipped --
        it is not in the article, so quoting it would fail verification."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines and " > " in lines[0]:
            lines = lines[1:]
        prose = " ".join(l for l in lines if not l.startswith(("|", "#", "-", ">", "```")))
        sents = [m.group(1).strip() for m in re.finditer(r"(.{40,320}?[.!?])(?=\s|$)", prose)]
        if sents:
            q = _stems(query) if best_match else set()
            s = max(sents, key=lambda x: (len(q & _stems(x)), -sents.index(x)))
            return s, s
        if prose:
            s = prose[:240].strip()
            return s, s
        rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines
                if l.startswith("|") and not set(l) <= set("|- :")]
        if len(rows) < 2:
            # A bulleted list with no prose: its first substantial item.
            items = [l.lstrip("-* ").strip() for l in lines if l.startswith(("-", "*"))]
            item = next((i for i in items if len(i) >= 25), "")
            return item, item
        head, body = rows[0], rows[1:]
        words = set(re.findall(r"[a-z0-9]+", query.lower()))
        row = max(body, key=lambda r: len(words & set(re.findall(r"[a-z0-9]+", " ".join(r).lower()))))
        text = "; ".join(f"{h}: {v}" for h, v in zip(head, row))
        return text, max(row, key=len)

    def _answer(self, user_text, context, results, notes):
        claims = []
        escal = {}
        for c in context:
            try:
                d = json.loads(c["text"])
                if "escalations" in d:
                    escal[d["ticket_id"]] = d["escalations"]
            except (ValueError, KeyError, TypeError):
                pass
        for r in results:
            if "escalations" in r and "ticket_id" in r:
                escal.setdefault(r["ticket_id"], r["escalations"])
        for r in results:
            if isinstance(r.get("subject"), str) and r.get("ticket_id"):
                tid = r["ticket_id"]
                claims.append({"text": f"{tid} (“{r['subject']}”) is {r['status']} with "
                                       f"{r['priority']} priority.",
                               "source_id": tid, "quote": r["subject"],
                               "facts": {"status": r["status"], "priority": r["priority"]}})
                claims.append({"text": f"The customer wrote: “{r['message']}”",
                               "source_id": tid, "quote": r["message"]})
                hist = escal.get(tid)
                count = len(hist) if hist is not None else r.get("escalation_count", 0)
                last = (hist[-1] if hist else None) or r.get("latest_escalation")
                if count and last:
                    claims.append({"text": f"It has been escalated {count} time(s); most recently "
                                           f"on {last['at'][:10]} from {last['from_tier']} to "
                                           f"{last['to_tier']} because {last['reason']}.",
                                   "source_id": tid, "quote": last["reason"],
                                   "facts": {"escalation_count": count}})
                else:
                    claims.append({"text": f"{tid} has not been escalated.", "source_id": tid,
                                   "quote": r["subject"], "facts": {"escalation_count": 0}})
        ticket_ids = {r["ticket_id"] for r in results if isinstance(r.get("subject"), str)}
        for tid, hist in escal.items():
            if tid in ticket_ids:
                continue                       # already summarised with its record
            if not hist:
                claims.append({"text": f"{tid} has no escalations on record.", "source_id": tid,
                               "quote": tid, "facts": {"escalation_count": 0}})
            for e in hist:
                claims.append({"text": f"On {e['at'][:10]} {e['by']} escalated {tid} from "
                                       f"{e['from_tier']} to {e['to_tier']}: {e['reason']}.",
                               "source_id": tid, "quote": e["reason"]})
        for r in results:
            sid = r.get("article_id") or r.get("document_id")
            if "text" in r and sid and "title" in r and "hits" not in r:
                text, quote = self._sentence(r["text"])
                if quote:
                    claims.append({"text": f"{sid} “{r['title']}”: {text}",
                                   "source_id": sid, "quote": quote})
        hits = [(h, r.get("query", user_text), i, n) for n, r in enumerate(results)
                for i, h in enumerate(h for h in r.get("hits", []) if h.get("relevance") != "weak")]
        # Scores from different servers are not comparable: take each search's
        # best hit before any search's second best (one search: unchanged).
        hits = [(h, q) for h, q, _, _ in sorted(hits, key=lambda x: (x[2], x[3]))]
        if hits and all(h.get("relevance") == "strong" for h, _ in hits):
            # All cross-encoder scores, so hits from different servers are on
            # one scale: keep the best ones, wherever they came from.
            hits.sort(key=lambda hq: -float(hq[0].get("score") or 0))
            # A hit far below the best is a different topic that merely
            # cleared the weak cut-off (a refund question pulling an error-code
            # row); related passages sit within ~1 point of each other.
            best = float(hits[0][0].get("score") or 0)
            hits = [hq for hq in hits if float(hq[0].get("score") or 0) >= best - MARGIN]
        seen = set()
        for h, query in hits:
            text, quote = self._sentence(h["text"], query, best_match="document_id" in h)
            if not quote or quote in seen or len(claims) >= 6 or len(seen) >= 2:
                continue
            seen.add(quote)
            claims.append({"text": text, "source_id": h.get("article_id") or h.get("document_id"),
                           "chunk_id": h["chunk_id"], "quote": quote})
        if not claims:
            why = notes[0] if notes else "the help centre and ticket history have nothing on this"
            return {"kind": "refusal", "claims": [],
                    "answer": f"I can't answer that from the connected sources: {why}."}
        body = " ".join(f"{c['text']} [{c['source_id']}]" for c in claims)
        if notes:
            body += " Note: " + "; ".join(notes)
        return {"kind": "answer", "answer": body, "claims": claims, "notes": notes}


def default_model():
    """Claude when the SDK has a credential, else the offline planner."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return ClaudeModel()
    return OfflineModel()
