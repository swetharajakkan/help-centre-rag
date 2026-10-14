# Week 9 — MCP · Task Set A: add the ticket-history server without touching the agent

The Week 9 agent is an MCP host. It gets every tool from `tools/list` at connect time, and the only place a server is named is `week9/mcp_config.json`. Support Ops' ticket-history server was added by editing that file and nothing else.

## Results

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Server two added by config; one query provably calls it | `ticket-history__get_ticket({"ticket_id": "TCK-4403"})` appears in the trace, and `tickets://TCK-4403/escalations` was attached as context | `evidence/trace_server_two.json` |
| 2 | Zero lines changed in the agent module | `git diff c1 c2 -- week9/agent` is empty: **0 changed lines**. All 7 agent files hash the same in both commits and in this tree. The only file that changed is `mcp_config.json` (+6 lines). | `evidence/agent_diff.txt`, `evidence/config_diff.txt` |
| 3 | Tool count before → after, from `tools/list` | **2 before → 4 after.** Before: `search_help_centre`, `get_article`. Added: `get_ticket`, `get_escalation_history` | `evidence/tool_counts.txt` |
| 4 | Raw `initialize → tools/list → tools/call`, annotated | Captured with plain httpx (no MCP SDK), including the 401 without a token, the `notifications/initialized` 202, and an `isError` result. Every top-level field is annotated by hand. | `evidence/wire.json` (`wire.raw.json` is unannotated) |
| 5 | Docstring rewritten as a prompt + a recoverable error, before/after | Same `get_article("BM-4")` call. **Before:** `Error 3` → 3 identical retries, no answer. **After:** "ids look like BM-nnn…" → one corrected call (`BM-004`), answered. 4 → 3 model turns, 3 → 1 failed calls. Tokens went **up**, 3,081 → 3,813, because the longer docstring is resent every turn. | `evidence/error_before_after.md` |
| 6 | 5-line supply-chain risk note | Covers who wrote it, what it can reach, what it logs, what a stolen token could do, and the call: **ship only behind the gateway** | `risk_note.md` |
| ★ | Bonus: one gateway, an audit line per call, a scoped token | The agent connects to one front door. With token `agent-no-escalations`, the escalation tool **and** its resource are denied, recoverably. The model switches to `get_ticket` and says what it couldn't see. Every call writes one JSON line: caller, tool, ticket id, outcome. | `evidence/bonus_gateway.md`, `evidence/gateway_audit.log` |

**Where the model call happens:** in the host, in `week9/agent/loop.py` (`model.complete`), after `tools/list` and before `tools/call`. It never happens inside either MCP server or on the wire.

**The engine, stated plainly:** this checkout has no `ANTHROPIC_API_KEY`, so every number above comes from the offline planner in `agent/model.py`. Like weeks 6–8, it sees only the conversation (user text, attached context, the discovered tool list, tool results). It cannot import a server or read the data. With a key set, the same code calls `claude-opus-5-5` with server-side refusal fallbacks enabled. Rerun the scripts to get Claude transcripts.

## Layout

```
week9/
  mcp_config.json                 servers the agent connects to (server one + two)
  config/mcp_config.server_one.json   the "before" config
  mcp_config.gateway.json         bonus: one server, the gateway
  agent/                          THE AGENT MODULE: unchanged by adding server two
    host.py    one MCP client per server; tools/list discovery; attach resources
    model.py   where the AI runs (Claude, or the offline planner)
    loop.py    model → tools/call → model
    crew.py    Responder + Verifier (multi-agent)
    config.py  reads the config (${VAR:-default} expansion)
    cli.py     python -m week9.agent.cli
  servers/rag_server.py           server one (ours, stdio): search + get_article
  servers/ticket_history/         server two (Support Ops, HTTP + bearer auth)
  gateway.py                      bonus: fan-out proxy, scopes, audit
  prove_config_only.py            → agent_diff.txt, config_diff.txt, tool_counts.txt, trace
  wire_capture.py                 → wire.json, wire.raw.json
  error_demo.py                   → error_before_after.md
  bonus_gateway.py                → bonus_gateway.md, gateway_audit.log
  risk_note.md
  evidence/
```

## Run

```bash
.venv/bin/pip install -r requirements.txt          # adds fastmcp==3.4.8

# server two is remote: start it the way an operator would
.venv/bin/python week9/servers/ticket_history/server.py --transport http --port 8765

# the agent (it spawns server one itself over stdio)
.venv/bin/python -m week9.agent.cli --list-tools
.venv/bin/python -m week9.agent.cli --crew "Why was TCK-4403 escalated?"

# regenerate the evidence (each script starts the servers it needs)
.venv/bin/python week9/prove_config_only.py
.venv/bin/python week9/wire_capture.py
.venv/bin/python week9/error_demo.py
.venv/bin/python week9/bonus_gateway.py

.venv/bin/python -m pytest backend/tests/test_week9.py
```

## The app: two logins and two agents

