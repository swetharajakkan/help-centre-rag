import React, { useEffect, useState } from 'react'
import CrewAnswer from './CrewAnswer.jsx'

/**
 * Week 9 (admin): MCP — the standard way agents reach tools & data.
 *
 * Everything on this page comes from /api/week9, which reads the LIVE host's
 * tools/list results and the evidence files the week9/*.py scripts wrote, so
 * what is shown is what the agent actually discovered and what the scripts
 * actually measured.
 */

const TABS = [
  ['topics', 'Topics'],
  ['servers', 'Servers & discovery'],
  ['proof', 'Config-only proof'],
  ['wire', 'JSON-RPC wire'],
  ['errors', 'Recoverable errors'],
  ['risk', 'Risk note'],
  ['gateway', 'Gateway (bonus)'],
  ['console', 'Console'],
]

const TOPICS = [
  ['What MCP is', 'An open protocol (JSON-RPC 2.0) for connecting a model-driven app to tools and data. A server is written once and any MCP host can use it, so adding the ticket-history server was a config edit, not an integration project.', 'proof'],
  ['Host, client, server', 'Host = week9/agent (owns the conversation, the model, the trust boundary). Client = one fastmcp.Client per server inside the host, one session each. Server = a separate process exposing primitives: help-centre-rag (ours) and ticket-history (Support Ops).', 'servers'],
  ['Where the AI runs', 'In the host only: week9/agent/loop.py calls model.complete between tools/list and tools/call. Neither server runs a model; the wire carries only tool names, arguments and results.', 'wire'],
  ['Tools, resources, prompts', 'Tools are model-invoked (get_ticket, search_help_centre). Resources are app-attached: the host reads tickets://{id}/escalations into the prompt when a ticket id appears, so the model never spends a turn on it. Prompts are user-picked templates (grounded_answer, handover_note).', 'servers'],
  ['Transports (stdio, HTTP)', 'help-centre-rag is a stdio child process the host spawns and owns. ticket-history is Streamable HTTP on :8765 with a session id header — a remote server reached like a vendor’s.', 'servers'],
  ['JSON-RPC handshake', 'initialize → notifications/initialized → tools/list → tools/call, captured raw with plain httpx and annotated field by field.', 'wire'],
  ['Tool discovery', 'The tool list the model sees is built only from tools/list at connect time: 2 tools before, 4 after, with zero changed lines in the agent module.', 'proof'],
  ['Building a server (fastmcp)', 'Both servers are FastMCP: @mcp.tool / @mcp.resource / @mcp.prompt; the docstring becomes the description the model reads, type hints become the inputSchema.', 'servers'],
  ['Recoverable errors', 'A tool error is a result with isError: true, written for the model. "Error 3" → 3 identical retries and no answer; "ids look like BM-nnn" → one corrected call and an answer.', 'errors'],
  ['Remote MCP & auth', 'Bearer tokens checked in HTTP before any JSON-RPC runs (401 captured on the wire). Bonus: a gateway with scoped tokens denies the escalation tool and its resource, recoverably, and audits every call.', 'gateway'],
]

const pre = (x) => <pre className="w9-pre">{x || 'Not generated yet — run the script named on this tab.'}</pre>

function ServerCard({ name, s }) {
  return (
    <div className={`w9-card ${s.connected ? '' : 'down'}`}>
      <div className="w9-card-head">
        <b>{name}</b>
        <span className={`pf ${s.connected ? 'ok' : 'bad'}`}>{s.connected ? 'connected' : 'down'}</span>
        <span className="res-meta">{s.transport} · {s.protocol || '—'} · {s.connect_ms} ms</span>
      </div>
      <p className="w9-mut"><code>{s.endpoint}</code></p>
      {s.server_info && <p className="w9-mut">serverInfo: {s.server_info.name} {s.server_info.version}</p>}
      {s.error && <p className="note bad">{s.error}</p>}
      {s.tools.map((t) => (
        <details key={t.name} className="trace">
          <summary><b>tool</b> {t.qualified}</summary>
          <pre className="w9-pre">{t.description}</pre>
          <pre className="w9-pre">{JSON.stringify(t.input_schema, null, 1)}</pre>
        </details>
      ))}
      <p className="w9-mut">
        resources: {s.resources.join(', ') || '—'} · templates: {s.resource_templates.join(', ') || '—'}
        {' '}· prompts: {s.prompts.join(', ') || '—'}
      </p>
      {s.attach?.length > 0 && (
        <p className="w9-mut">host attaches: {s.attach.map((a) => `${a.uri} when /${a.when}/`).join(', ')}</p>
      )}
    </div>
  )
}

