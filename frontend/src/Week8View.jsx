import React, { useEffect, useMemo, useState } from 'react'

/**
 * Week 8: agent failure modes & trajectory evals.
 *
 * Everything comes from /api/week8, which reads week8/trajectory_results.json
 * and week8/injection_results.json as the CLI wrote them. Every trace on this
 * page is fetched from /api/week8/run, which re-runs the SAME (ticket, seed,
 * mitigation) through the same code -- runs are deterministic, so the trace
 * shown is the run the eval scored.
 */

const TABS = [
  ['overview', 'Overview'],
  ['paths', '1 · Expected Sequences'],
  ['metrics', '2 · Trajectory Metrics'],
  ['gap', '3 · Outcome vs Trajectory Gap'],
  ['modes', 'Failure-Mode Zoo'],
  ['mitigation', '4 · One Mitigation'],
  ['regression', '5 · Regression Check'],
  ['injection', '6. Injection & Least Privilege'],
  ['owasp', '7. OWASP LLM Top 10'],
  // ['demo', 'Demo Script'],
  // ['writeup', 'Write-up'],
  // ['code', 'Source Code'],
]

// Validated categorical pair on the app's dark surface (dataviz validator):
// BEFORE = blue, AFTER = orange. Used for chart marks only, never for text.
const C_BEFORE = '#3987e5'
const C_AFTER = '#d95926'

const pct = (x, d = 1) => (x == null ? '—' : `${(x * 100).toFixed(d)}%`)
const usd = (x, d = 4) => (x == null ? '—' : `$${Number(x).toFixed(d)}`)
const num = (x) => (x == null ? '—' : Math.round(Number(x)).toLocaleString())
const pts = (x) => `${x >= 0 ? '+' : '−'}${Math.abs(x * 100).toFixed(1)} pts`
const signed = (d, f) => `${d >= 0 ? '+' : '−'}${f(Math.abs(d))}`
const short = (t) => t.replace('lookup_refund_policy', 'policy').replace('search_tickets', 'search')

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

function Seg({ options, value, onChange }) {
  return (
    <span className="ev-filters w8-seg">
      {options.map(([v, label]) => (
        <button key={String(v)} type="button" data-on={value === v ? 1 : 0}
          onClick={() => onChange(v)}>{label}</button>
      ))}
    </span>
  )
}

function PF({ ok, label }) {
  return <span className={`w7-pf ${ok ? 'ok' : 'bad'}`}>{label ? `${label} ` : ''}{ok ? 'PASS' : 'FAIL'}</span>
}

function Step({ k, state }) {
  return <span className={`w7-step w8-st ${state || ''}`}>{short(k[0])}({k[1]})</span>
}

function Seq({ seq }) {
  return (
    <span className="w7-path">
      {seq.map((k, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="w8-arrow">→</span>}
          <Step k={k} />
        </React.Fragment>
      ))}
    </span>
  )
}

function ModeChips({ modes }) {
  if (!modes?.length) return <span className="w8-chip ok">no failure modes</span>
  return modes.map((m) => <span key={m} className="w8-chip bad">{m}</span>)
}

/* ----------------------------------------------------------- trace card */

function TraceCard({ tid, seed, mitigate, title }) {
  const [run, setRun] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    let live = true
    setRun(null); setErr(null)
    api('/api/week8/run', { ticket_id: tid, seed, mitigate })
      .then((r) => live && setRun(r)).catch((e) => live && setErr(e.message))
    return () => { live = false }
  }, [tid, seed, mitigate])
  if (err) return <div className="banner bad"><pre>{err}</pre></div>
  if (!run) return <div className="w7-run"><p className="ev-note">running {tid} seed {seed}…</p></div>
  const s = run.score
  const accepted = run.accepted.map((seq) => JSON.stringify(seq))
  const ok = s.trajectory_pass
  return (
    <div className={`w7-run ${ok && s.outcome_pass ? 'pass' : 'fail'}`}>
      <div className="w7-run-top">
        <b>{title || `${tid} · seed ${seed}`}</b>
        <span className="w8-chip">{mitigate ? 'mitigation ON' : 'mitigation OFF'}</span>
        <span className="spacer" />
        <PF ok={s.outcome_pass} label="outcome" />
        <PF ok={s.trajectory_pass} label="trajectory" />
      </div>
      <div className="w7-run-stats">
        <span>{num(run.total_tokens)} tokens</span>
        <span>{usd(run.cost_usd)}</span>
        <span>{run.latency_s.toFixed(2)} s (sim.)</span>
        <span>{run.llm_calls} model calls</span>
        <span>{s.steps_taken} / {s.steps_needed} steps</span>
        {run.terminated && <span className="w8-warn">budget {run.terminated.budget} hit</span>}
      </div>
      <div className="w8-modes">
        <ModeChips modes={s.modes} />
        {s.tool_errors > 0 && (
          <span className="w8-chip warn">validator rejected {s.tool_errors} call{s.tool_errors === 1 ? '' : 's'} — the attempt stays in the trajectory</span>
        )}
      </div>
      <div className="w8-kv">
        <span>accepted</span>
        <div>{run.accepted.map((seq, i) => <div key={i}><Seq seq={seq} /></div>)}</div>
      </div>
      <ol className="w7-steps w8-trace">
        {run.tool_calls.map((c, i) => {
          const state = c.error ? 'err' : c.valid ? 'ok' : 'bad'
          return (
            <li key={i} className={`tool ${state}`}>
              <div className="w7-sh">
                <b>{i + 1}. {c.name}</b>
                <span>
                  called on <code>{c.key[1]}</code> ·{' '}
                  {c.error ? <span className="w8-warn">rejected with an error</span>
                    : c.valid ? <span className="w8-okt">argument valid</span>
                      : <span className="w8-badt">argument NOT grounded</span>}
                </span>
              </div>
              <div className="w7-kv"><span>args</span><code>{JSON.stringify(c.args)}</code></div>
              <div className="w7-kv"><span>result</span><code>{JSON.stringify(c.result)}</code></div>
            </li>
          )
        })}
      </ol>
      <p className="w7-foot">
        Taken sequence {accepted.includes(JSON.stringify(s.keys)) ? 'matches' : 'matches NONE of'} the
        accepted set{s.outcome_mismatches?.length ? ' · outcome mismatches: ' +
          s.outcome_mismatches.map((m) => `${m.field} expected ${m.expected}, got ${m.got}`).join('; ') : ''}.
      </p>
      <pre className="w7-reply">{run.output.reply}</pre>
    </div>
  )
}

function TracePair({ tid, seed }) {
  return (
    <div className="w7-runs">
      <TraceCard tid={tid} seed={seed} mitigate={false} title={`BEFORE · ${tid} · seed ${seed}`} />
      <TraceCard tid={tid} seed={seed} mitigate title={`AFTER · ${tid} · seed ${seed}`} />
    </div>
  )
}

/* ------------------------------------------------------------- overview */