- **Logins** (`backend/app/auth.py`). `user` / `user123` sees only a chat: pick a week's question in the sidebar or type one, and get the verified reply. `admin` / `admin123` gets two tabs. **Track** is a live list of every question asked (filter: Users / Everyone / Admins). Opening one shows who asked, the answer they saw, how many agents ran, every tools/call (server, tool, arguments, result, timing, errors), what the host attached, what the Verifier re-fetched, and each claim's verdict. **Chat** is the full app as before, including the **MCP · W9** view. Track records live in `backend/data/track.jsonl` (gitignored, admin-only, written by `backend/app/track.py`). The roles are enforced on the server for every `/api/*` request, not just hidden in the UI. A `user` session gets 403 on everything except `/api/w9/ask`. Sessions are an HMAC-signed HttpOnly cookie. Set real accounts with `HELP_CENTRE_USERS="name:password:role,..."` and a stable secret with `HELP_CENTRE_AUTH_SECRET`. The demo passwords are for a laptop only.
- **Responder + Verifier** (`agent/crew.py`). The Responder runs the MCP tool loop and drafts JSON claims, each with a source id and a verbatim quote. The Verifier ignores the Responder's tool results. For each claim it picks a lookup tool itself, **re-fetches the cited record over MCP**, and checks three things: the quote is verbatim, each stated field matches, and every figure appears in the source. With Claude available, it also asks a second model call whether the quote supports the claim. If a claim is rejected, there is one revision round. If it still fails, the unverified claims are dropped or the question goes to a human. Tests confirm a forged status, a forged quote and a forged figure are each rejected.

## Sign-up, MongoDB, and admin documents (server three)

- **Database.** MongoDB Atlas, from `MONGODB_URI` in `.env` (`backend/app/db.py`). Collections: `users` (pbkdf2-hashed passwords), `admin_emails` (who may become an admin; seeded with `swetharajakkan@yopmail.com`, `helpcentre.admin@yopmail.com`, `supportops.lead@yopmail.com`, `billing.admin@yopmail.com`), `documents` (original bytes + extracted text + categories) and `counters`.
- **Sign-up** (`backend/app/auth.py`, `frontend/src/Login.jsx`). Anyone can sign up as a **user**. An **admin** sign-up needs both an email on `admin_emails` and the admin code (`HELP_CENTRE_ADMIN_CODE`, default `HC-ADMIN-2026`). Both failures return the same message, so the form doesn't reveal which emails are admins. Login is by email. The demo accounts (`user`/`admin`) still work without a database.
- **Upload** (admin → **Documents** tab, `backend/app/documents.py`). Upload a PDF, Markdown, text, CSV, JSON, HTML or image file, pick one or more categories (Refund, Billing, … or your own), and it is stored in `documents`.
- **Answering from it.** `week9/servers/documents_server.py` (`search_documents`, `get_document`, `docs://catalog`, `docs://categories`) was added as one block in `mcp_config.json`. It reads Mongo on every call, so a question asked straight after an upload is answered from it, by users too, and the Verifier re-fetches `DOC-nnn` like any other source. The offline planner now sends a plain question to **every** discovered search tool and keeps the best-scored hits. Tool count with all three servers: **6**.

## The ten topics, and where each one is covered

| Topic | Covered by |
|---|---|
| What MCP is | The task itself: a second server added by config. `prove_config_only.py` |
| Host, client, server | `agent/host.py` docstring: host = this process, one `fastmcp.Client` per server, servers are separate processes |
| Where the AI runs | `agent/model.py` + `loop.py`. The `where_the_model_runs` line in `wire.json`. No server imports a model |
| Tools, resources, prompts | Tools: `get_ticket`, `search_help_centre`. Resources: `tickets://{id}/escalations` is **attached by the host** (config `attach`), so the model doesn't spend a turn fetching it, and `kb://articles`. Prompts: `grounded_answer`, `handover_note` |
| Transports (stdio, HTTP) | Server one is a stdio child the host spawns. Server two is Streamable HTTP with an `mcp-session-id` header |
| JSON-RPC handshake | `wire.json`: initialize → notifications/initialized → tools/list → tools/call |
| Tool discovery | `host.tool_specs()` is built only from `tools/list`. A dead server is reported and skipped (tested) |
| Building a server (fastmcp) | `servers/rag_server.py`, `servers/ticket_history/server.py`: `@mcp.tool`, `@mcp.resource`, `@mcp.prompt` |
| Recoverable errors | Both servers raise `ToolError` text written for the model and returned as `isError: true`. Each error says whether it is malformed / missing / denied, and whether to retry. `error_before_after.md` |
| Remote MCP & auth | Bearer tokens checked in HTTP before any JSON-RPC (the 401 in `wire.json`). The gateway's scoped tokens. `risk_note.md` |

## Things found along the way

- **Breadcrumb quotes failed verification.** The chunker prefixes each chunk with `Title > Section`, which is not in the article. The first offline drafts quoted it, and the Verifier rejected those claims. The Responder now skips that line.
- **Substring figure matching let a forged "7" through,** because "2026-09-27" contains a 7. The Verifier now matches whole numbers. A test covers it.
- **The gateway proxy forwards the caller's `Authorization` header upstream,** which overwrote the gateway's own ticket token (401) and would have leaked the agent's gateway token to the vendor. The upstream credential is now set as httpx auth.
- **Off-corpus questions got verbatim but irrelevant quotes.** Faithfulness is not relevance. The RAG server now labels each hit's `relevance` from the reranker score (in-corpus ≥ −1.0, off-corpus ≤ −1.88; cut at −1.5), and its docstring tells the model to treat weak hits as "not covered".