function Wire({ text }) {
  if (!text) return pre(null)
  const w = JSON.parse(text)
  return (
    <>
      <p className="banner ok w9-line"><b>Where the model runs:</b> {w.where_the_model_runs}</p>
      {w.exchange.map((x) => (
        <div className="w9-card" key={x.step}>
          <div className="w9-card-head">
            <b>{x.step}</b><span className="res-meta">{x.http.request} → HTTP {x.http.status}</span>
          </div>
          <p className="w9-mut">{x.http._note}</p>
          <div className="w9-cols">
            <div>
              <p className="block-title">request</p>
              <pre className="w9-pre">{JSON.stringify(x.request, null, 1)}</pre>
              <Notes notes={x._request_notes} />
            </div>
            <div>
              <p className="block-title">response</p>
              <pre className="w9-pre">{x.response == null ? '(empty body)' : JSON.stringify(x.response, null, 1).slice(0, 2500)}</pre>
              <Notes notes={x._response_notes} />
            </div>
          </div>
        </div>
      ))}
    </>
  )
}

function Notes({ notes }) {
  const rows = Object.entries(notes || {})
  if (!rows.length) return null
  return (
    <table className="w9-notes"><tbody>
      {rows.map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}
    </tbody></table>
  )
}

function Console() {
  const [q, setQ] = useState('Why was TCK-4403 escalated?')
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const res = await fetch('/api/w9/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`)
      setData(d)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <div className="composer-inner w9-console">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
        <button className="send" onClick={run} disabled={busy || !q.trim()}>{busy ? 'Running…' : 'Run crew'}</button>
      </div>
      {err && <p className="note bad">{err}</p>}
      {data && <div className="msg bot"><CrewAnswer data={data} /></div>}
    </>
  )
}

export default function Week9View() {
  const [tab, setTab] = useState('topics')
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const load = (reconnect = false) => {
    setErr(null)
    const p = reconnect ? fetch('/api/week9/reconnect', { method: 'POST' }).then(() => fetch('/api/week9'))
      : fetch('/api/week9')
    p.then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`); return j }))
      .then(setD).catch((e) => setErr(e.message))
  }
  useEffect(() => load(), [])

  const disc = d?.discovery
  return (
    <div className="view w9">
      <div className="subbar">
        <div className="seg" role="tablist">
          {TABS.map(([k, label]) => (
            <button key={k} data-on={tab === k ? 1 : 0} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>
      {err && <div className="banner bad"><strong>Could not load Week 9.</strong><pre>{err}</pre></div>}
      {!d && !err && <div className="stage"><i className="led-dot" />connecting to the MCP servers…</div>}
      {d && (
        <div className="w9-body">
          <div className="hints">
            <span className="hint-chip"><b>{disc.tool_count}</b> tools discovered</span>
            {Object.entries(disc.servers).map(([n, s]) => (
              <span key={n} className="hint-chip">{n}: <b>{s.connected ? s.tools.length : 'down'}</b></span>
            ))}
            <span className="hint-chip">model <b>{d.model}</b></span>
            <button className="ghost" onClick={() => load(true)}>Re-run discovery</button>
          </div>

          {tab === 'topics' && (
            <div className="w9-grid">
              {TOPICS.map(([t, body, go]) => (
                <button key={t} className="w9-topic" onClick={() => setTab(go)}>
                  <b>{t}</b><span>{body}</span>
                </button>
              ))}
            </div>
          )}
          {tab === 'servers' && (
            <>
              <p className="w9-mut">config: <code>{disc.config}</code></p>
              {Object.entries(disc.servers).map(([n, s]) => <ServerCard key={n} name={n} s={s} />)}
              <details className="trace"><summary>mcp_config.json</summary>{pre(d.config_text)}</details>
            </>
          )}
          {tab === 'proof' && (
            <>
              <p className="w9-mut">Written by <code>week9/prove_config_only.py</code>: a throwaway git repo, commit 1 = server one, commit 2 = server one + two, the agent run from each commit’s own files.</p>
              <p className="block-title">tool counts (from tools/list)</p>{pre(d.evidence['tool_counts.txt'])}
              <p className="block-title">agent_diff.txt</p>{pre(d.evidence['agent_diff.txt'])}
              <p className="block-title">config diff</p>{pre(d.evidence['config_diff.txt'])}
            </>
          )}
          {tab === 'wire' && <Wire text={d.wire} />}
          {tab === 'errors' && pre(d.evidence['error_before_after.md'])}
          {tab === 'risk' && pre(d.risk_note)}
          {tab === 'gateway' && (
            <>
              {pre(d.evidence['bonus_gateway.md'])}
              <p className="block-title">gateway_audit.log (last 20)</p>
              {pre(d.audit_tail.join('\n'))}
            </>
          )}
          {tab === 'console' && <Console />}
        </div>
      )}
    </div>
  )
}
