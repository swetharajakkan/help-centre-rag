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
  ['console', 'Ask'],
  ['servers', 'Servers'],
]

function ServerCard({ name, s }) {
  return (
    <div className={`w9-card ${s.connected ? '' : 'down'}`}>
      <div className="w9-card-head">
        <b>{name}</b>
        <span className={`pf ${s.connected ? 'ok' : 'bad'}`}>{s.connected ? 'connected' : 'down'}</span>
        <span className="res-meta">{s.connect_ms} ms</span>
      </div>
      {s.error && <p className="note bad">{s.error}</p>}
      {s.tools.length > 0 && (
        <p className="w9-mut">tools: {s.tools.map((t) => <code key={t.name}>{t.name}</code>)}</p>
      )}
    </div>
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
        <button className="send" onClick={run} disabled={busy || !q.trim()}>{busy ? 'Running…' : 'Ask'}</button>
      </div>
      {err && <p className="note bad">{err}</p>}
      {data && <div className="msg bot"><CrewAnswer data={data} /></div>}
    </>
  )
}

export default function Week9View() {
  const [tab, setTab] = useState('console')
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
      {err && <div className="banner bad"><strong>Could not load.</strong><pre>{err}</pre></div>}
      {!d && !err && <div className="stage"><i className="led-dot" />loading…</div>}
      {d && (
        <div className="w9-body">
          <div className="hints">
            <span className="hint-chip"><b>{disc.tool_count}</b> tools</span>
            {Object.entries(disc.servers).map(([n, s]) => (
              <span key={n} className="hint-chip">{n}: <b>{s.connected ? s.tools.length : 'down'}</b></span>
            ))}
            <button className="ghost" onClick={() => load(true)}>Reconnect</button>
          </div>

          {tab === 'servers' && Object.entries(disc.servers).map(([n, s]) => <ServerCard key={n} name={n} s={s} />)}
          {tab === 'console' && <Console />}
        </div>
      )}
    </div>
  )
}
