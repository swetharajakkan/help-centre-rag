# Week 9 demo script: MCP, Task Set A

About 12 minutes. The order follows the rubric, highest marks first. Every command runs from the `help-centre/` folder.

---

## Before you start (5 min, before the audience arrives)

Open **four terminals** in `help-centre/`:

| Terminal | Command | Leave it running |
|---|---|---|
| T1 — server two (Support Ops) | `.venv/bin/python week9/servers/ticket_history/server.py --transport http --port 8765` | yes |
| T2 — backend | `.venv/bin/uvicorn backend.app.main:app --port 8000` | yes |
| T3 — frontend | `cd frontend && npm run dev` | yes |
| T4 — commands | the demo commands below | — |

> If a port is already in use, a copy is already running. Use it, or stop it first: `lsof -iTCP:8765 -sTCP:LISTEN` → `kill <pid>`.

Then:
1. Regenerate the evidence fresh, so the timestamps are from today:
   ```bash
   .venv/bin/python week9/prove_config_only.py
   .venv/bin/python week9/wire_capture.py
   .venv/bin/python week9/error_demo.py
   .venv/bin/python week9/bonus_gateway.py
   ```
2. Optional: clear old Track entries with `rm backend/data/track.jsonl`.
3. In the editor, open these as tabs: `week9/mcp_config.json`, `week9/evidence/agent_diff.txt`, `week9/evidence/wire.json`, `week9/evidence/error_before_after.md`, `week9/risk_note.md`.
4. In the browser, open http://localhost:5173 and confirm the login page loads.

---

## 0. The problem, in one breath (30 s)

> "Support Ops built an MCP server for ticket lookup and escalation history. They want our agent using it before shift handover, with no code release. My Week 9 agent already discovers its tools from our own RAG server over MCP. Today I'll prove that discovery is real: server two goes in with **config only**."

---

## 1. Config-only server swap: 30 + 15 marks (3 min)

**Step 1: before.** The agent with only server one:
```bash
.venv/bin/python -m week9.agent.cli --config week9/config/mcp_config.server_one.json --list-tools
```
Point at: `tools discovered: 2` (`search_help_centre`, `get_article`).

**Step 2: the change.** Show `week9/mcp_config.json`. The only addition is the `ticket-history` block: an HTTP URL, a bearer token, and one `attach` rule.

**Step 3: after.** Same agent, the normal config:
```bash
.venv/bin/python -m week9.agent.cli --list-tools
```
Point at: `tools discovered: 4`. The two new names come from the server's `tools/list` reply, not from our code.

**Step 4: a query that calls server two.**
```bash
.venv/bin/python -m week9.agent.cli --crew "Why was TCK-4403 escalated?"
```
Point at the trace line `tools/call ticket-history__get_ticket({"ticket_id": "TCK-4403"})`. The `ticket-history__` prefix shows which server answered.

**Step 5: the proof.** Open `week9/evidence/agent_diff.txt`:
- `git diff <commit1> <commit2> -- week9/agent` is **empty** → `changed lines in week9/agent: 0`
- the only file in the whole commit that changed is `mcp_config.json | 6 ++++++`
- the hashes of all agent files match in both commits *and* the working tree

> "This isn't a diff I typed. `prove_config_only.py` builds a real git repo. Commit 1 has server one, commit 2 adds server two. It runs the agent from each commit's own files and diffs them."

Then show `week9/evidence/tool_counts.txt`: **2 before → 4 after**, names listed per server.

---

## 2. The raw JSON-RPC wire: 25 marks (3 min)

Open `week9/evidence/wire.json`. It was captured with plain `httpx`, no MCP library, so you're looking at exactly the bytes sent.

Walk the steps:

| Step | Say |
|---|---|
| `unauthenticated` | "No token → HTTP **401**. Auth sits *under* JSON-RPC: no MCP method runs." |
| `initialize` | "The handshake. `id: 1` comes back in the response, which is how replies are paired with requests. The server sends back `protocolVersion`, `capabilities` (what it offers) and `serverInfo` (who wrote it). The `mcp-session-id` header names the session." |
| `initialized` | "**No `id` field**, so it's a *notification*: no reply, just 202. Only after this may requests be sent." |
| `tools_list` | "Discovery. Each tool carries a `description` (the docstring the model reads), an `inputSchema` and annotations like `readOnlyHint`." |
| `tools_call` | "Execution. `content` is for the model, `structuredContent` is for code, `isError: false`." |
| `tools_call_error` | "A bad id is still a **result** with `isError: true`, not a protocol error. That's why the model can read it and fix the call." |

**The line to say clearly:** read `where_the_model_runs` at the top of the file:
> "The model runs in the **host**, in `agent/loop.py`, *after* tools/list and *before* tools/call. It never runs in the server or on the wire. The server only lists tools and executes them."

---

## 3. Docstring as a prompt + recoverable error: 20 marks (2 min)

Open `week9/evidence/error_before_after.md`. Same question, same agent, same failing call `get_article("BM-4")`:

