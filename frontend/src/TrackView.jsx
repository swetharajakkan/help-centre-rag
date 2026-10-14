import React, { useCallback, useEffect, useState } from 'react'

/**
 * Admin · Track: every question asked through the support agent.
 *
 * The list comes from /api/track and refreshes every 5 s, so a question a
 * user asks shows up while the admin watches. Opening one loads
 * /api/track/{id}: what the host attached, each Responder turn and tools/call
 * (server, tool, arguments, result, timing), every record the Verifier
 * re-fetched, each claim's verdict, and the answer the user saw.
 */

const ROLES = [['user', 'Users'], ['', 'Everyone'], ['admin', 'Admins']]

const when = (ts) => new Date(ts).toLocaleString()
const secs = (ms) => (ms == null ? '—' : `${(ms / 1000).toFixed(1)} s`)

function Badge({ r }) {
  if (r.error) return <span className="pf bad">FAILED</span>
  if (r.kind === 'smalltalk') return <span className="pf na">SMALL TALK</span>
  if (r.kind === 'refusal') return <span className="pf na">NOT COVERED</span>
  return r.approved
    ? <span className="pf ok">VERIFIED</span>
    : <span className="pf bad">PARTLY VERIFIED</span>
}

function Detail({ id }) {
  const [r, setR] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    setR(null); setErr(null)
    fetch(`/api/track/${id}`).then((x) => x.json().then((j) => {
      if (!x.ok) throw new Error(j.detail || `HTTP ${x.status}`)
      setR(j)
    })).catch((e) => setErr(e.message))
  }, [id])
  if (err) return <div className="banner bad"><strong>Could not load.</strong><pre>{err}</pre></div>
  if (!r) return <div className="stage"><i className="led-dot" />loading…</div>

  const tools = r.steps.filter((s) => s.kind === 'tool')
  const verifier = r.agents.find((a) => a.name === 'Verifier')
  return (
    <div className="tr-detail">
      <div className="res-head">
        <Badge r={r} />
        <span className="res-meta">
          {r.username} ({r.role}) · {when(r.ts)} · {secs(r.ms)} · model {r.model || '—'}
        </span>
      </div>
      <p className="tr-q">“{r.question}”</p>

      <div className="tr-stats">
        <div><b>{r.agents.length}</b><span>agents</span></div>
        <div><b>{r.agents.reduce((n, a) => n + (a.runs || 1), 0)}</b><span>agent runs</span></div>
        <div><b>{tools.length}</b><span>tools/call</span></div>
        <div><b>{tools.filter((t) => t.is_error).length}</b><span>failed calls</span></div>
        <div><b>{r.steps.filter((s) => s.kind === 'model').length}</b><span>model turns</span></div>
        <div><b>{verifier?.calls?.length ?? 0}</b><span>verifier re-fetches</span></div>
      </div>

      {r.error && <div className="banner bad"><strong>The agent failed.</strong><pre>{r.error}</pre></div>}

      <p className="block-title">Answer the user saw</p>
      <div className="reply-box crew-reply">{r.answer ?? '—'}</div>

      <p className="block-title">What happened, in order</p>
      <ol className="tr-flow">
        {r.agents.filter((a) => a.name === 'Router').map((a) => (
          <li key="router">
            <span className="tr-who host">Router</span>{a.did}
          </li>
        ))}
        {r.kind !== 'smalltalk' && <li>
          <span className="tr-who host">Host</span>
          {r.context.length
            ? <>attached {r.context.length} resource{r.context.length === 1 ? '' : 's'} as context (resources/read, no model involved): {r.context.map((u) => <code key={u}>{u}</code>)}</>
            : 'attached no context'}
        </li>}
        {r.steps.map((s, i) => s.kind === 'model' ? (
          <li key={i}>
            <span className="tr-who resp">Responder</span>
            model turn {s.turn} → {s.tool_uses?.length
              ? <>chose {s.tool_uses.map((u) => <code key={u.name + JSON.stringify(u.input)}>{u.name}({JSON.stringify(u.input)})</code>)}</>
              : <b>wrote the answer</b>}
            <span className="tr-mut"> · {s.input_tokens} in / {s.output_tokens} out tokens</span>
          </li>
        ) : (
          <li key={i} className={s.is_error ? 'err' : ''}>
            <span className="tr-who tool">tools/call</span>
            <b>{s.tool}</b> on <b>{s.server}</b> <code>{JSON.stringify(s.args)}</code>
            <span className="tr-mut"> · {s.ms} ms{s.is_error ? ' · isError' : ''}</span>
            <details><summary>result</summary><pre className="w9-pre">{s.result}</pre></details>
          </li>
        ))}
        {verifier?.calls?.map((c, i) => (
          <li key={`v${i}`} className={c.is_error ? 'err' : ''}>
            <span className="tr-who verif">Verifier</span>
            re-fetched {c.resource
              ? <>resource <code>{c.resource}</code></>
              : <><b>{c.tool}</b> on <b>{c.server}</b> <code>{JSON.stringify(c.args)}</code></>}
            {c.ms != null && <span className="tr-mut"> · {c.ms} ms</span>}
          </li>
        ))}
        {r.rounds.map((x) => (
          <li key={`r${x.round}`}>
            <span className="tr-who verif">Verifier</span>
            round {x.round}: <b className={x.approved ? 'okc' : 'badc'}>{x.summary}</b>
            <ul className="tr-checks">
              {x.checks.map((c, i) => (
                <li key={i}>
                  <b className={c.ok ? 'okc' : 'badc'}>{c.ok ? '✓' : '✗'}</b> {c.text}
                  <span className="tr-mut"> · source {c.source_id} via {c.refetched_via || '—'}
                    {c.reasons.length ? ` · ${c.reasons.join('; ')}` : ''}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      <p className="block-title">Agents</p>
      <table className="w9-notes"><tbody>
        {r.agents.map((a) => (
          <tr key={a.name}><td><b>{a.name}</b> ×{a.runs}</td><td>{a.did}{a.tokens ? ` · ${a.tokens.toLocaleString()} tokens` : ''}</td></tr>
        ))}
      </tbody></table>
    </div>
  )
}

export default function TrackView() {
  const [role, setRole] = useState('user')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [open, setOpen] = useState(null)

  const load = useCallback(() => {
    fetch(`/api/track?role=${role}`).then((x) => x.json().then((j) => {
      if (!x.ok) throw new Error(j.detail || `HTTP ${x.status}`)
      setData(j); setErr(null)
    })).catch((e) => setErr(e.message))
  }, [role])
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])
  useEffect(() => {
    if (data?.items?.length && !data.items.some((i) => i.id === open)) setOpen(data.items[0].id)
  }, [data])     // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="track">
      <aside className="tr-list">
        <div className="tr-list-head">
          <div className="seg" role="radiogroup" aria-label="Who">
            {ROLES.map(([v, label]) => (
              <button key={v} data-on={role === v ? 1 : 0} onClick={() => setRole(v)}>{label}</button>
            ))}
          </div>
          <span className="tr-mut">{data ? `${data.total} question${data.total === 1 ? '' : 's'}` : ''} · live</span>
        </div>
        {err && <p className="note bad">{err}</p>}
        {data && !data.items.length && (
          <p className="tr-mut tr-empty">Nothing yet. Questions asked by {role || 'anyone'} appear here as they are asked.</p>
        )}
        {data?.items.map((r) => (
          <button key={r.id} className={`tr-item ${open === r.id ? 'on' : ''}`} onClick={() => setOpen(r.id)}>
            <span className="tr-item-top"><Badge r={r} /><span className="tr-mut">{when(r.ts)}</span></span>
            <span className="tr-item-q">{r.question}</span>
            <span className="tr-mut">
              {r.username} · {r.n_agents} agents · {r.n_tool_calls} tool call{r.n_tool_calls === 1 ? '' : 's'} · {secs(r.ms)}
            </span>
            {r.tools_called?.length > 0 && (
              <span className="tr-tools">{r.tools_called.map((t) => <code key={t}>{t.split('__').pop()}</code>)}</span>
            )}
          </button>
        ))}
      </aside>
      <section className="tr-main">
        {open ? <Detail id={open} /> : <div className="empty"><h2>Track</h2><p>Select a question to see what the agents did.</p></div>}
      </section>
    </div>
  )
}
