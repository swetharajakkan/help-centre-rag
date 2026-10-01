import React, { useEffect, useMemo, useState } from 'react'

/**
 * Week 7: does this need to be an agent? Agent vs fixed workflow, raced.
 *
 * Everything comes from /api/week7, which reads week7/race.json,
 * week7/budget_termination.log and the week7 sources as the CLI wrote them.
 * The buttons on this page call the same Python functions the CLI does
 * (run_agent, run_workflow, race.main, budget_demo.run_demo), so a number
 * seen here and a number printed in the terminal come from one code path.
 */

const TABS = [
  ['race', 'Race & Workflow vs Agent'],
  ['react', 'ReAct Trace'],
  ['branching', 'Branching'],
  ['budgets', 'Budgets & Stop Conditions'],
  ['tool', 'Tool Definitions'],
  ['memory', 'Memory & Vector Recall'],
  ['mem0', 'mem0 Library'],
  ['graph', 'LangGraph Framework'],
  ['bonus', '30-Turn Threads'],
  // ['code', 'Source Code'],
]
const CLS_LABEL = { straight: 'straight', branch: 'branch', multi_order: 'multi-order' }
const FIELDS = ['decision', 'refund_order_id', 'refund_amount_usd', 'escalate']
const BUDGET_LABEL = {
  max_iterations: 'Max iterations (model calls)',
  max_tokens: 'Max tokens (in + out, summed)',
  max_cost_usd: 'Max cost (USD)',
  max_wall_s: 'Max wall-clock (seconds)',
}

const usd = (x, d = 4) => (x == null ? '—' : `$${Number(x).toFixed(d)}`)
const num = (x) => (x == null ? '—' : Number(x).toLocaleString())