| | Before | After |
|---|---|---|
| error | `Error 3` | "ids look like BM-nnn… known ids… call search_help_centre" |
| what the model did | resent the **same** call 3 times, gave up | reformatted to `BM-004`, answered |
| failed calls | 3 | 1 |
| answered? | no | **yes** |

Scroll to the `diff` block: a two-word docstring became one written as a prompt (when to use the tool, the id shape, what comes back, what each error means).

**Be upfront about the cost:** "Tokens went *up*, 3,081 → 3,813, because the longer docstring is resent every turn. It costs more per question, but the question gets answered."

---

## 4. Risk note: 10 marks (1 min)

Open `week9/risk_note.md` and read the five bold labels:
**who wrote it** (Support Ops, unpinned) · **what it can reach** (every ticket, including customer emails; ticket text is a prompt-injection channel) · **what it logs** (every call with arguments, no rotation) · **stolen token** (static, no expiry, can walk all TCK ids) · **verdict: ship only behind the gateway.**

---

## 5. Bonus: one gateway, audit, scoped token (1.5 min)

```bash
.venv/bin/python week9/bonus_gateway.py
```
Point at:
- **`agent-full`**: works normally.
- **`agent-no-escalations`**: `get_escalation_history` → `permission denied … Call ticket-history_get_ticket … instead`. The model **reads the denial and switches** to `get_ticket`, and the answer notes what it couldn't see.
- The **audit lines** at the bottom: one per call, with `caller`, `tool`, `ticket_id`, `outcome`.

> "The resource is denied too. Otherwise the app could attach the escalation history and get around the denied tool."

---

## 6. The app: two logins, two agents, Track (2 min)

**As user.** Sign in with `user` / `user123`.
1. Type **"Hi"**: a friendly reply with a **CHAT** badge (small talk, no tools).
2. Sidebar → Week 9 → **"Why was TCK-4403 escalated?"** → **VERIFIED · 4 claims**, with sources `TCK-4403`, `BM-004`.
   > "One agent, the Responder, writes the answer. A second agent, the Verifier, fetches every cited record again over MCP and checks the quote, the facts and every number before the user sees it."
3. Sign out.

**As admin.** Sign in with `admin` / `admin123` → the **Track** tab opens.
1. The user's questions are at the top. Click "Why was TCK-4403 escalated?".
2. Point at the counters: **2 agents · tools/call · verifier re-fetches**.
3. Walk "What happened, in order": **Host** attached `tickets://TCK-4403/escalations` → **Responder** chose `get_ticket` → **tools/call** on ticket-history → … → **Verifier** re-fetched → round 1: **4/4 claims verified**.
4. Click the "Hi" entry: **SMALL TALK**, Router replied directly with no tools.
5. **Chat** tab → **MCP · W9** → **Topics**. One card per syllabus topic, each linking to its evidence.

> "The roles are enforced by the server, not just hidden in the UI. A user session gets 403 on everything except asking."

---

## Questions you are likely to get

| Question | Answer |
|---|---|
| **Where does the AI run?** | In the host (`week9/agent/loop.py` → `model.complete`). Neither server imports a model. |
| **Host vs client vs server?** | Host = our agent process (conversation, model, trust boundary). Client = one `fastmcp.Client` per server inside the host. Server = a separate process exposing tools/resources/prompts. |
| **Why is escalation history a resource *and* a tool?** | Support Ops ship both. Our host *attaches* the resource when a ticket id appears (config `attach`), so the model never spends a turn fetching it. The tool remains for hosts that don't attach, and it's what the gateway scopes away. |
| **stdio vs HTTP?** | Server one is a stdio child process the host starts and owns. Server two is remote Streamable HTTP with a session header and a bearer token, the way you'd reach a vendor. |
| **Did you hard-code the tool list?** | No. `host.tool_specs()` is built only from `tools/list`. Proof: 0 changed lines, 2 → 4 tools. |
| **What if server two is down?** | The host reports it and carries on with server one (tested: `test_dead_server_does_not_sink_the_rest`). |
| **Is that a real LLM?** | This checkout has no `ANTHROPIC_API_KEY`, so it's the offline planner in `agent/model.py`. It sees only the conversation and plans from tool descriptions and error text. Set a key and the same code calls `claude-opus-5-5`. Rerun the scripts for Claude transcripts. |
| **Why trust a third-party server?** | We don't by default. See the risk note: ship it only behind the gateway, with scoped short-lived tokens. |
| **How were the servers built?** | FastMCP: `@mcp.tool`, `@mcp.resource`, `@mcp.prompt`. The docstring becomes the description and the type hints become the `inputSchema`. |

---

## If something breaks mid-demo

| Symptom | Fix |
|---|---|
| `ticket-history ... FAILED` / only 2 tools | T1 isn't running. Restart it; in the UI, MCP · W9 → **Re-run discovery**. |
| UI says "Backend not reachable" | T2 stopped. Restart uvicorn. |
| Stuck on the login screen after signing in | Hard refresh (Cmd+Shift+R). |
| A script fails | Every evidence file is already in `week9/evidence/`. Open it and talk through it. |
| Run the tests live as a confidence check | `.venv/bin/python -m pytest backend/tests/test_week9.py` (~25 s) |