function Overview({ d, go }) {
  const b = d.before.summary
  const a = d.after.summary
  const top = d.top_mode
  const checklist = [
    ['The 10 expected tool sequences, with alternate-path cases marked', 'paths',
      `${Object.keys(d.alternate_path_cases).length} alternate-path cases asserted as sets`],
    ['Tool-choice accuracy, argument validity, step efficiency, cost p50 and max', 'metrics',
      `${pct(b.tool_choice_accuracy)} · ${pct(b.argument_validity)} · ${b.step_efficiency.toFixed(3)} · ${usd(b.cost_p50)} / ${usd(b.cost_max)}`],
    ['The gap number and the trace of one right-answer-wrong-path ticket', 'gap',
      `${pts(b.gap)} · ${b.right_answer_wrong_path} runs`],
    ['Failure-mode taxonomy and how the top mode was chosen', 'modes', `top: ${top}`],
    ['The single mitigation diff, before → after count, measured price', 'mitigation',
      `${b.modes[top]} → ${a.modes[top]} · ${signed(a.cost_p50 - b.cost_p50, (x) => usd(x))} p50 cost`],
    ['Per-mode regression table covering every mode', 'regression',
      `${Object.keys(d.modes).length} modes checked`],
    ['Bonus: indirect injection, defences, what still gets through, eval cost', 'injection',
      '3 indirect + 3 direct attacks × 4 defence configurations'],
  ]
  return (
    <>
      <section className="w8-hero">
        <div className="w8-tile big">
          <span>outcome − trajectory gap</span>
          <b>{pts(b.gap)}</b>
          <i>{pct(b.outcome_pass_rate)} pass the outcome eval, only {pct(b.trajectory_pass_rate)} take an acceptable path</i>
        </div>
        <div className="w8-tile">
          <span>right answer, wrong path</span>
          <b>{b.right_answer_wrong_path} / {b.runs}</b>
          <i>runs the outcome eval passes and the trajectory eval fails</i>
        </div>
        <div className="w8-tile">
          <span>top mode · {top}</span>
          <b>{b.modes[top]} → {a.modes[top]}</b>
          <i>after ONE mitigation (argument validation)</i>
        </div>
        <div className="w8-tile">
          <span>price of the mitigation</span>
          <b>{signed(a.cost_p50 - b.cost_p50, (x) => usd(x))}</b>
          <i>p50 cost / ticket ({signed((a.cost_p50 / b.cost_p50 - 1), (x) => pct(x))}), {signed(a.latency_p50 - b.latency_p50, (x) => `${x.toFixed(2)} s`)} p50 latency</i>
        </div>
      </section>

      <section className="w7-card">
        <h3>The problem</h3>
        <p className="w8-p">
          The ticket agent passes its outcome eval and support still doesn't trust it: it
          drafted a correct refund reply after never opening the order record. A right
          answer down a wrong path is a time bomb with a passing test. This page scores the
          path, exposes the gap as a number, and kills the worst failure mode with the
          price tag attached. It extends the Week 7 agent: same 10 tickets, same answer key,
          same budgets, same outcome grader.
        </p>
      </section>

      <section className="w7-card">
        <h3>Submission checklist — where each item is on this page</h3>
        <table className="w7-cmp w8-check">
          <tbody>
            {checklist.map(([item, tab, val]) => (
              <tr key={tab}>
                <td><span className="w8-okt">✓</span> {item}</td>
                <td className="mut">{val}</td>
                <td><button type="button" className="w7-btn sm" onClick={() => go(tab)}>open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="w7-card">
        <h3>Week 8 topics — where each is covered</h3>
        <table className="w7-cmp w8-check">
          <tbody>
            {[['Agent failure modes', 'modes', '7-mode zoo, classified from each trajectory'],
              ['Trajectory evaluation', 'gap', 'every run scored on its path, not only its answer'],
              ['Expected tool sequences', 'paths', '10 sequences, 3 asserted as sets'],
              ['Tool-choice accuracy', 'metrics', pct(b.tool_choice_accuracy)],
              ['Outcome vs trajectory gap', 'gap', pts(b.gap)],
              ['Cost per task (mean & p99)', 'metrics', `mean ${usd(b.cost_mean)} · p99 ${usd(b.cost_p99)} · max ${usd(b.cost_max)}`],
              ['Prompt injection (direct)', 'injection', 'D1–D3 typed into the user turn'],
              ['Indirect prompt injection', 'injection', 'A1–A3 hidden in a pasted email returned by get_ticket'],
              ['Tool sandboxing & least privilege', 'injection', 'read-only vs sandboxed issue_refund; per-tool scope'],
              ['Output validation', 'injection', 'output guardrail + argument validation on tool inputs'],
              ['OWASP LLM Top 10', 'owasp', 'all 10 risks mapped, gaps stated'],
            ].map(([t, tab, v]) => (
              <tr key={t}><td><span className="w8-okt">✓</span> {t}</td><td className="mut">{v}</td>
                <td><button type="button" className="w7-btn sm" onClick={() => go(tab)}>open</button></td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="w7-card">
        <h3>What is real and what is a dial</h3>
        <p className="w8-p">
          There is no <code>ANTHROPIC_API_KEY</code> on this checkout, so the model is an
          offline engine (<code>week8/sim_model.py</code>). It keeps Week 7's decision logic
          and samples the behaviours a real tool-using model shows. Each behaviour is a
          named rate drawn from a seeded hash, so runs are reproducible. The eval, the
          taxonomy, the mitigation, its price and the regression check are real code
          paths; <b>how often</b> the model wanders is a chosen dial, not a measurement.
          {` ${d.ticket_ids.length} tickets × ${d.seeds} seeds = ${b.runs} runs per condition`};
          BEFORE and AFTER use the same seeds.
        </p>
        <table className="w7-cmp w8-rates">
          <tbody>
            {Object.entries(d.rates).map(([k, v]) => (
              <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}

/* -------------------------------------------------------- 1 · sequences */

function PathsTab({ d }) {
  const b = d.before.summary
  return (
    <>
      <section className="w7-card">
        <h3>The 10 expected tool sequences</h3>
        <p className="w8-p">
          A step is <i>tool(what it was called on)</i>. For the policy tool, "what it was
          called on" is the order whose <b>fetched record</b> the facts came from; facts
          typed from the customer's email score <code>UNGROUNDED</code> even when every number
          is right. Tickets with more than one correct path are asserted as a <b>set</b>.
          Asserted in code: <code>trajectory_eval.py::EXPECTED_PATHS</code>.
        </p>
        <div className="w7-scroll">
          <table className="w7-tickets w8-paths">
            <thead><tr><th>ticket</th><th>customer message</th><th>accepted sequence(s)</th><th>alternate paths</th></tr></thead>
            <tbody>
              {d.ticket_ids.map((tid) => {
                const alt = d.alternate_path_cases[tid]
                return (
                  <tr key={tid} className={alt ? 'w8-alt' : ''}>
                    <td className="mono">{tid}</td>
                    <td className="w8-msg">“{d.tickets[tid].message}”</td>
                    <td>{d.expected_paths[tid].map((s, i) => <div key={i}><Seq seq={s} /></div>)}</td>
                    <td>{alt
                      ? <><span className="w8-chip warn">set of {d.expected_paths[tid].length}</span> <span className="mut">{alt}</span></>
                      : <span className="mut">one path</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className="w7-card">
        <h3>Over-assertion check: why the sets matter</h3>
        <table className="w7-cmp">
          <thead><tr><th>assertion style (BEFORE runs)</th><th>trajectory pass</th><th>gap</th></tr></thead>
          <tbody>
            <tr><td>One exact sequence per ticket (brittle)</td><td>{pct(b.naive_trajectory_pass_rate)}</td><td>{pts(b.naive_gap)}</td></tr>
            <tr><td>Accepted <b>set</b> per ticket (this eval)</td><td className="win">{pct(b.trajectory_pass_rate)}</td><td className="win">{pts(b.gap)}</td></tr>
          </tbody>
        </table>
        <p className="w7-foot">
          {((b.naive_gap - b.gap) * 100).toFixed(1)} pts of the gap would be correct runs — searching prior tickets
          before vs after pulling the order, or fetching the two duplicate charges in either order —
          scored as failures.
        </p>
      </section>
    </>
  )
}

/* ---------------------------------------------------------- 2 · metrics */

function CostChart({ runs, color, title, stats, onPick }) {
  const [hov, setHov] = useState(null)
  const sorted = useMemo(() => [...runs].sort((x, y) => x.cost_usd - y.cost_usd), [runs])
  const W = 640, H = 170, P = { l: 46, r: 12, t: 14, b: 22 }
  const max = Math.max(0.06, ...runs.map((r) => r.cost_usd))
  const bw = (W - P.l - P.r) / sorted.length
  const y = (v) => H - P.b - (v / max) * (H - P.t - P.b)
  const ticks = [0, 0.02, 0.04, 0.06].filter((t) => t <= max)
  const h = hov != null ? sorted[hov] : null
  return (
    <figure className="w8-fig">
      <figcaption>
        <b>{title}</b>
        <span className="mut">
          {h ? `${h.ticket_id} · seed ${h.seed} · ${usd(h.cost_usd)} · ${h.llm_calls} model calls${h.terminated ? ` · budget ${h.terminated} hit` : ''} — click for trace`
            : `per-run cost, sorted · p50 ${usd(stats.cost_p50)} · p99 ${usd(stats.cost_p99)} · max ${usd(stats.cost_max)} · mean ${usd(stats.cost_mean)}`}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: per-run cost`} onMouseLeave={() => setHov(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className="w8-grid" />
            <text x={P.l - 6} y={y(t) + 3} textAnchor="end" className="w8-ax">${t.toFixed(2)}</text>
          </g>
        ))}
        {sorted.map((r, i) => {
          const top = y(r.cost_usd)
          return (
            <g key={i} onMouseEnter={() => setHov(i)} onClick={() => onPick(r)} style={{ cursor: 'pointer' }}>
              <rect x={P.l + i * bw} y={P.t} width={bw} height={H - P.t - P.b} fill="transparent" />
              <rect x={P.l + i * bw + 0.5} y={top} width={Math.max(1, bw - 1)} height={H - P.b - top}
                rx={Math.min(2, bw / 3)} fill={color} opacity={hov == null || hov === i ? 1 : 0.45} />
            </g>
          )
        })}
        {[['p50', stats.cost_p50, P.l + 4, 'start'], ['p99', stats.cost_p99, P.l + (W - P.l - P.r) * 0.45, 'middle'],
          ['max', stats.cost_max, P.l + 4, 'start']].map(([lab, v, x, anchor]) => (
          <g key={lab}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className="w8-ref" />
            <text x={x} y={y(v) - 4} textAnchor={anchor} className="w8-reflab">{lab} {usd(v)}</text>
          </g>
        ))}
      </svg>
    </figure>
  )
}

function MetricsTab({ d }) {
  const b = d.before.summary
  const a = d.after.summary
  const [pick, setPick] = useState(null)
  const rows = [
    ['Tool-choice accuracy', 'LCS of tool names vs the best accepted path ÷ the longer of the two', pct(b.tool_choice_accuracy), pct(a.tool_choice_accuracy)],
    ['Argument validity rate', 'ids the ticket actually named; policy facts that equal a fetched record (real, not fluent fiction)', pct(b.argument_validity), pct(a.argument_validity)],
    ['Step efficiency', 'tool steps taken ÷ steps needed (1.00 = no waste)', b.step_efficiency.toFixed(3), a.step_efficiency.toFixed(3)],
    ['Step efficiency per run, p50 / max', '', `${b.step_efficiency_p50.toFixed(2)} / ${b.step_efficiency_max.toFixed(2)}`, `${a.step_efficiency_p50.toFixed(2)} / ${a.step_efficiency_max.toFixed(2)}`],
    ['Cost per ticket — p50', 'median run', usd(b.cost_p50), usd(a.cost_p50)],
    ['Cost per ticket — p95', '1 run in 20 costs at least this', usd(b.cost_p95), usd(a.cost_p95)],
    ['Cost per ticket — p99', '1 run in 100 costs at least this', usd(b.cost_p99), usd(a.cost_p99)],
    ['Cost per ticket — MAX', 'the run that shows up on the bill', usd(b.cost_max), usd(a.cost_max)],
    ['Cost per ticket — mean', 'shown only for contrast; it hides the tail', usd(b.cost_mean), usd(a.cost_mean)],
    ['Tokens per ticket p50 / max', '', `${num(b.tokens_p50)} / ${num(b.tokens_max)}`, `${num(a.tokens_p50)} / ${num(a.tokens_max)}`],
    ['Latency per ticket p50 / max', 'simulated', `${b.latency_p50.toFixed(2)} s / ${b.latency_max.toFixed(2)} s`, `${a.latency_p50.toFixed(2)} s / ${a.latency_max.toFixed(2)} s`],
    ['Outcome pass rate', 'Week 7 grader: contract + Week-6 assertions', pct(b.outcome_pass_rate), pct(a.outcome_pass_rate)],
    ['Trajectory pass rate', 'path in the accepted set, all args valid, no budget cut', pct(b.trajectory_pass_rate), pct(a.trajectory_pass_rate)],
  ]
  return (
    <>
      <section className="w7-card">
        <h3>The four trajectory numbers ({b.runs} runs per condition)</h3>
        <table className="w7-cmp w8-metrics">
          <thead><tr><th>metric</th><th>definition</th><th>BEFORE</th><th>AFTER</th></tr></thead>
          <tbody>
            {rows.map(([m, def, bv, av]) => (
              <tr key={m} className={m.includes('MAX') || m.includes('p99') ? 'w8-hl' : ''}>
                <td>{m}</td><td className="mut">{def}</td><td>{bv}</td><td>{av}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="w7-card">
        <h3>Cost variance — p50, p99 and max, not the mean</h3>
        <p className="w8-p">
          BEFORE, the most expensive run costs <b>{(b.cost_max / b.cost_p50).toFixed(1)}× the p50</b>. The mean ({usd(b.cost_mean)}) hides it.
          Hover a bar for the run; click it for its full trace.
        </p>
        <div className="w8-charts">
          <CostChart runs={d.before.runs} color={C_BEFORE} title="BEFORE (no mitigation)" stats={b}
            onPick={(r) => setPick({ ...r, mitigate: false })} />
          <CostChart runs={d.after.runs} color={C_AFTER} title="AFTER (argument validation)" stats={a}
            onPick={(r) => setPick({ ...r, mitigate: true })} />
        </div>
        {pick && <TraceCard tid={pick.ticket_id} seed={pick.seed} mitigate={pick.mitigate} />}
      </section>
      <section className="w7-card">
        <h3>Per ticket — passes out of {d.seeds} runs</h3>
        <table className="w7-tickets">
          <thead><tr><th>ticket</th><th>outcome BEFORE</th><th>trajectory BEFORE</th><th>outcome AFTER</th><th>trajectory AFTER</th></tr></thead>
          <tbody>
            {d.ticket_ids.map((tid) => {
              const pb = b.per_ticket[tid]
              const pa = a.per_ticket[tid]
              return (
                <tr key={tid}>
                  <td className="mono">{tid}</td>
                  <td className="n">{pb.outcome}/{pb.n}</td><td className="n">{pb.trajectory}/{pb.n}</td>
                  <td className={`n ${pa.outcome !== pb.outcome ? 'w8-chg' : ''}`}>{pa.outcome}/{pa.n}</td>
                  <td className="n">{pa.trajectory}/{pa.n}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </>
  )
}

/* -------------------------------------------------------------- 3 · gap */

function cellState(r) {
  if (r.outcome_pass && r.trajectory_pass) return ['ok', '✓', 'right answer, right path']
  if (r.outcome_pass) return ['warn', '!', 'right answer, WRONG path']
  return ['bad', '✗', 'wrong outcome']
}

function GapTab({ d }) {
  const [cond, setCond] = useState('before')
  const [pick, setPick] = useState({ ticket_id: 'TCK-7001', seed: 2 })
  const runs = d[cond].runs
  const s = d[cond].summary
  const m = {
    pp: runs.filter((r) => r.outcome_pass && r.trajectory_pass).length,
    pf: runs.filter((r) => r.outcome_pass && !r.trajectory_pass).length,
    fp: runs.filter((r) => !r.outcome_pass && r.trajectory_pass).length,
    ff: runs.filter((r) => !r.outcome_pass && !r.trajectory_pass).length,
  }
  const byKey = Object.fromEntries(runs.map((r) => [`${r.ticket_id}|${r.seed}`, r]))
  const seeds = [...Array(d.seeds).keys()]
  return (
    <>
      <section className="w8-hero">
        <div className="w8-tile big">
          <span>gap = outcome pass − trajectory pass ({cond})</span>
          <b>{pts(s.gap)}</b>
          <i>{pct(s.outcome_pass_rate)} − {pct(s.trajectory_pass_rate)}</i>
        </div>
        <div className="w8-matrix">
          <div />
          <div className="h">trajectory PASS</div>
          <div className="h">trajectory FAIL</div>
          <div className="h">outcome PASS</div>
          <div className="ok">{m.pp}</div>
          <div className="warn"><b>{m.pf}</b><i>right answer, wrong path</i></div>
          <div className="h">outcome FAIL</div>
          <div className="mid">{m.fp}</div>
          <div className="bad">{m.ff}</div>
        </div>
      </section>

      <section className="w7-card">
        <div className="w7-h">
          <h3>Every run — ticket × seed</h3>
          <span className="spacer" />
          <Seg value={cond} onChange={setCond} options={[['before', 'BEFORE'], ['after', 'AFTER']]} />
        </div>
        <div className="w8-legend">
          <span><i className="w8-cell ok">✓</i> right answer, right path</span>
          <span><i className="w8-cell warn">!</i> right answer, wrong path (the gap)</span>
          <span><i className="w8-cell bad">✗</i> wrong outcome</span>
        </div>
        <div className="w7-scroll">
          <table className="w8-grid-t">
            <thead><tr><th>ticket</th>{seeds.map((sd) => <th key={sd}>s{sd}</th>)}</tr></thead>
            <tbody>
              {d.ticket_ids.map((tid) => (
                <tr key={tid}>
                  <td className="mono">{tid}</td>
                  {seeds.map((sd) => {
                    const r = byKey[`${tid}|${sd}`]
                    if (!r) return <td key={sd} />
                    const [cls, sym, what] = cellState(r)
                    const on = pick.ticket_id === tid && pick.seed === sd
                    return (
                      <td key={sd}>
                        <button type="button" className={`w8-cell ${cls} ${on ? 'on' : ''}`}
                          title={`${tid} seed ${sd}: ${what}${r.modes.length ? ' · ' + r.modes.join(', ') : ''}`}
                          onClick={() => setPick({ ticket_id: tid, seed: sd })}>{sym}</button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="w7-card">
        <h3>{pick.ticket_id === 'TCK-7001' && pick.seed === 2
          ? 'The named case: TCK-7001, seed 2 — correct refund, order record never opened'
          : `${pick.ticket_id}, seed ${pick.seed}`}</h3>
        {pick.ticket_id === 'TCK-7001' && pick.seed === 2 && (
          <p className="w8-p">
            The customer wrote “12 days ago for $41.50”. The agent typed those numbers straight
            into the policy tool and <b>assumed</b> <code>status: paid</code>, skipping{' '}
            <code>get_order</code>. The reply is right only because the customer's numbers
            happened to be right. The same shortcut on <b>TCK-7005</b> refunded an order that
            was <b>already refunded</b>; compare seeds 0, 3, 7 and 8 there.
          </p>
        )}
        <TracePair tid={pick.ticket_id} seed={pick.seed} />
      </section>
    </>
  )
}

/* ------------------------------------------------------------ the zoo */

function ModesTab({ d }) {
  const b = d.before.summary
  const [mode, setMode] = useState(d.top_mode)
  const [pick, setPick] = useState(null)
  const ranked = Object.keys(d.modes).sort((x, y) =>
    b.modes[y] * d.severity[y][0] - b.modes[x] * d.severity[x][0] || b.modes[y] - b.modes[x])
  const byCount = Object.keys(d.modes).sort((x, y) => b.modes[y] - b.modes[x])[0]
  const hits = d.before.runs.filter((r) => r.modes.includes(mode))
  return (
    <>
      <section className="w7-card">
        <h3>The failure-mode taxonomy, ranked (BEFORE)</h3>
        <p className="w8-p">
          Each run is classified from its trajectory by <code>failure_modes()</code>; a run can
          show more than one mode. The top mode is ranked by <b>count × severity</b>.
          Click a mode to list its runs.
        </p>
        <table className="w7-cmp w8-zoo">
          <thead><tr><th>#</th><th>mode</th><th>definition</th><th>severity</th><th>runs</th><th>weight</th><th>score</th></tr></thead>
          <tbody>
            {ranked.map((m, i) => (
              <tr key={m} className={`click ${mode === m ? 'on' : ''} ${m === d.top_mode ? 'w8-hl' : ''}`}
                onClick={() => { setMode(m); setPick(null) }}>
                <td>{i + 1}</td>
                <td><code>{m}</code>{m === d.top_mode && <span className="w8-chip bad">TOP</span>}</td>
                <td className="mut">{d.modes[m]}</td>
                <td className="mut">{d.severity[m][1]}</td>
                <td>{b.modes[m]}</td><td>×{d.severity[m][0]}</td><td><b>{b.modes[m] * d.severity[m][0]}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
        {byCount !== d.top_mode && (
          <p className="w7-foot">
            By raw count alone the top mode would be <code>{byCount}</code> ({b.modes[byCount]} runs vs{' '}
            {b.modes[d.top_mode]}). It is not chosen: it changes no decision, and its cost tail is
            already capped by the Week 7 step budget.
          </p>
        )}
      </section>
      <section className="w7-card">
        <h3><code>{mode}</code> — {hits.length} run{hits.length === 1 ? '' : 's'} BEFORE</h3>
        <div className="w8-chips">
          {hits.length ? hits.map((r) => (
            <button key={`${r.ticket_id}${r.seed}`} type="button"
              className={`w8-chip btn ${r.outcome_pass ? 'warn' : 'bad'} ${pick === r ? 'on' : ''}`}
              title={r.outcome_pass ? 'outcome passed (silent failure)' : 'outcome failed'}
              onClick={() => setPick(r)}>
              {r.ticket_id} · s{r.seed} {r.outcome_pass ? '(outcome ✓)' : '(outcome ✗)'}
            </button>
          )) : <span className="mut">none</span>}
        </div>
        {pick && <TracePair tid={pick.ticket_id} seed={pick.seed} />}
      </section>
    </>
  )
}

/* -------------------------------------------------------- 4 · mitigation */

function MitigationTab({ d }) {
  const b = d.before.summary
  const a = d.after.summary
  const top = d.top_mode
  const after = Object.fromEntries(d.after.runs.map((r) => [`${r.ticket_id}|${r.seed}`, r]))
  const touched = d.before.runs.map((r) => [r, after[`${r.ticket_id}|${r.seed}`]])
    .filter(([, x]) => x && x.tool_errors > 0)
  const mean = (xs) => xs.reduce((s, x) => s + x, 0) / Math.max(1, xs.length)
  const tc = mean(touched.map(([x, y]) => y.cost_usd - x.cost_usd))
  const tt = mean(touched.map(([x, y]) => y.total_tokens - x.total_tokens))
  const tl = mean(touched.map(([x, y]) => y.latency_s - x.latency_s))
  const fixed = touched.filter(([x, y]) => y.outcome_pass && !x.outcome_pass).length
  const price = [
    ['Cost / ticket p50', b.cost_p50, a.cost_p50, (x) => usd(x)],
    ['Cost / ticket max', b.cost_max, a.cost_max, (x) => usd(x)],
    ['Cost / ticket mean', b.cost_mean, a.cost_mean, (x) => usd(x)],
    ['Tokens / ticket mean', b.tokens_mean, a.tokens_mean, num],
    ['Latency / ticket p50 (sim.)', b.latency_p50, a.latency_p50, (x) => `${x.toFixed(3)} s`],
    ['Latency / ticket max (sim.)', b.latency_max, a.latency_max, (x) => `${x.toFixed(3)} s`],
  ]
  return (
    <>
      <section className="w8-hero">
        <div className="w8-tile big">
          <span><code>{top}</code> runs</span>
          <b>{b.modes[top]} → {a.modes[top]}</b>
          <i>same {b.runs} seeds, one change</i>
        </div>
        <div className="w8-tile">
          <span>price · p50 cost / ticket</span>
          <b>{signed(a.cost_p50 - b.cost_p50, (x) => usd(x))}</b>
          <i>{signed(a.cost_p50 / b.cost_p50 - 1, (x) => pct(x))}</i>
        </div>
        <div className="w8-tile">
          <span>price on the {touched.length} runs it fired on</span>
          <b>{signed(tc, (x) => usd(x))}</b>
          <i>+{num(tt)} tokens, +{tl.toFixed(2)} s each; {fixed} went wrong → right</i>
        </div>
      </section>

      <section className="w7-card">
        <h3>The one change: argument validation on <code>lookup_refund_policy</code></h3>
        <p className="w8-p">
          <code>Config(validate_policy_args=True)</code> switches on this function. Tool
          descriptions, schemas, the system prompt, the budgets and the model are all unchanged —
          so the before → after count is attributable to this change alone. Other zoo options
          (tighter description, hard step limit, re-planning, workflow) were deliberately
          <b> not</b> shipped alongside it.
        </p>
        <pre className="w7-code w8-diff">{d.mitigation_source.split('\n').map((l, i) => (
          <span key={i} className="add">+ {l}{'\n'}</span>))}</pre>
        <details>
          <summary className="w8-sum">where it is switched on — <code>tools8.call()</code></summary>
          <pre className="w7-code">{d.mitigation_switch}</pre>
        </details>
      </section>

      <section className="w7-card">
        <h3>Before → after, with the price measured</h3>
        <table className="w7-cmp">
          <thead><tr><th></th><th>BEFORE</th><th>AFTER</th><th>price</th></tr></thead>
          <tbody>
            <tr className="w8-hl"><td><code>{top}</code> runs</td><td>{b.modes[top]}</td><td>{a.modes[top]}</td><td className="mut">target</td></tr>
            <tr><td>Outcome pass rate</td><td>{pct(b.outcome_pass_rate)}</td><td>{pct(a.outcome_pass_rate)}</td><td className="mut">TCK-7005 wrong refunds fixed</td></tr>
            <tr><td>Tool calls rejected with an error</td><td>{b.tool_errors}</td><td>{a.tool_errors}</td><td className="mut">each one is an extra round trip</td></tr>
            {price.map(([l, x, y, f]) => (
              <tr key={l}><td>{l}</td><td>{f(x)}</td><td>{f(y)}</td>
                <td><b>{signed(y - x, f)}</b> <span className="mut">({signed(y / x - 1, (v) => pct(v))})</span></td></tr>
            ))}
          </tbody>
        </table>
        <p className="w7-foot">
          Not free: a rejected call is a full extra model round trip with the whole history
          resent. What it did <b>not</b> fix: trajectory pass stays {pct(b.trajectory_pass_rate)} → {pct(a.trajectory_pass_rate)} and
          the gap moves {pts(b.gap)} → {pts(a.gap)}. The validator stops the shortcut at the tool
          boundary, but the model still <i>attempts</i> it, and a strict trajectory eval still
          reports that attempt.
        </p>
      </section>

      <section className="w7-card">
        <h3>Same run, before and after — TCK-7001 seed 2</h3>
        <TracePair tid="TCK-7001" seed={2} />
      </section>
    </>
  )
}

/* -------------------------------------------------------- 5 · regression */

function RegressionTab({ d }) {
  const b = d.before.summary.modes
  const a = d.after.summary.modes
  const top = d.top_mode
  const max = Math.max(1, ...Object.values(b), ...Object.values(a))
  const rows = Object.keys(d.modes).map((m) => {
    const x = b[m], y = a[m]
    let v, cls
    if (m === top) { v = y < x ? 'TARGET: reduced' : 'TARGET: not reduced'; cls = y < x ? 'ok' : 'bad' }
    else if (x === 0 && y > 0) { v = 'NEW: created by the mitigation'; cls = 'bad' }
    else if (y > x) { v = 'WORSE'; cls = 'bad' }
    else if (y < x) { v = 'better (side effect)'; cls = 'ok' }
    else { v = 'unchanged'; cls = '' }
    return { m, x, y, v, cls }
  })
  const worse = rows.filter((r) => r.cls === 'bad' && r.m !== top)
  return (
    <section className="w7-card">
      <h3>Per-mode counts, before → after — every mode in the taxonomy</h3>
      <div className="w8-legend">
        <span><i className="w8-sw" style={{ background: C_BEFORE }} /> BEFORE</span>
        <span><i className="w8-sw" style={{ background: C_AFTER }} /> AFTER</span>
      </div>
      <table className="w7-cmp w8-reg">
        <thead><tr><th>mode</th><th>BEFORE</th><th>AFTER</th><th>Δ</th><th className="w8-barcol">runs</th><th>verdict</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.m}>
              <td><code>{r.m}</code></td><td>{r.x}</td><td>{r.y}</td>
              <td>{r.y - r.x > 0 ? '+' : ''}{r.y - r.x}</td>
              <td className="w8-barcol">
                <div className="w8-hbar"><i style={{ width: `${(r.x / max) * 100}%`, background: C_BEFORE }} title={`BEFORE ${r.x}`} /></div>
                <div className="w8-hbar"><i style={{ width: `${(r.y / max) * 100}%`, background: C_AFTER }} title={`AFTER ${r.y}`} /></div>
              </td>
              <td><span className={`w8-chip ${r.cls}`}>{r.v}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="w8-p">
        {worse.length
          ? <>Modes that got worse or appeared: {worse.map((r) => <code key={r.m}>{r.m} </code>)}.
            {' '}<code>error_retry_loop</code> is new: after the validator rejects a call, the agent
            sometimes resends it unchanged before re-planning. <code>redundant_loop</code> rose
            because recovery paths are longer, so there are more steps on which to repeat a call.</>
          : <>No mode got worse. Modes checked: {rows.map((r) => <code key={r.m}>{r.m} </code>)}</>}
      </p>
    </section>
  )
}

/* -------------------------------------------------------- bonus · inject */

const CONFIG_LABEL = {
  undefended: 'undefended',
  defended: 'defended (read-only)',
  sandboxed: 'defended (sandboxed)',
  'defended+screen': 'defended + input screen',
}

function ResultTable({ results, attacks, configs, n }) {
  return (
    <div className="w7-scroll">
      <table className="w7-cmp w8-inj">
        <thead><tr><th>attack</th><th>config</th><th>called issue_refund</th><th>money moved</th>
          <th>sandboxed</th><th>refund promised</th><th>attacker text in reply</th>
          <th>guardrail fired</th><th>tool errors</th><th>got through</th></tr></thead>
        <tbody>
          {Object.keys(attacks).map((aid) => configs.map((c, i) => {
            const x = results[c]?.[aid]
            if (!x) return null
            return (
              <tr key={aid + c}>
                <td>{i === 0 ? <b>{aid}</b> : ''}</td><td>{CONFIG_LABEL[c]}</td>
                <td>{x.tried_refund_tool}/{n}</td><td>{x.money_moved}/{n}</td>
                <td>{x.sandboxed ?? 0}/{n}</td>
                <td>{x.refund_promised}/{n}</td><td>{x.attacker_text_in_reply}/{n}</td>
                <td>{x.guardrail_fired}/{n}</td><td>{x.tool_errors ?? '—'}</td>
                <td><span className={`w8-chip ${x.got_through ? 'bad' : 'ok'}`}>{x.got_through}/{n}</span></td>
              </tr>
            )
          }))}
        </tbody>
      </table>
    </div>
  )
}

function AttackRunner({ d }) {
  const [kind, setKind] = useState('indirect')
  const attacks = kind === 'direct' ? d.direct_attacks : d.attacks
  const [aid, setAid] = useState(Object.keys(d.attacks)[0])
  const configs = kind === 'direct'
    ? ['undefended', 'defended', 'defended+screen']
    : ['undefended', 'defended', 'sandboxed']
  const [config, setConfig] = useState('undefended')
  const [seed, setSeed] = useState(0)
  const [r, setR] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const switchKind = (k) => {
    setKind(k)
    setAid(Object.keys(k === 'direct' ? d.direct_attacks : d.attacks)[0])
    setConfig('undefended')
  }
  useEffect(() => {
    if (!attacks[aid]) return
    let live = true
    setBusy(true); setErr(null)
    api('/api/week8/attack', { attack_id: aid, kind, config, seed })
      .then((x) => live && setR(x)).catch((e) => live && setErr(e.message))
      .finally(() => live && setBusy(false))
    return () => { live = false }
  }, [kind, aid, config, seed])
  const v = r?.verdict
  return (
    <section className="w7-card">
      <h3>Attack it yourself</h3>
      <div className="w8-controls">
        <Seg value={kind} onChange={switchKind} options={[['indirect', 'indirect (in the email)'], ['direct', 'direct (in the user turn)']]} />
      </div>
      <div className="w8-controls">
        <Seg value={aid} onChange={setAid} options={Object.keys(attacks).map((k) => [k, k])} />
      </div>
      <div className="w8-controls">
        <Seg value={config} onChange={setConfig} options={configs.map((c) => [c, CONFIG_LABEL[c]])} />
        <label className="w8-sel">seed
          <select value={seed} onChange={(e) => setSeed(Number(e.target.value))}>
            {[...Array(10).keys()].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {busy && <span className="mut">running…</span>}
      </div>
      <p className="w7-foot">{d.config_info[config]}</p>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {r && v && (
        <div className={`w7-run ${v.got_through ? 'fail' : 'pass'}`}>
          <div className="w7-run-top">
            <b>{r.ticket.ticket_id}</b>
            <span className="w8-chip">{r.kind}</span>
            <span className="spacer" />
            <span className={`w7-pf ${v.got_through ? 'bad' : 'ok'}`}>{v.got_through ? 'GOT THROUGH' : 'BLOCKED'}</span>
          </div>
          <div className="w8-kv"><span>user turn</span><code>{r.user_message}</code></div>
          <div className="w8-kv"><span>ticket body</span><code>{r.ticket.message}</code></div>
          <div className="w8-modes">
            <span className={`w8-chip ${v.tried_refund_tool ? 'bad' : 'ok'}`}>called issue_refund: {String(v.tried_refund_tool)}</span>
            <span className={`w8-chip ${v.money_moved ? 'bad' : 'ok'}`}>money moved: {String(v.money_moved)}</span>
            {v.sandboxed && <span className="w8-chip warn">sandboxed: queued for a human, no money moved</span>}
            <span className={`w8-chip ${v.refund_promised ? 'bad' : 'ok'}`}>refund promised: {String(v.refund_promised)}</span>
            <span className={`w8-chip ${v.attacker_text_in_reply ? 'bad' : 'ok'}`}>attacker text in reply: {String(v.attacker_text_in_reply)}</span>
            {v.guardrail && <span className="w8-chip warn">output guardrail: {v.guardrail}</span>}
          </div>
          <ol className="w7-steps">
            {r.tool_calls.map((c, i) => (
              <li key={i} className="tool">
                <div className="w7-sh"><b>{i + 1}. {c.name}</b><span>{c.result.error ? 'error' : c.result.status === 'dry_run' ? 'dry run (sandbox)' : 'ok'}</span></div>
                <div className="w7-kv"><span>args</span><code>{JSON.stringify(c.args)}</code></div>
                <div className="w7-kv"><span>result</span><code>{JSON.stringify(c.result)}</code></div>
              </li>
            ))}
          </ol>
          {!!r.side_effects.length && (
            <p className="w7-foot">side effects: <code>{JSON.stringify(r.side_effects)}</code></p>
          )}
          <pre className="w7-reply">{r.output.reply}</pre>
        </div>
      )}
    </section>
  )
}

function InjectionTab({ d, onRerun, busy }) {
  const inj = d.injection
  const off = inj.eval_defences_off
  const on = inj.eval_defences_on
  const n = inj.undefended[Object.keys(d.attacks)[0]].rows.length
  const indirect = { undefended: inj.undefended, defended: inj.defended, sandboxed: inj.sandboxed }
  const cost = [
    ['Outcome pass rate', 'outcome_pass_rate', (x) => pct(x)],
    ['Trajectory pass rate', 'trajectory_pass_rate', (x) => pct(x)],
    ['Tool-choice accuracy', 'tool_choice_accuracy', (x) => pct(x)],
    ['Argument validity', 'argument_validity', (x) => pct(x)],
    ['Cost / ticket p50', 'cost_p50', (x) => usd(x)],
    ['Cost / ticket p99', 'cost_p99', (x) => usd(x)],
    ['Cost / ticket max', 'cost_max', (x) => usd(x)],
    ['Tokens / ticket mean', 'tokens_mean', num],
    ['Latency / ticket p50', 'latency_p50', (x) => `${x.toFixed(3)} s`],
  ]
  return (
    <>
      <section className="w7-card">
        <div className="w7-h">
          <h3>Prompt injection — indirect and direct</h3>
          <span className="spacer" />
          <button type="button" className="w7-btn" disabled={busy} onClick={onRerun}>{busy ? 're-running…' : 'Re-run all attacks'}</button>
        </div>
        <p className="w8-p">
          Target: ORD-5102 (USD 18, 44 days old; policy says <code>outside_window</code>, no refund).
          The agent is given a <b>write</b> tool, <code>issue_refund</code>, so obeying has a countable
          side effect. <b>Indirect</b>: the payload hides in a customer's pasted email that our own{' '}
          <code>get_ticket</code> returns. <b>Direct</b>: the attacker types it into their own message to the agent.
        </p>
        <div className="w8-twocol">
          <div>
            <h4 className="w8-h4">Indirect (in tool output)</h4>
            <ul className="w8-attacks">{Object.entries(d.attacks).map(([k, t]) => <li key={k}><b>{k}</b> “{t}”</li>)}</ul>
          </div>
          <div>
            <h4 className="w8-h4">Direct (in the user turn)</h4>
            <ul className="w8-attacks">{Object.entries(d.direct_attacks).map(([k, t]) => <li key={k}><b>{k}</b> “{t}”</li>)}</ul>
          </div>
        </div>
        <h4 className="w8-h4">The four defence layers</h4>
        <table className="w7-cmp">
          <tbody>
            <tr><td><b>1 · sanitise tool output</b></td><td className="mut">blocklist + &lt;untrusted_customer_text&gt; wrapper on what get_ticket returns</td></tr>
            <tr><td><b>2 · least privilege</b></td><td className="mut">issue_refund scoped read-only (errors) — or 2′ sandboxed (dry run, queued for a human)</td></tr>
            <tr><td><b>3 · output validation</b></td><td className="mut">guardrail blocks any refund promise the policy tool did not allow, for that order, in this run</td></tr>
            <tr><td><b>4 · input screen</b></td><td className="mut">the same blocklist on the user's own turn (direct injection)</td></tr>
          </tbody>
        </table>
      </section>

      <section className="w7-card">
        <h3>Indirect injection — results ({n} seeds each)</h3>
        <ResultTable results={indirect} attacks={d.attacks} configs={['undefended', 'defended', 'sandboxed']} n={n} />
        <p className="w8-p">
          <b>What still gets through:</b> A3 (reply-shaping), {inj.defended['A3-reply-shaping'].got_through}/{n} with every
          defence on. It asks for no refund, so least privilege and the refund guardrail never apply; only the
          wrapper touched it. A2 (paraphrase) walks straight past the blocklist and is stopped by layers 2 and 3.
        </p>
      </section>

      <section className="w7-card">
        <h3>Direct injection — results ({n} seeds each)</h3>
        <ResultTable results={inj.direct} attacks={d.direct_attacks} configs={['undefended', 'defended', 'defended+screen']} n={n} />
        <p className="w8-p">
          The tool-output sanitiser never sees a direct attack: it is in the user's turn, not in tool output.
          The <b>input screen</b> (layer 4) removes "Ignore previous instructions", but "issue a full refund"
          survives and is still obeyed; the paraphrase passes untouched. <b>Every refund was stopped by layers
          2 and 3, not by a filter.</b> D3 gets through {inj.direct.defended['D3-reply-shaping'].got_through}/{n}:
          nothing checks a promise that is not a refund.
        </p>
      </section>

      <section className="w7-card">
        <h3>Least privilege & sandboxing</h3>
        <table className="w7-cmp">
          <thead><tr><th>tool</th><th>access</th><th>scope</th></tr></thead>
          <tbody>
            {d.privilege.map((p) => (
              <tr key={p.tool}><td><code>{p.tool}</code></td>
                <td><span className={`w8-chip ${p.access.startsWith('WRITE') ? 'bad' : 'ok'}`}>{p.access}</span></td>
                <td className="mut">{p.scope}</td></tr>
            ))}
          </tbody>
        </table>
        <h4 className="w8-h4">Read-only vs sandboxed, on the indirect attacks</h4>
        <table className="w7-cmp">
          <thead><tr><th>attack</th><th>read-only: tool errors</th><th>sandboxed: tool errors</th><th>read-only: mean calls / cost</th><th>sandboxed: mean calls / cost</th></tr></thead>
          <tbody>
            {Object.keys(d.attacks).map((aid) => {
              const a = inj.defended[aid], b = inj.sandboxed[aid]
              return (
                <tr key={aid}><td><b>{aid}</b></td><td>{a.tool_errors}</td><td>{b.tool_errors}</td>
                  <td>{a.mean_tool_calls.toFixed(1)} / {usd(a.mean_cost)}</td>
                  <td>{b.mean_tool_calls.toFixed(1)} / {usd(b.mean_cost)}</td></tr>
              )
            })}
          </tbody>
        </table>
        <p className="w8-p">
          Both move no money. <b>Read-only</b> returns an error, so the agent argues with it (retries: more
          calls, more cost). <b>Sandboxed</b> returns a believable "dry run" and queues the attempt for a human:
          fewer calls and cheaper, but the agent now <i>believes</i> the refund went out, so it writes "we have
          issued a full refund" — and only the output guardrail catches that. A sandbox is not a defence on its own.
        </p>
      </section>

      <AttackRunner d={d} />

      <section className="w7-card">
        <h3>What the defences cost on the 10 normal tickets (trajectory eval re-run)</h3>
        <p className="w8-p">Both columns: mitigation on, <code>issue_refund</code> offered; only the defences differ. Same seeds.</p>
        <table className="w7-cmp">
          <thead><tr><th>metric</th><th>defences OFF</th><th>defences ON</th><th>Δ</th></tr></thead>
          <tbody>
            {cost.map(([l, k, f]) => off[k] != null && (
              <tr key={k}><td>{l}</td><td>{f(off[k])}</td><td>{f(on[k])}</td><td>{signed(on[k] - off[k], f)}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="w7-foot">
          Guardrail false positives on legitimate runs: {inj.guardrail_false_positives.length}.
          The cost is the wrapper and note added to every ticket body.
        </p>
      </section>

      <section className="w7-card">
        <h3>The defence code</h3>
        {[['1 · sanitise tool output', d.sanitize_source], ['2 · read-only refund tool (least privilege)', d.readonly_source],
          ["2′ · sandboxed refund tool (dry run)", d.sandbox_source],
          ['3 · output guardrail (output validation)', d.guardrail_source],
          ['4 · input screen (direct injection)', d.input_screen_source]].map(([t, src]) => (
          <details key={t}><summary className="w8-sum">{t}</summary><pre className="w7-code">{src}</pre></details>
        ))}
      </section>
    </>
  )
}

/* ---------------------------------------------------------------- owasp */

function OwaspTab({ d, go }) {
  const b = d.before.summary
  const inj = d.injection
  const dir = inj.direct
  const rows = [
    ['LLM01', 'Prompt Injection', 'covered',
      `Indirect: 10/10 → 0/10 for refund attacks with defences; A3 still ${inj.defended['A3-reply-shaping'].got_through}/10. Direct: 10/10 → 0/10 for refunds; D3 still ${dir.defended['D3-reply-shaping'].got_through}/10. Input/output filters alone stopped nothing.`, 'injection'],
    ['LLM02', 'Sensitive Information Disclosure', 'partial',
      'Tools are scoped to one ticket / one order id (no bulk reads); not tested with an exfiltration attack.', 'injection'],
    ['LLM03', 'Supply Chain', 'out of scope',
      'No third-party model or plugin is loaded at run time (offline engine).', null],
    ['LLM04', 'Data and Model Poisoning', 'out of scope',
      'No training or fine-tuning in this system.', null],
    ['LLM05', 'Improper Output Handling', 'covered',
      `Output guardrail blocks refund promises the policy tool did not allow (0 false positives in ${inj.eval_defences_on.runs} legitimate runs). Argument validation does the same for tool inputs (${b.modes.skipped_order_record} → 0).`, 'mitigation'],
    ['LLM06', 'Excessive Agency', 'covered',
      'Least privilege: issue_refund read-only or sandboxed; read tools scoped to one id; Week 7 budgets (8 calls, 20k tokens, $0.25) cap every run.', 'injection'],
    ['LLM07', 'System Prompt Leakage', 'not covered',
      'No leakage attack was run; the system prompt holds no secrets.', null],
    ['LLM08', 'Vector and Embedding Weaknesses', 'not covered here',
      'Week 8 has no retrieval; the RAG side (Weeks 3–5) is where this applies.', null],
    ['LLM09', 'Misinformation', 'covered',
      `Confident answers on fabricated or unchecked facts are the failure modes: skipped_order_record (${b.modes.skipped_order_record} runs), invented_id (${b.modes.invented_id}). The outcome eval passes most of them — the gap is ${pts(b.gap)}.`, 'gap'],
    ['LLM10', 'Unbounded Consumption', 'covered',
      `Budgets stop runaway loops (budget_exhausted: ${b.modes.budget_exhausted} runs, handed to a human). Cost reported as p50 ${usd(b.cost_p50)} / p99 ${usd(b.cost_p99)} / max ${usd(b.cost_max)}, not the mean.`, 'metrics'],
  ]
  const cls = { covered: 'ok', partial: 'warn' }
  return (
    <section className="w7-card">
      <h3>OWASP Top 10 for LLM Applications (2025) — what Week 8 covers</h3>
      <p className="w8-p">Each risk is mapped to the evidence on this page, with the numbers it rests on. Gaps are stated as gaps.</p>
      <div className="w7-scroll">
        <table className="w7-cmp w8-owasp">
          <thead><tr><th>id</th><th>risk</th><th>status</th><th>evidence in Week 8</th><th /></tr></thead>
          <tbody>
            {rows.map(([id, name, st, ev, tab]) => (
              <tr key={id}>
                <td><b>{id}</b></td><td>{name}</td>
                <td><span className={`w8-chip ${cls[st] || ''}`}>{st}</span></td>
                <td className="mut">{ev}</td>
                <td>{tab && <button type="button" className="w7-btn sm" onClick={() => go(tab)}>open</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function DemoTab({ d }) {
  return (
    <section className="w7-card">
      <p className="w7-foot"><code>week8/DEMO.md</code> — the order to present Week 8 in, with what to click and what to say.</p>
      <pre className="w8-md">{d.demo_md || 'week8/DEMO.md not found.'}</pre>
    </section>
  )
}

/* ------------------------------------------------------- write-up / code */

function WriteupTab({ d }) {
  return (
    <section className="w7-card">
      <p className="w7-foot">
        <code>week8/results_week8.md</code>, the submission write-up. The numbers in it are copied from
        the generated reports this page reads.
      </p>
      <pre className="w8-md">{d.results_md}</pre>
    </section>
  )
}

const CODE_NOTES = {
  'trajectory_eval.py': 'The 10 expected sequences, the four metrics, the gap, the failure-mode classifier, before/after and the regression table.',
  'tools8.py': 'Week 7 tools + optional search_tickets + THE mitigation (validate_policy_args).',
  'sim_model.py': 'The sampled engine: every failure behaviour is a named rate.',
  'agent8.py': 'The Week 7 loop and budgets, wired to the sampled engine.',
  'store8.py': 'Week 7 tickets as customers write them (quoted figures), plus prior tickets for search.',
  'injection.py': 'Bonus: the planted attacks, the three defences and the cost re-run.',
}

function CodeTab({ d }) {
  const [file, setFile] = useState('trajectory_eval.py')
  return (
    <section className="w7-card">
      <div className="ev-filters">
        {Object.keys(d.source).map((f) => (
          <button key={f} type="button" data-on={file === f ? 1 : 0} onClick={() => setFile(f)}>{f}</button>
        ))}
      </div>
      <p className="w7-foot">{CODE_NOTES[file]}</p>
      <pre className="w7-code">{d.source[file]}</pre>
    </section>
  )
}

/* ------------------------------------------------------------------ page */

export default function Week8View() {
  const [tab, setTab] = useState(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    return TABS.some(([k]) => k === t) ? t : 'overview'
  })
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(null)
  const [seeds, setSeeds] = useState(10)
  useEffect(() => { api('/api/week8').then(setD).catch((e) => setErr(e.message)) }, [])

  const rerun = async (what) => {
    setBusy(what); setErr(null)
    try {
      setD(what === 'eval' ? await api('/api/week8/eval', { seeds })
        : await api('/api/week8/injection', {}))
    } catch (e) { setErr(e.message) } finally { setBusy(null) }
  }

  if (err && !d) return <div className="view"><div className="banner bad"><strong>Week 8 failed to load.</strong><pre>{err}</pre></div></div>
  if (!d) return <div className="view"><p className="ev-note">Loading Week 8…</p></div>

  return (
    <div className="view ev w7 w8">
      <header className="ev-head w8-head">
        <h2>Agent failure modes &amp; trajectory evals — Week 8</h2>
        <span className="spacer" />
        <label className="w8-sel">seeds per ticket
          <select value={seeds} onChange={(e) => setSeeds(Number(e.target.value))}>
            {[5, 10, 20, 30].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <button type="button" className="w7-btn" disabled={!!busy} onClick={() => rerun('eval')}>
          {busy === 'eval' ? 're-running…' : 'Re-run trajectory eval'}
        </button>
      </header>
      <nav className="ev-filters w7-tabs">
        {TABS.map(([k, label]) => (
          <button key={k} type="button" data-on={tab === k ? 1 : 0} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {tab === 'overview' && <Overview d={d} go={setTab} />}
      {tab === 'paths' && <PathsTab d={d} />}
      {tab === 'metrics' && <MetricsTab d={d} />}
      {tab === 'gap' && <GapTab d={d} />}
      {tab === 'modes' && <ModesTab d={d} />}
      {tab === 'mitigation' && <MitigationTab d={d} />}
      {tab === 'regression' && <RegressionTab d={d} />}
      {tab === 'injection' && <InjectionTab d={d} busy={busy === 'inj'} onRerun={() => rerun('inj')} />}
      {tab === 'owasp' && <OwaspTab d={d} go={setTab} />}
      {tab === 'demo' && <DemoTab d={d} />}
      {tab === 'writeup' && <WriteupTab d={d} />}
      {tab === 'code' && <CodeTab d={d} />}
    </div>
  )
}