async function api(url, body) {
  const res = await fetch(url, body === undefined ? undefined : {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  const text = await res.text()
  let data
  try { data = JSON.parse(text) } catch { throw new Error(text.slice(0, 300)) }
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

function Pass({ ok }) {
  return <span className={`w7-pf ${ok ? 'ok' : 'bad'}`}>{ok ? 'PASS' : 'FAIL'}</span>
}

function Path({ path, other }) {
  // Steps the other system did not take at this position are marked, so a
  // changed path is visible without reading both lists.
  return (
    <span className="w7-path">
      {path.map((t, i) => (
        <span key={i} className={`w7-step ${other && other[i] !== t ? 'diff' : ''}`}>
          {t.replace('lookup_refund_policy', 'refund_policy')}
        </span>
      ))}
      {!path.length && <span className="w7-step none">no tools</span>}
    </span>
  )
}

function TraceLink({ url }) {
  return url
    ? <a className="w7-trace" href={url} target="_blank" rel="noreferrer">Langfuse ↗</a>
    : <span className="w7-trace off">not traced</span>
}

/* ------------------------------------------------------------- race tab */

function Comparison({ summary }) {
  const a = summary.agent
  const w = summary.workflow
  const rows = [
    ['Pass rate', `${(a.pass_rate * 100).toFixed(0)}%`, `${(w.pass_rate * 100).toFixed(0)}%`,
      a.pass_rate === w.pass_rate ? null : a.pass_rate > w.pass_rate ? 'agent' : 'workflow',
      `${a.passed}/${a.n} vs ${w.passed}/${w.n}`],
    ['P50 latency', `${a.p50_latency_s.toFixed(2)} s`, `${w.p50_latency_s.toFixed(2)} s`,
      a.p50_latency_s < w.p50_latency_s ? 'agent' : 'workflow',
      `${(a.p50_latency_s / w.p50_latency_s).toFixed(1)}× slower for the agent`],
    ['Total tokens', num(a.total_tokens), num(w.total_tokens),
      a.total_tokens < w.total_tokens ? 'agent' : 'workflow',
      `${(a.total_tokens / w.total_tokens).toFixed(1)}× — ${a.llm_calls} vs ${w.llm_calls} model calls`],
    ['Cost per ticket', usd(a.cost_per_ticket_usd), usd(w.cost_per_ticket_usd),
      a.cost_per_ticket_usd < w.cost_per_ticket_usd ? 'agent' : 'workflow',
      `${(a.cost_per_ticket_usd / w.cost_per_ticket_usd).toFixed(1)}×`],
  ]
  return (
    <table className="w7-cmp">
      <thead>
        <tr><th>metric (same 10 tickets)</th><th>Agent</th><th>Fixed workflow</th><th>gap</th></tr>
      </thead>
      <tbody>
        {rows.map(([m, av, wv, better, note]) => (
          <tr key={m}>
            <td>{m}</td>
            <td className={better === 'agent' ? 'win' : ''}>{av}</td>
            <td className={better === 'workflow' ? 'win' : ''}>{wv}</td>
            <td className="mut">{note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Steps({ run }) {
  // One block per step: a heading line, then the arguments and the result
  // each on their own wrapped line, so long JSON never leaves the card.
  return (
    <ol className="w7-steps">
      {run.steps.map((s, i) => s.kind === 'llm' ? (
        <li key={i} className="llm">
          <div className="w7-sh"><b>model call</b>
            <span>stop {s.stop_reason} · {num(s.input_tokens)} in / {num(s.output_tokens)} out · {usd(s.cost_usd, 5)} · {s.latency_s.toFixed(2)} s</span>
          </div>
        </li>
      ) : (
        <li key={i} className="tool">
          <div className="w7-sh"><b>{s.name}</b><span>tool call</span></div>
          <div className="w7-kv"><span>args</span><code>{JSON.stringify(s.args)}</code></div>
          <div className="w7-kv"><span>result</span><code>{JSON.stringify(s.result)}</code></div>
        </li>
      ))}
      {run.terminated && (
        <li className="stop">
          <div className="w7-sh"><b>budget {run.terminated.budget}</b>
            <span>limit {run.terminated.limit}, observed {run.terminated.observed} · terminated cleanly, handed to a human</span>
          </div>
        </li>
      )}
    </ol>
  )
}

function RunCard({ title, run, other, onRerun, busy }) {
  return (
    <div className={`w7-run ${run.grade?.passed ? 'pass' : 'fail'}`}>
      {/* Two fixed rows, so the agent and workflow cards line up. */}
      <div className="w7-run-top">
        <b>{title}</b>
        <Pass ok={run.grade?.passed} />
        {run.live && <span className="w7-live">live re-run</span>}
        <span className="spacer" />
        <TraceLink url={run.trace_url} />
        <button type="button" className="w7-btn sm" disabled={busy} onClick={onRerun}>
          {busy ? 'running…' : 're-run'}
        </button>
      </div>
      <div className="w7-run-stats">
        <span>{num(run.total_tokens)} tokens</span>
        <span>{usd(run.cost_usd)}</span>
        <span>{run.latency_s.toFixed(2)} s</span>
        <span>{run.llm_calls} model call{run.llm_calls === 1 ? '' : 's'}</span>
        <span>{run.path.length} tool call{run.path.length === 1 ? '' : 's'}</span>
      </div>
      <Path path={run.path} other={other?.path} />
      {!!run.grade?.mismatches?.length && (
        <p className="w7-miss">
          {run.grade.mismatches.map((m) => (
            <span key={m.field}>
              <b>{m.field}</b> expected <code>{String(m.expected)}</code>, got <code>{String(m.got)}</code>
            </span>
          ))}
        </p>
      )}
      {!!run.grade?.assertions_failed?.length && (
        <p className="w7-miss">Week-6 assertions failed: {run.grade.assertions_failed.join(', ')}</p>
      )}
      <pre className="w7-reply">{run.output.reply}</pre>
      <details>
        <summary>step trace ({run.steps.length} steps)</summary>
        <Steps run={run} />
      </details>
    </div>
  )
}

function TicketDetail({ tid, race, runs, setRun }) {
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const t = race.tickets[tid]
  const exp = race.expected[tid]
  const rerun = async (system) => {
    setBusy(system); setErr(null)
    try {
      const r = await api('/api/week7/run', { ticket_id: tid, system })
      setRun(system, tid, { ...r, live: true })
    } catch (e) { setErr(e.message) } finally { setBusy(null) }
  }
  return (
    <div className="w7-detail">
      <div className="w7-ticket">
        <p className="w7-msg">“{t.message}”</p>
        <p className="mut">
          tier {t.customer_tier} · request {t.request_type} · orders{' '}
          {t.order_ids.length ? t.order_ids.join(', ') : 'none named'}
        </p>
        <p className="w7-exp">
          <span className="ev-k">expected contract</span>
          {FIELDS.map((f) => <span key={f}><b>{f}</b> {String(exp[f])}</span>)}
        </p>
      </div>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      <div className="w7-runs">
        <RunCard title="Agent" run={runs.agent[tid]} other={runs.workflow[tid]}
          busy={busy === 'agent'} onRerun={() => rerun('agent')} />
        <RunCard title="Fixed workflow" run={runs.workflow[tid]} other={runs.agent[tid]}
          busy={busy === 'workflow'} onRerun={() => rerun('workflow')} />
      </div>
    </div>
  )
}

const CLASS_INFO = [
  ['straight', 'Straight',
    'One paid order. The policy table decides the answer (refund, outside the 30-day window, …) and nothing the tools return changes which step comes next.'],
  ['branch', 'Branch',
    'What step 3 has to do depends on what step 2 found: the order is missing, already refunded, under a bank chargeback, over the USD 100 approval limit, or the customer gave no order number at all.'],
  ['multi_order', 'Multi-order',
    'The customer names two orders (a double charge). How many get_order calls are needed is only known after reading the ticket, and the two charges must be compared to find the duplicate.'],
]

function Legend({ race }) {
  const ids = (cls) => race.ticket_ids.filter((t) => race.expected[t].cls === cls)
  return (
    <section className="w7-card">
      <h3>What the ticket classes and tools mean</h3>
      <div className="w7-legend">
        {CLASS_INFO.map(([cls, name, text]) => (
          <div key={cls} className="w7-leg">
            <span className={`w7-cls ${cls}`}>{name}</span>
            <p>{text}</p>
            <p className="mut">{ids(cls).length} ticket{ids(cls).length === 1 ? '' : 's'}: {ids(cls).join(', ')}</p>
          </div>
        ))}
      </div>
      <div className="w7-legend">
        <div className="w7-leg">
          <b>3 tools</b>
          <p><code>get_ticket</code> reads the helpdesk ticket · <code>get_order</code> reads one
            billing order · <code>lookup_refund_policy</code> <span className="w7-badge added">new in Week 7</span>{' '}
            turns the facts into the SP-001 decision.</p>
        </div>
        <div className="w7-leg">
          <b>How many are used</b>
          <p><b>Agent:</b> the model picks each call from the previous result, usually 3 tool
            calls and 4 model calls; 4 tools on the double charge (two get_order), 2 when no order is named.</p>
          <p><b>Fixed workflow:</b> always the same 3 tool calls and 1 model call.</p>
        </div>
        <div className="w7-leg">
          <b>How a tool is made</b>
          <p>In <code>week7/tools.py</code>: a JSON definition (name, one-job description,
            typed parameters with enums) that the model reads, plus a plain Python function
            that does the work. The agent loop runs whichever one the model asks for.
            The <b>Third tool</b> tab shows the definitions before and after.</p>
        </div>
      </div>
    </section>
  )
}

function RaceTab({ race, runs, setRun, onRerace, racing }) {
  const [open, setOpen] = useState(null)
  return (
    <>
      <section className="w7-card">
        <div className="w7-h">
          <h3>Agent vs fixed workflow — the four numbers</h3>
          <span className="spacer" />
          <button type="button" className="w7-btn" onClick={onRerace} disabled={racing}>
            {racing ? 'racing 20 runs… (~25 s)' : 'Re-run the race'}
          </button>
        </div>
        <Comparison summary={race.summary} />
        <p className="w7-foot">
          Ran {new Date(race.ran_at).toLocaleString()} · model <b>{race.engine.model}</b>,
          the same one for both systems · tokens {race.engine.tokens} · cost priced
          as {race.engine.priced_as} (${race.engine.price_in_per_mtok}/M in,
          ${race.engine.price_out_per_mtok}/M out) · latency {race.engine.latency}.
          Written to <code>week7/race.csv</code>.
        </p>
      </section>

      <section className="w7-card verdict">
        <div className="w7-h">
          <h3>Verdict</h3>
          <span className={`w7-wc ${race.verdict_words < 150 ? 'ok' : 'bad'}`}>
            {race.verdict_words} words
          </span>
        </div>
        <p className="w7-verdict">{race.verdict}</p>
        <p className="w7-foot">
          Generated from the measured results by <code>race.py</code>, so it is
          rewritten, and cannot contradict the table, whenever the race is re-run.
        </p>
      </section>

      <Legend race={race} />

      <section className="w7-card">
        <h3>Per ticket — click a row for both outputs, step traces and live re-runs</h3>
        <div className="w7-scroll">
          <table className="w7-tickets">
            <thead>
              <tr>
                <th>ticket</th><th>class</th>
                <th>agent</th><th>tokens</th><th>cost</th><th>latency</th>
                <th>workflow</th><th>tokens</th><th>cost</th><th>latency</th>
              </tr>
            </thead>
            <tbody>
              {race.ticket_ids.map((tid) => {
                const a = runs.agent[tid]
                const w = runs.workflow[tid]
                return (
                  <React.Fragment key={tid}>
                    <tr className={`click ${open === tid ? 'on' : ''}`}
                      onClick={() => setOpen(open === tid ? null : tid)}>
                      <td className="mono">{open === tid ? '▾' : '▸'} {tid}</td>
                      <td><span className={`w7-cls ${race.expected[tid].cls}`}>
                        {CLS_LABEL[race.expected[tid].cls]}</span></td>
                      <td><Pass ok={a.grade.passed} /></td>
                      <td className="n">{num(a.total_tokens)}</td>
                      <td className="n">{usd(a.cost_usd)}</td>
                      <td className="n">{a.latency_s.toFixed(2)} s</td>
                      <td><Pass ok={w.grade.passed} /></td>
                      <td className="n">{num(w.total_tokens)}</td>
                      <td className="n">{usd(w.cost_usd)}</td>
                      <td className="n">{w.latency_s.toFixed(2)} s</td>
                    </tr>
                    {open === tid && (
                      <tr className="w7-open"><td colSpan={10}>
                        <TicketDetail tid={tid} race={race} runs={runs} setRun={setRun} />
                      </td></tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

/* -------------------------------------------------------- branching tab */

function BranchingTab({ race }) {
  const p = race.paths
  const varied = p.filter((r) => r.path_differs)
  const broke = p.filter((r) => r.outcome_differs)
  return (
    <section className="w7-card">
      <h3>Does the execution path change with the input?</h3>
      <div className="ev-band">
        <div className="ev-stat"><span className="ev-k">tickets where step 3 depends on step 2</span>
          <b>{p.filter((r) => r.cls !== 'straight').length}<i>/</i>{p.length}</b>
          <span className="ev-sub2">branch + multi-order classes</span></div>
        <div className="ev-stat"><span className="ev-k">agent path differed from workflow</span>
          <b>{varied.length}<i>/</i>{p.length}</b>
          <span className="ev-sub2">{varied.map((r) => r.ticket_id).join(', ') || 'none'}</span></div>
        <div className="ev-stat big"><span className="ev-k">outcome differed</span>
          <b>{broke.length}<i>/</i>{p.length}</b>
          <span className="ev-sub2">{broke.map((r) => r.ticket_id).join(', ') || 'none'} — the only place the path mattered</span></div>
      </div>
      <div className="w7-scroll">
        <table className="w7-tickets">
          <thead>
            <tr><th>ticket</th><th>what step 2 found</th><th>agent path</th>
              <th>workflow path</th><th>path</th><th>outcome</th></tr>
          </thead>
          <tbody>
            {p.map((r) => (
              <tr key={r.ticket_id} className={r.outcome_differs ? 'hot' : ''}>
                <td className="mono">{r.ticket_id}<br />
                  <span className={`w7-cls ${r.cls}`}>{CLS_LABEL[r.cls]}</span></td>
                <td className="mut">{r.branch_note || 'one paid order, policy table decides'}</td>
                <td><Path path={r.agent_path} other={r.workflow_path} /><br />
                  <span className="mut">{r.agent_decision} <Pass ok={r.agent_passed} /></span></td>
                <td><Path path={r.workflow_path} other={r.agent_path} /><br />
                  <span className="mut">{r.workflow_decision} <Pass ok={r.workflow_passed} /></span></td>
                <td>{r.path_differs ? <b className="warn">changed</b> : <span className="mut">same</span>}</td>
                <td>{r.outcome_differs ? <b className="bad">changed</b> : <span className="mut">same</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="w7-foot">
        Missing, refunded, charged-back and over-limit orders all take the same
        three tools. The branch lives in the <b>result</b> of lookup_refund_policy,
        not in the choice of the next tool, so the fixed path handles it. The path
        only has to change when the number of get_order calls depends on the
        ticket's contents.
      </p>
    </section>
  )
}

/* ----------------------------------------------------------- budgets tab */

function BudgetsTab({ data, onSaved }) {
  const defaults = data.default_budgets
  const [ticket, setTicket] = useState('TCK-7009')
  const [budget, setBudget] = useState('max_tokens')
  const [limit, setLimit] = useState(2500)
  const [save, setSave] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [res, setRes] = useState(null)

  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await api('/api/week7/budget', {
        ticket_id: ticket, budget, limit: Number(limit), save,
      })
      setRes(r)
      if (save) onSaved()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <section className="w7-card">
        <h3>The four budgets, enforced in the agent loop</h3>
        <div className="w7-budgets">
          {Object.entries(defaults).map(([k, v]) => (
            <div key={k} className={`ev-stat ${k === budget ? 'big' : ''}`}>
              <span className="ev-k">{BUDGET_LABEL[k]}</span>
              <b>{k === budget ? limit : v}</b>
              <span className="ev-sub2">{k === budget ? 'being tested' : 'default'}</span>
            </div>
          ))}
        </div>
        <p className="w7-foot">
          Checked before every model call (tokens and cost are checked again right
          after one, so a call that crosses the line cannot also trigger tool calls).
          On breach the loop stops, the ticket goes to a human with an [ESCALATED]
          reply, and the event is scored on the Langfuse trace.
        </p>

        <div className="w7-form">
          <label>ticket
            <select value={ticket} onChange={(e) => setTicket(e.target.value)}>
              {data.race.ticket_ids.map((t) => <option key={t}>{t}</option>)}
            </select>
          </label>
          <label>budget to tighten
            <select value={budget} onChange={(e) => {
              setBudget(e.target.value)
              setLimit({
                max_iterations: 2, max_tokens: 2500, max_cost_usd: 0.008,
                max_wall_s: 0.5
              }[e.target.value])
            }}>
              {Object.keys(defaults).map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </label>
          <label>limit
            <input type="number" step="any" value={limit}
              onChange={(e) => setLimit(e.target.value)} />
          </label>
          <label className="chk">
            <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} />
            save as week7/budget_termination.log
          </label>
          <button type="button" className="w7-btn" onClick={run} disabled={busy}>
            {busy ? 'running…' : 'Run agent under this budget'}
          </button>
        </div>
        {err && <div className="banner bad"><pre>{err}</pre></div>}
        {res && (
          <div className={`w7-term ${res.terminated ? 'hit' : 'ok'}`}>
            <div className="w7-term-grid">
              <div><span className="ev-k">ticket running</span><b>{res.ticket_id}</b></div>
              <div><span className="ev-k">budget reached</span>
                <b>{res.terminated ? res.terminated.budget : 'none'}</b></div>
              <div><span className="ev-k">configured limit</span>
                <b>{res.terminated ? res.terminated.limit : '—'}</b></div>
              <div><span className="ev-k">observed</span>
                <b>{res.terminated ? res.terminated.observed : '—'}</b></div>
              <div><span className="ev-k">termination</span>
                <b className={res.terminated ? 'ok' : ''}>
                  {res.terminated ? 'clean — handed to a human' : `finished: ${res.output.decision}`}</b></div>
              <div><span className="ev-k">trace</span><TraceLink url={res.trace_url} /></div>
            </div>
            <pre className="w7-log">{res.log_text}</pre>
          </div>
        )}
      </section>

      <section className="w7-card">
        <h3>Saved termination log — week7/budget_termination.log</h3>
        <pre className="w7-log">{data.budget_log || 'No log yet. Run `.venv/bin/python week7/budget_demo.py`.'}</pre>
      </section>
    </>
  )
}

/* -------------------------------------------------------------- tool tab */

function ToolTab({ data }) {
  return (
    <section className="w7-card">
      <h3>Tool descriptions and parameters: before Week 7 → now</h3>
      <p className="w7-foot">
        The new tool has one job: map one order's facts to the SP-001 decision.
        Adding it forced a change to get_order, whose old description ("check
        whether it can be refunded") would have overlapped with it.
      </p>
      <div className="w7-tools">
        {data.tool_diff.map((t) => (
          <div key={t.name} className="w7-tool">
            <div className="w7-h">
              <code className="w7-tname">{t.name}</code>
              <span className={`w7-badge ${t.status}`}>{t.status}</span>
            </div>
            {t.before && (
              <p className="w7-desc old"><span className="ev-k">before</span>{t.before.description}</p>
            )}
            <p className="w7-desc new"><span className="ev-k">now</span>{t.after.description}</p>
            <pre className="w7-diff">
              {t.diff.map((l, i) => (
                <div key={i} className={l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : ''}>{l}</div>
              ))}
            </pre>
          </div>
        ))}
      </div>
      <h3>Enums</h3>
      <div className="w7-enums">
        {Object.entries(data.enums).map(([k, vs]) => (
          <div key={k}><code>{k}</code>{vs.map((v) => <span key={v} className="w7-chip">{v}</span>)}</div>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------- react tab */

function ReActTab({ ticketIds }) {
  const [tid, setTid] = useState('TCK-7009')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const runReAct = async (targetId) => {
    setBusy(true); setErr(null)
    try {
      const data = await api('/api/week7/react', { ticket_id: targetId || tid })
      setRes(data)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  useEffect(() => { runReAct('TCK-7009') }, [])

  return (
    <section className="w7-card">
      <h3>ReAct Loop (Reason + Act) — Explicit Audit Trail</h3>
      <p className="w7-foot">
        Before taking an action, the agent writes an explicit <b>Thought</b>. After executing the tool call (<b>Action</b>),
        it receives an <b>Observation</b>. This reasoning loop provides complete transparency.
      </p>
      <div className="w7-form">
        <label>Ticket:
          <select value={tid} onChange={(e) => { setTid(e.target.value); runReAct(e.target.value) }}>
            {(ticketIds || ['TCK-7001', 'TCK-7009']).map(t => <option key={t}>{t}</option>)}
          </select>
        </label>
        <button type="button" className="w7-btn" onClick={() => runReAct()} disabled={busy}>
          {busy ? 'Running ReAct loop…' : 'Re-run ReAct Trace'}
        </button>
      </div>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {res && (
        <div style={{ marginTop: '16px' }}>
          <h4>ReAct Trace for <code>{res.ticket_id}</code> ({res.trace?.length || 0} steps)</h4>
          <ol className="w7-steps">
            {res.trace?.map((step, i) => (
              <li key={i} className="tool" style={{ marginBottom: '14px', background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '8px', border: '1px solid var(--bd)' }}>
                <div style={{ color: 'var(--accent-soft)', fontWeight: 'bold', marginBottom: '4px' }}>
                  Step {step.step}: Thought
                </div>
                <div style={{ fontStyle: 'italic', marginBottom: '8px', background: 'rgba(255,255,255,0.05)', padding: '8px', borderRadius: '4px' }}>
                  "{step.thought}"
                </div>
                {step.action && (
                  <div style={{ marginBottom: '6px' }}>
                    <span className="w7-chip" style={{ background: 'var(--accent)', color: '#000', fontWeight: 'bold', marginRight: '6px' }}>Action</span>
                    <code>{step.action.name}</code>({JSON.stringify(step.action.input)})
                  </div>
                )}
                {step.observation && (
                  <div style={{ marginTop: '6px' }}>
                    <span className="w7-chip" style={{ background: '#22c55e', color: '#000', fontWeight: 'bold', marginRight: '6px' }}>Observation</span>
                    <code style={{ fontSize: '11px' }}>{JSON.stringify(step.observation)}</code>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {res.output && (
            <div className="w7-term ok" style={{ marginTop: '12px' }}>
              <b>Final Decision:</b> {res.output.decision} (Refund order: {String(res.output.refund_order_id)}, Escalate: {String(res.output.escalate)})
              <pre className="w7-reply">{res.output.reply}</pre>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------ memory tab */

function MemoryTab() {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const runMemory = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await api('/api/week7/memory')
      setData(r)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  useEffect(() => { runMemory() }, [])

  return (
    <section className="w7-card">
      <div className="w7-h">
        <h3>Agent Memory: Short-Term, Rolling Summary vs Vector Memory</h3>
        <span className="spacer" />
        <button type="button" className="w7-btn" onClick={runMemory} disabled={busy}>
          {busy ? 'Evaluating memory…' : 'Re-evaluate Memory'}
        </button>
      </div>
      <p className="w7-foot">
        Evaluates context retention across 3 long threads.
        <b>Rolling summarisation is lossy:</b> it drops Director waiver code <code>MGR-AUTH-8821</code> on TCK-LONG-03.
        <b>Vector memory</b> embeds turns with <code>fastembed bge-small</code> and recalls exact texts on demand.
      </p>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {data && (
        <div className="w7-scroll" style={{ marginTop: '16px' }}>
          <table className="w7-tickets">
            <thead>
              <tr>
                <th>Thread</th>
                <th>Customer</th>
                <th>Full History</th>
                <th>Window + Summary</th>
                <th>Window + Summary + Vector</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.results || {}).map(([tid, item]) => {
                const fh = item.modes['full history']
                const ws = item.modes['window + summary']
                const wsv = item.modes['window + summary + vector']
                return (
                  <tr key={tid}>
                    <td className="mono"><b>{tid}</b><br/><span className="mut">{item.title}</span></td>
                    <td className="mono">{item.customer_id}</td>
                    <td>
                      <Pass ok={fh?.passed} /> <span className="mut">({num(fh?.tokens)} tok)</span>
                    </td>
                    <td>
                      <Pass ok={ws?.passed} /> <span className="mut">({num(ws?.tokens)} tok)</span>
                      {!ws?.passed && <div style={{ color: '#ef4444', fontSize: '11px', marginTop: '2px' }}>⚠️ Lossy summary dropped MGR-AUTH-8821</div>}
                    </td>
                    <td>
                      <Pass ok={wsv?.passed} /> <span className="mut">({num(wsv?.tokens)} tok)</span>
                      {wsv?.waiver_recalled && <div style={{ color: '#22c55e', fontSize: '11px', marginTop: '2px' }}>✅ Vector recalled waiver code</div>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* -------------------------------------------------------------- mem0 tab */

function Mem0Tab() {
  const [user, setUser] = useState('CUST-903')
  const [query, setQuery] = useState('manager authorization or waiver code approving the refund')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const queryMem0 = async () => {
    setBusy(true); setErr(null)
    try {
      const data = await api('/api/week7/mem0', { user_id: user, query })
      setRes(data)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  useEffect(() => { queryMem0() }, [])

  return (
    <section className="w7-card">
      <h3>mem0 Library Integration</h3>
      <p className="w7-foot">
        <code>mem0</code> is a production-grade long-term memory framework: local fastembed <code>bge-small-en-v1.5</code>, embedded Qdrant vector store on disk, SQLite history DB, and automatic user-id scoping.
      </p>
      <div className="w7-form" style={{ gap: '12px' }}>
        <label>User ID:
          <select value={user} onChange={(e) => setUser(e.target.value)}>
            <option value="CUST-901">CUST-901 (Standard)</option>
            <option value="CUST-902">CUST-902 (VIP)</option>
            <option value="CUST-903">CUST-903 (Priority - holds waiver)</option>
          </select>
        </label>
        <label style={{ flex: 1 }}>Query:
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: '100%' }} />
        </label>
        <button type="button" className="w7-btn" onClick={queryMem0} disabled={busy}>
          {busy ? 'Querying mem0…' : 'Search mem0 Memory'}
        </button>
      </div>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {res && (
        <div style={{ marginTop: '16px' }}>
          <h4>Top Search Hits for User <code>{res.user_id}</code></h4>
          {res.results?.length === 0 ? (
            <p className="mut">No matching memories found for this user.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {res.results?.map((r, i) => (
                <div key={i} style={{ padding: '12px', background: 'rgba(255,255,255,0.03)', borderLeft: '3px solid var(--accent)', borderRadius: '4px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--mut)', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Memory ID: {r.id || i}</span>
                    <span>Score: {r.score ? r.score.toFixed(3) : '—'}</span>
                  </div>
                  <div style={{ fontSize: '13px', marginTop: '4px', fontWeight: '500' }}>
                    {r.memory || r.text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------- graph tab */

function GraphTab({ race }) {
  const [tid, setTid] = useState('TCK-7009')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const runGraph = async (targetId) => {
    setBusy(true); setErr(null)
    try {
      const r = await api('/api/week7/graph', { ticket_id: targetId || tid })
      setData(r)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  useEffect(() => { runGraph('TCK-7009') }, [])

  return (
    <section className="w7-card">
      <h3>LangChain & LangGraph Framework Implementation</h3>
      <p className="w7-foot">
        LangGraph models the agent as a cyclic graph (<code>START -&gt; model &lt;--&gt; tools -&gt; END</code>) and the workflow as a DAG (<code>START -&gt; ticket -&gt; order -&gt; policy -&gt; draft -&gt; END</code>).
        Includes built-in checkpointers for short-term thread memory and state recovery.
      </p>
      <div className="w7-form">
        <label>Select Ticket:
          <select value={tid} onChange={(e) => { setTid(e.target.value); runGraph(e.target.value) }}>
            {(race?.ticket_ids || ['TCK-7001', 'TCK-7009']).map(t => <option key={t}>{t}</option>)}
          </select>
        </label>
        <button type="button" className="w7-btn" onClick={() => runGraph()} disabled={busy}>
          {busy ? 'Running LangGraph…' : 'Run LangGraph Agent'}
        </button>
      </div>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {data && (
        <div style={{ marginTop: '16px' }}>
          <div className="w7-runs">
            <div className="w7-run pass">
              <b>LangGraph Agent</b>
              <p className="mut">LLM Calls: {data.agent.llm_calls} · Path: {data.agent.path.join(' ➔ ')}</p>
              <pre className="w7-reply">{JSON.stringify(data.agent.output, null, 2)}</pre>
            </div>
            <div className="w7-run pass">
              <b>LangGraph Fixed Workflow</b>
              <p className="mut">LLM Calls: {data.workflow.llm_calls} · Path: {data.workflow.path.join(' ➔ ')}</p>
              <pre className="w7-reply">{JSON.stringify(data.workflow.output, null, 2)}</pre>
            </div>
          </div>

          <div style={{ marginTop: '20px' }}>
            <h4>State Checkpoints Saved for {data.ticket_id} ({data.checkpoints?.length || 0} snapshots)</h4>
            <table className="w7-tickets">
              <thead>
                <tr><th>Step</th><th>Next Node</th><th>Last Message</th></tr>
              </thead>
              <tbody>
                {data.checkpoints?.map((c, i) => (
                  <tr key={i}>
                    <td>Step {c.step}</td>
                    <td><code>{c.next.join(', ')}</code></td>
                    <td className="mut">{c.last_message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.mermaid && (
            <div style={{ marginTop: '20px' }}>
              <h4>Mermaid Graph Specs</h4>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div>
                  <b>Agent Graph (Cyclic)</b>
                  <pre className="w7-code" style={{ fontSize: '11px' }}>{data.mermaid.agent}</pre>
                </div>
                <div>
                  <b>Workflow Graph (DAG)</b>
                  <pre className="w7-code" style={{ fontSize: '11px' }}>{data.mermaid.workflow}</pre>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/* -------------------------------------------------------------- code tab */

const CODE_NOTES = {
  'agent.py': 'The agent: model-driven tool loop and the four budgets. One command: .venv/bin/python week7/agent.py',
  'react.py': 'ReAct: Reason + Act loop printing Thought -> Action -> Observation step by step.',
  'workflow.py': 'The fixed workflow: four hard-coded steps, no loop. One command: .venv/bin/python week7/workflow.py',
  'tools.py': 'The three tools and their definitions, before and after.',
  'model.py': 'The shared offline model: what is real (decisions, wall-clock) and what is estimated (tokens).',
  'store.py': 'The 10 tickets, the orders, and the answer key neither system can read.',
  'bonus.py': 'Bonus challenge: sliding window + summarisation over 30-turn threads, persistent tier store, and failure analysis.',
  'memory.py': 'Short vs long-term memory: why rolling summary needs a vector memory behind it.',
  'mem0_demo.py': 'mem0 library integration: packaged fastembed, vector store, SQLite history and user scoping.',
  'graph.py': 'LangGraph: agent loop as a cyclic graph vs workflow as a linear DAG, with state checkpoints.',
}

function CodeTab({ data }) {
  const [file, setFile] = useState('agent.py')
  return (
    <section className="w7-card">
      <div className="ev-filters">
        {Object.keys(data.source).map((f) => (
          <button key={f} type="button" data-on={file === f ? 1 : 0} onClick={() => setFile(f)}>{f}</button>
        ))}
      </div>
      <p className="w7-foot">{CODE_NOTES[file]}</p>
      <pre className="w7-code">{data.source[file]}</pre>
    </section>
  )
}

/* ------------------------------------------------------------- bonus tab */

function BonusTab({ data, onRefresh }) {
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState(null)
  const [openThread, setOpenThread] = useState('TCK-LONG-03')
  const bonus = data.bonus

  const rerunBonus = async () => {
    setRunning(true); setErr(null)
    try {
      await api('/api/week7/bonus')
      await onRefresh()
    } catch (e) {
      setErr(e.message)
    } finally {
      setRunning(false)
    }
  }

  if (!bonus) {
    return (
      <section className="w7-card">
        <h3>Bonus Challenge: Memory & 30-Turn Threads</h3>
        <p className="w7-foot">No bonus results found yet.</p>
        <button type="button" className="w7-btn" onClick={rerunBonus} disabled={running}>
          {running ? 'Running 3 long threads…' : 'Run Bonus Challenge'}
        </button>
      </section>
    )
  }

  return (
    <>
      <section className="w7-card">
        <div className="w7-h">
          <h3>Bonus Challenge — Sliding Window, Summarisation & Persistent Memory</h3>
          <span className="spacer" />
          <button type="button" className="w7-btn" onClick={rerunBonus} disabled={running}>
            {running ? 'Running 30-turn threads…' : 'Re-run 3 Long Threads'}
          </button>
        </div>
        <p className="w7-foot">
          Evaluates an agent across <b>30-turn ticket threads</b> with a sliding window (last 6 messages)
          plus rolling summarisation. Persists the customer tier in <code>tier_store.json</code> across full
          process restarts, and identifies the exact detail lost to lossy compression.
        </p>

        <div className="ev-band">
          <div className="ev-stat">
            <span className="ev-k">Persisted fact across restart</span>
            <b>Customer Tier</b>
            <span className="ev-sub2">Saved to disk (tier_store.json)</span>
          </div>
          <div className="ev-stat">
            <span className="ev-k">Context window management</span>
            <b>Sliding + Summary</b>
            <span className="ev-sub2">~70% token reduction per lap</span>
          </div>
          <div className="ev-stat big">
            <span className="ev-k">Ticket broken by summarisation</span>
            <b className="bad">{bonus.broken_ticket || 'None'}</b>
            <span className="ev-sub2">1 of 3 threads failed</span>
          </div>
        </div>

        {bonus.destroyed_detail && (
          <div className="w7-destroyed-box">
            <div className="w7-destroyed-title">
              ⚠️ <b>Detail destroyed by summarisation</b> (Broke ticket <code>{bonus.broken_ticket}</code>):
            </div>
            <div className="w7-destroyed-text">
              {bonus.destroyed_detail}
            </div>
            <p className="w7-destroyed-explanation">
              <b>Why it broke:</b> On Turn 12 of the conversation, the customer provided Director waiver code{' '}
              <code>MGR-AUTH-8821</code> to approve a $240 refund directly without manager escalation. As the thread
              continued for 18 more turns of general billing inquiries, the sliding window pushed Turn 12 into the summariser.
              The lossy summary retained the generic topic ("account and billing inquiries") but compressed out the specific
              exemption code. At Turn 30, the agent fell back to the default SP-001 $100 ceiling and escalated to a manager,
              failing the customer contract.
            </p>
          </div>
        )}
      </section>

      <section className="w7-card">
        <h3>The 3 Long Threads (30 Turns Each)</h3>
        <div className="w7-bonus-threads">
          {Object.entries(bonus.threads).map(([tid, t]) => {
            const w = t.with_window
            const isOpen = openThread === tid
            return (
              <div key={tid} className={`w7-thread-card ${w.passed ? 'pass' : 'fail'}`}>
                <div className="w7-thread-header" onClick={() => setOpenThread(isOpen ? null : tid)}>
                  <div className="w7-thread-title">
                    <span className="mono">{isOpen ? '▾' : '▸'} {tid}</span>
                    <b>{t.title}</b>
                  </div>
                  <Pass ok={w.passed} />
                  <span className="w7-chip">{w.total_turns} turns</span>
                  <span className="w7-chip">Tier: {w.persisted_tier}</span>
                  <span className="mut">{w.token_reduction_pct}% token saving</span>
                </div>

                <div className="w7-thread-meta">
                  <div>
                    <span className="ev-k">Decision</span>
                    <b>{w.output.decision}</b>
                  </div>
                  <div>
                    <span className="ev-k">Escalate</span>
                    <b>{String(w.output.escalate)}</b>
                  </div>
                  <div>
                    <span className="ev-k">Raw vs Windowed Tokens</span>
                    <span>{num(w.raw_tokens_without_window)} tok ➔ <b>{num(w.active_tokens)} tok</b></span>
                  </div>
                  <div>
                    <span className="ev-k">Tier persistence state</span>
                    <span className="mono">{w.tier_source}</span>
                  </div>
                </div>

                {isOpen && (
                  <div className="w7-thread-body">
                    <pre className="w7-reply">{w.output.reply}</pre>
                    {w.detail_destroyed && (
                      <div className="banner bad">
                        <strong>Failure diagnosis:</strong> {w.detail_destroyed} was purged during sliding window compression!
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>
    </>
  )
}

/* ------------------------------------------------------------------ page */

export default function Week7View() {
  // ?tab=budgets#week7 opens a sub-tab directly, for sharing a link to it.
  const [tab, setTab] = useState(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    return TABS.some(([k]) => k === t) ? t : 'race'
  })
  const [data, setData] = useState(null)
  const [runs, setRuns] = useState(null)
  const [err, setErr] = useState(null)
  const [racing, setRacing] = useState(false)

  const load = (d) => {
    setData(d)
    if (d.ok) setRuns({ agent: { ...d.race.runs.agent }, workflow: { ...d.race.runs.workflow } })
  }
  const refresh = () => api('/api/week7').then(load).catch((e) => setErr(e.message))
  useEffect(() => { refresh() }, [])

  const setRun = (system, tid, r) =>
    setRuns((prev) => ({ ...prev, [system]: { ...prev[system], [tid]: r } }))

  const rerace = async () => {
    setRacing(true); setErr(null)
    try { load(await api('/api/week7/race', {})) } catch (e) { setErr(e.message) } finally { setRacing(false) }
  }

  const liveCount = useMemo(() => runs
    ? Object.values(runs).flatMap((s) => Object.values(s)).filter((r) => r.live).length : 0, [runs])

  if (err && !data) {
    return <div className="view"><div className="banner bad"><strong>Week 7 failed to load.</strong><pre>{err}</pre></div></div>
  }
  if (!data) return <div className="view"><p className="ev-note">Loading Week 7…</p></div>
  if (!data.ok) {
    return (
      <div className="view"><div className="empty">
        <h2>No race results yet</h2>
        <p>Run <code>.venv/bin/python week7/race.py</code>, or:</p>
        <button type="button" className="w7-btn" onClick={rerace} disabled={racing}>
          {racing ? 'racing…' : 'Run the race now'}
        </button>
      </div></div>
    )
  }

  return (
    <div className="view ev w7">
      <header className="ev-head">
        <h2>Does it need to be an agent? — Week 7</h2>
        {/* <p className="ev-sub">
          The Week 6 ticket-reply task, built twice with the same three tools, the
          same model and the same output contract: once as a model-driven agent
          loop, once as four hard-coded steps. Raced over the same 10 refund-chase
          tickets. The engine is offline (no ANTHROPIC_API_KEY): decisions and
          wall-clock are real, tokens are estimated.
        </p> */}
      </header>

      <nav className="ev-filters w7-tabs">
        {TABS.map(([k, label]) => (
          <button key={k} type="button" data-on={tab === k ? 1 : 0} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>

      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {liveCount > 0 && tab === 'race' && (
        <p className="ev-note">
          {liveCount} row{liveCount === 1 ? '' : 's'} replaced by a live re-run. The four
          headline numbers stay those of the recorded race until it is re-run.
        </p>
      )}

      {tab === 'race' && <RaceTab race={data.race} runs={runs} setRun={setRun}
        onRerace={rerace} racing={racing} />}
      {tab === 'react' && <ReActTab ticketIds={data.race?.ticket_ids} />}
      {tab === 'branching' && <BranchingTab race={data.race} />}
      {tab === 'budgets' && <BudgetsTab data={data} onSaved={refresh} />}
      {tab === 'tool' && <ToolTab data={data} />}
      {tab === 'memory' && <MemoryTab />}
      {tab === 'mem0' && <Mem0Tab />}
      {tab === 'graph' && <GraphTab race={data.race} />}
      {tab === 'bonus' && <BonusTab data={data} onRefresh={refresh} />}
      {tab === 'code' && <CodeTab data={data} />}
    </div>
  )
}
