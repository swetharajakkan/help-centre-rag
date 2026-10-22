import React, { useEffect, useState } from 'react'

/**
 * Agent race (admin): the triage squad vs the single agent on the same ten
 * tickets. Everything here is read from week10/race.json, which
 * week10/race.py writes, so the page and the markdown deliverables cannot
 * drift apart.
 */

const TABS = [
  ['race', 'Race'],
  ['handoffs', 'Hand-offs'],
  ['failure', 'Worker failure'],
  ['verdict', 'Verdict'],
  ['fanout', 'Race 2: many issues'],
  ['a2a', 'A2A'],
  ['card', 'Agent card'],
]

const usd = (x) => `$${Number(x).toFixed(4)}`
const sec = (x) => `${Number(x).toFixed(2)} s`
const pf = (ok) => <span className={`pf ${ok ? 'ok' : 'bad'}`}>{ok ? 'PASS' : 'FAIL'}</span>

function RaceTab({ d }) {
  const S = d.summary.single
  const M = d.summary.squad
  const P = d.summary.single_par || S
  // [label, single, squad, raw single, raw squad, higher is better]
  const rows = [
    ['Pass rate', `${S.passed}/${S.n}`, `${P.passed}/${P.n}`, `${M.passed}/${M.n}`],
    ['Latency p50', sec(S.p50_s), sec(P.p50_s), sec(M.p50_s)],
    ['Latency p99', sec(S.p99_s), sec(P.p99_s), sec(M.p99_s)],
    ['Total tokens', S.total_tokens.toLocaleString(), P.total_tokens.toLocaleString(), M.total_tokens.toLocaleString()],
    ['Cost per ticket', usd(S.cost_per_ticket_usd), usd(P.cost_per_ticket_usd), usd(M.cost_per_ticket_usd)],
  ]
  return (
    <>
      <div className="w10-tiles">
        <div className="w10-tile"><b>{d.multiplier}x</b><span>tokens, squad vs single</span></div>
        <div className="w10-tile"><b>{S.passed} vs {M.passed}</b><span>passed (single vs squad)</span></div>
        <div className="w10-tile"><b>{sec(M.p99_s)}</b><span>squad p99</span></div>
      </div>
      <div className="w10-card">
        <table className="w10-table">
          <thead><tr><th>Metric</th><th className="num">Single agent</th>
            <th className="num">Single + parallel</th><th className="num">Triage squad</th></tr></thead>
          <tbody>
            {rows.map(([k, a, p, b]) => (
              <tr key={k}><td>{k}</td><td className="num">{a}</td><td className="num">{p}</td>
                <td className="num">{b}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="w10-h">Per ticket</h3>
      <div className="w10-card">
        <table>
          <thead>
            <tr><th>Case</th><th>Question</th><th>Single</th><th>Single + parallel</th><th>Squad</th>
              <th className="num">Single tokens</th><th className="num">Parallel tokens</th>
              <th className="num">Squad tokens</th></tr>
          </thead>
          <tbody>
            {d.runs.single.map((s, i) => {
              const m = d.runs.squad[i]
              const p = (d.runs.single_par || d.runs.single)[i]
              return (
                <tr key={s.case_id}>
                  <td>{s.case_id}</td>
                  <td className="w10-q">{s.question}</td>
                  <td>{pf(s.grade.passed)}</td>
                  <td>{pf(p.grade.passed)}</td>
                  <td>{pf(m.grade.passed)}</td>
                  <td className="num">{s.tokens.toLocaleString()}</td>
                  <td className="num">{p.tokens.toLocaleString()}</td>
                  <td className="num">{m.tokens.toLocaleString()}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function HandoffsTab({ d }) {
  const [arm, setArm] = useState('squad')
  const top = d.handoff_shares[0]
  return (
    <>
      <p className="w10-line">
        <b>{d.multiplier}x</b> — largest share: <b>{top.handoff}</b>, {Math.round(top.share * 100)}% of squad tokens
      </p>
      <div className="w10-bars">
        {d.handoff_shares.map((h) => (
          <div className="w10-bar" key={h.handoff}>
            <span className="w10-bar-label">{h.handoff}</span>
            <span className="w10-track"><span className="w10-fill" style={{ width: `${h.share * 100}%` }} /></span>
            <span className="w10-bar-n">{h.tokens.toLocaleString()} · {Math.round(h.share * 100)}%</span>
          </div>
        ))}
      </div>
      <div className="seg w10-seg" role="tablist">
        {[['single', 'Single agent'], ['single_par', 'Single + parallel'], ['squad', 'Triage squad']]
          .filter(([k]) => d.runs[k]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={arm === k} data-on={arm === k ? 1 : 0}
            onClick={() => setArm(k)}>{label}</button>
        ))}
      </div>
      <div className="w10-card">
        <table>
          <thead>
            <tr><th>Case</th><th>#</th><th>From → To</th><th>Step</th>
              <th className="num">In</th><th className="num">Out</th><th className="num">Total</th></tr>
          </thead>
          <tbody>
            {d.runs[arm].flatMap((r) => r.handoffs.map((h) => (
              <tr key={`${r.case_id}-${h.seq}`}>
                <td>{h.case}</td><td>{h.seq}</td><td>{h.from} → {h.to}</td><td>{h.label}</td>
                <td className="num">{h.tokens_in.toLocaleString()}</td>
                <td className="num">{h.tokens_out.toLocaleString()}</td>
                <td className="num">{h.tokens.toLocaleString()}</td>
              </tr>
            )))}
          </tbody>
        </table>
      </div>
    </>
  )
}

const BEHAVIOUR = {
  retried: 'Retried',
  degraded: 'Degraded — no retry, error hidden from the customer',
  lied: 'Lied — answered as if the worker had replied',
}

function FailureTab({ f }) {
  return (
    <>
      <div className="w10-tiles">
        <div className="w10-tile"><b>{f.case_id}</b><span>policy worker → 500</span></div>
        <div className="w10-tile"><b>{f.retried ? 'yes' : 'no'}</b><span>retried</span></div>
        <div className="w10-tile"><b>{f.grade.passed ? 'PASS' : 'FAIL'}</b><span>judge on failed run</span></div>
      </div>
      <p className="w10-line"><b>{BEHAVIOUR[f.behaviour]}</b></p>
      <p className="w10-q">{f.question}</p>
      <p className="note bad"><code>{f.error}</code></p>
      <div className="cols">
        <div><h3>Worker down</h3><pre className="reply-box">{f.reply}</pre></div>
        <div><h3>Worker healthy</h3><pre className="reply-box">{f.clean_reply}</pre></div>
      </div>
    </>
  )
}

function VerdictTab({ lines }) {
  return (
    <>
      {lines.filter((l) => l.startsWith('VERDICT')).map((l) => {
        const kill = l.includes('KILL')
        return (
          <div key={l} className={`w10-banner ${kill ? 'kill' : 'keep'}`}>
            <span className="w10-badge">{kill ? 'KILL' : 'KEEP'}</span>
            <span>{l.replace(/^VERDICT: (KILL|KEEP) — /, '')}</span>
          </div>
        )
      })}
      <div className="w10-card">
        <ul className="w10-verdict">
          {lines.filter((l) => !l.startsWith('VERDICT')).map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </div>
    </>
  )
}

const ARM2 = {
  single: 'Single agent (one tool call per turn)',
  single_par: 'Single agent + parallel tool calls',
  squad: 'Triage squad (concurrent workers)',
}

const ARM_HOW = {
  single: 'One agent, all tools, one growing history. One tool call per turn: search code 1, then code 2, … then the policy, then the reply. K codes = K + 2 model calls.',
  single_par: 'The same single agent, but it asks for every search in ONE turn (parallel tool calls). Always 3 model calls, but one history holds every issue.',
  squad: 'Orchestrator plans, triage worker reads the ticket, then one policy worker PER CODE runs at the same time, each seeing only its own code. Orchestrator writes the reply.',
}

/** One ticket through race 2's three arms: replies, hand-offs, pass/fail. */
export function FanoutArms({ d }) {
  const shown = ['single', 'single_par', 'squad'].filter((k) => d.arms && d.arms[k])
  return (
    <>
      <p className="w10-line">{d.n_codes} independent issue{d.n_codes === 1 ? '' : 's'} · budget per agent run:
        {' '}{d.budget.max_calls} model calls, {d.budget.max_tokens.toLocaleString()} tokens (Week 7)</p>
      {d.route && (
        <p className="w10-line">Auto routing would pick <b>{ARM2[d.route.arm] || 'the Week 9 support crew'}</b>: {d.route.reason}.</p>
      )}
      {!shown.length && <p className="note">No arm to run for this question.</p>}
      <div className="w11-three">
        {shown.map((k) => {
          const a = d.arms[k]
          return (
            <div key={k} className="w10-card w12-arm">
              <h3>{ARM2[k]} {pf(a.passed)}</h3>
              <p className="w10-q">{ARM_HOW[k]}</p>
              {a.terminated && <div className="banner bad"><strong>Stopped by budget.</strong> {a.terminated}</div>}
              <div className="w12-stats">
                <span><b>{a.calls}</b> model calls</span>
                <span><b>{a.agents}</b> agent{a.agents === 1 ? '' : 's'}</span>
                <span><b>{a.max_agent_tokens.toLocaleString()}</b> biggest context</span>
                <span><b>{a.tokens.toLocaleString()}</b> tokens total</span>
                <span><b>{usd(a.cost_usd)}</b></span>
                <span><b>{sec(a.latency_s)}</b></span>
              </div>
              <pre className="reply-box">{a.reply}</pre>
              <p className="w10-q">Judge: {a.verdict} — {a.why}{a.assertions_failed && a.assertions_failed.length ? ` · assertions failed: ${a.assertions_failed.join(', ')}` : ''}</p>
              <details className="trace">
                <summary>{a.handoffs.length} hand-offs</summary>
                <ol className="steps">
                  {a.handoffs.map((h, i) => (
                    <li key={i}><b>{h.from} → {h.to}</b> · {h.label} · {h.tokens.toLocaleString()} tokens</li>
                  ))}
                </ol>
              </details>
            </div>
          )
        })}
      </div>
    </>
  )
}

export function ArmPicker({ arms, setArms, auto, setAuto }) {
  const flip = (a) => setArms(arms.includes(a) ? arms.filter((x) => x !== a) : [...arms, a])
  return (
    <span className="w12-arms">
      <span className="w10-q">run on</span>
      {['single', 'single_par', 'squad'].map((a) => (
        <label key={a}><input type="checkbox" checked={!auto && arms.includes(a)} disabled={auto}
          onChange={() => flip(a)} /> {{ single: 'Single', single_par: 'Single + parallel', squad: 'Squad' }[a]}</label>
      ))}
      {setAuto && <label><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto (as users get it)</label>}
    </span>
  )
}

function FanoutLive({ f }) {
  const [pick, setPick] = useState(f.cases[0])
  const [k, setK] = useState(7)
  const [arms, setArms] = useState(['single', 'single_par', 'squad'])
  const [busy, setBusy] = useState(false)
  const [r, setR] = useState(null)
  const [err, setErr] = useState(null)
  const run = (body) => {
    setBusy(true); setErr(null)
    fetch('/api/w10/fanout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then((x) => x.json().then((j) => { if (!x.ok) throw new Error(j.detail || `HTTP ${x.status}`); return j }))
      .then(setR).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }
  return (
    <>
      <h3 className="w10-h">Run it live: pick a ticket or a number of issues (K), and which arms</h3>
      <div className="w10-card w11-filters">
        <label>ticket <select value={pick} onChange={(e) => setPick(e.target.value)}>
          {f.cases.map((c) => <option key={c} value={c}>{c} — {f.questions[c].slice(0, 70)}…</option>)}
        </select></label>
        <button className="send" disabled={busy || !arms.length} onClick={() => run({ case_id: pick, arms })}>Run {pick}</button>
        <span className="w10-q">or</span>
        <label>Number of issues (K) <select value={k} onChange={(e) => setK(Number(e.target.value))}>
          {[2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => <option key={n} value={n}>{n}</option>)}
        </select></label>
        <button className="send" disabled={busy || !arms.length} onClick={() => run({ k, arms })}>Run K = {k}</button>
        <ArmPicker arms={arms} setArms={setArms} />
        {busy && <span><i className="led-dot" /> running all three arms…</span>}
      </div>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {r && (
        <>
          <p className="w10-line"><b>{r.case_id}</b>: {r.question}</p>
          <FanoutArms d={r} />
        </>
      )}
    </>
  )
}

/** Race 2: tickets with several independent issues, the squad's home ground. */
function FanoutTab({ f }) {
  const [open, setOpen] = useState(null)
  if (!f) return <p className="note">Run <code>week10/fanout.py</code> first.</p>
  const ks = [...new Set(f.sweep.map((x) => x.k))]
  const at = (k, arm) => f.sweep.find((x) => x.k === k && x.arm === arm)
  const firstFail = ks.find((k) => !at(k, 'single').passed)
  const top = ks[ks.length - 1]
  return (
    <>
      <FanoutLive f={f} />
      <div className="w10-banner keep">
        <span className="w10-badge">SQUAD</span>
        <span>Use the triage squad when a ticket has several independent issues that each need
          their own context. The single agent as built fails from {firstFail} issues (Week 7
          budget: {f.budgets.max_calls} calls); the squad passes up to {top}, and no squad agent
          holds more than {at(top, 'squad').max_agent_tokens.toLocaleString()} tokens.</span>
      </div>
      <div className="w10-tiles">
        <div className="w10-tile"><b>K = {firstFail}</b><span>single agent fails (budget)</span></div>
        <div className="w10-tile"><b>{at(top, 'squad').max_agent_tokens.toLocaleString()}</b>
          <span>largest squad agent at K = {top}</span></div>
        <div className="w10-tile"><b>{at(top, 'single_par').max_agent_tokens.toLocaleString()}</b>
          <span>single + parallel tools at K = {top}</span></div>
      </div>
      <h3 className="w10-h">Four multi-issue tickets (3-6 codes), saved run</h3>
      <div className="w10-card">
        <table>
          <thead><tr><th>Arm</th><th>Pass</th><th className="num">Tokens</th>
            <th className="num">Cost / ticket</th><th className="num">Mean latency</th></tr></thead>
          <tbody>
            {Object.entries(f.summary).map(([arm, s]) => (
              <tr key={arm}><td>{ARM2[arm]}</td><td>{s.passed}/{s.n}</td>
                <td className="num">{s.tokens.toLocaleString()}</td>
                <td className="num">{usd(s.cost_per_ticket_usd)}</td>
                <td className="num">{sec(s.mean_latency_s)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="w10-h">Size sweep: one ticket naming K independent codes</h3>
      <div className="w10-card">
        <table>
          <thead><tr><th>K</th><th>Single</th><th>Single + parallel</th><th>Squad</th>
            <th className="num">Single context</th><th className="num">Parallel context</th>
            <th className="num">Largest squad agent</th></tr></thead>
          <tbody>
            {ks.map((k) => {
              const [a, b, c] = ['single', 'single_par', 'squad'].map((x) => at(k, x))
              const cell = (x) => <>{pf(x.passed)} <span className="w10-q">{sec(x.latency_s)}
                {x.terminated ? ' · budget' : ''}</span></>
              return (
                <tr key={k}><td>{k}</td><td>{cell(a)}</td><td>{cell(b)}</td><td>{cell(c)}</td>
                  <td className="num">{a.max_agent_tokens.toLocaleString()}</td>
                  <td className="num">{b.max_agent_tokens.toLocaleString()}</td>
                  <td className="num">{c.max_agent_tokens.toLocaleString()}</td></tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <h3 className="w10-h">The tickets and the replies</h3>
      <div className="w10-card">
        <table>
          <thead><tr><th>Case</th><th>Question</th><th>Single</th><th>Parallel</th><th>Squad</th></tr></thead>
          <tbody>
            {f.cases.map((cid) => {
              const r = (arm) => f.rows.find((x) => x.case_id === cid && x.arm === arm)
              return (
                <React.Fragment key={cid}>
                  <tr onClick={() => setOpen(open === cid ? null : cid)} style={{ cursor: 'pointer' }}>
                    <td>{cid}</td><td className="w10-q">{f.questions[cid]}</td>
                    <td>{pf(r('single').grade.passed)}</td><td>{pf(r('single_par').grade.passed)}</td>
                    <td>{pf(r('squad').grade.passed)}</td>
                  </tr>
                  {open === cid && (
                    <tr><td colSpan={5}><pre className="reply-box">{r('squad').reply}</pre></td></tr>
                  )}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="w10-card">
        <ul className="w10-verdict">
          <li>Declared before it ran, and kept separate from race 1: adding cases to race 1 after
            seeing its result would be the bias its verdict warns about.</li>
          <li>Honest caveat: a single agent with parallel tool calls also passes every size here and
            is cheaper ({usd(f.summary.single_par.cost_per_ticket_usd)} vs {usd(f.summary.squad.cost_per_ticket_usd)} per
            ticket). The squad's lasting edge is context isolation, not speed.</li>
          <li className="v">Routing rule: single agent by default; triage squad when triage counts more
            independent issues than the single agent's budget allows, or when each issue's context is large.</li>
        </ul>
      </div>
    </>
  )
}

function CardTab({ card }) {
  if (!card) return <p className="note">No agent card.</p>
  return (
    <>
      <div className="w10-tiles">
        <div className="w10-tile"><b>{card.skills.length}</b><span>skills</span></div>
        <div className="w10-tile"><b>{card.defaultInputModes.join(', ')}</b><span>input</span></div>
        <div className="w10-tile"><b>{Object.keys(card.securitySchemes).join(', ')}</b><span>auth</span></div>
      </div>
      <div className="w10-card">
        <table>
          <thead><tr><th>Skill</th><th>Description</th></tr></thead>
          <tbody>
            {card.skills.map((s) => <tr key={s.id}><td>{s.name}</td><td>{s.description}</td></tr>)}
          </tbody>
        </table>
      </div>
      <p className="w10-line">Failed case → <b>input-required</b> (ticket owner decides), worker task → <b>failed</b>.</p>
    </>
  )
}

function Timeline({ title, transitions }) {
  return (
    <div className="w10-tl">
      <span className="w10-tl-title">{title}</span>
      <div className="w10-tl-row">
        {transitions.map((t, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="w10-arrow">→</span>}
            <span className={`w10-state s-${t.state}`} title={t.note || ''}>{t.state}</span>
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

const DECISIONS = [['retry', 'Retry'], ['billing_review', 'Billing Review'], ['manual', 'Reply by hand']]

function A2ATab({ cases }) {
  const [caseId, setCaseId] = useState(cases[0])
  const [inject, setInject] = useState(true)
  const [busy, setBusy] = useState(false)
  const [r, setR] = useState(null)
  const [err, setErr] = useState(null)
  const post = async (url, body) => {
    setBusy(true); setErr(null)
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) })
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`)
      setR(d)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const t = r?.task
  return (
    <>
      <div className="w10-controls">
        <select className="picker" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
          {cases.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <div className="seg" role="radiogroup">
          {[[true, 'Worker 500'], [false, 'Worker healthy']].map(([v, label]) => (
            <button key={label} role="radio" aria-checked={inject === v} data-on={inject === v ? 1 : 0}
              onClick={() => setInject(v)}>{label}</button>
          ))}
        </div>
        <button className="send" disabled={busy}
          onClick={() => post('/api/w10/a2a/run', { case_id: caseId, inject_500: inject })}>
          {busy ? 'Running…' : 'Run'}
        </button>
      </div>
      {err && <p className="note bad">{err}</p>}
      {t && (
        <div className="w10-card w10-pad">
          <Timeline title="Ticket task" transitions={t.transitions} />
          {r.worker_tasks.map((w, i) => (
            <Timeline key={w.id} title={`Worker task ${i + 1}`} transitions={w.transitions} />
          ))}
        </div>
      )}
      {t?.state === 'input-required' && (
        <div className="w10-banner kill">
          <span className="w10-badge">WAITING</span>
          <span className="w10-ask">{t.question_for_owner}</span>
          <span className="w10-actions">
            {DECISIONS.map(([k, label]) => (
              <button key={k} className="ghost" disabled={busy}
                onClick={() => post('/api/w10/a2a/resume', { task_id: t.id, decision: k })}>{label}</button>
            ))}
          </span>
        </div>
      )}
      {t?.reply && <pre className="reply-box">{t.reply}</pre>}
      {t?.state === 'completed' && !t.reply && (
        <div className="w10-banner keep"><span className="w10-badge">DONE</span>
          <span>{t.transitions[t.transitions.length - 1].note}</span></div>
      )}
    </>
  )
}

export default function Week10View() {
  const [tab, setTab] = useState('race')
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    fetch('/api/week10')
      .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`); return j }))
      .then(setD).catch((e) => setErr(e.message))
  }, [])

  return (
    <div className="view w10">
      <div className="subbar">
        <div className="seg" role="tablist">
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} data-on={tab === k ? 1 : 0}
              onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>
      {err && <div className="banner bad"><strong>Could not load.</strong><pre>{err}</pre></div>}
      {!d && !err && <div className="stage"><i className="led-dot" />loading…</div>}
      {d && (
        <div className="w10-body">
          <header className="w10-hero">
            <h2>Agent race</h2>
            <p>Single agent vs Triage squad · {d.cases.length} tickets</p>
          </header>
          {tab === 'race' && <RaceTab d={d} />}
          {tab === 'handoffs' && <HandoffsTab d={d} />}
          {tab === 'failure' && <FailureTab f={d.failure} />}
          {tab === 'verdict' && <VerdictTab lines={d.verdict} />}
          {tab === 'fanout' && <FanoutTab f={d.fanout} />}
          {tab === 'card' && <CardTab card={d.agent_card} />}
          {tab === 'a2a' && <A2ATab cases={d.cases} />}
        </div>
      )}
    </div>
  )
}
