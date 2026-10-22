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
  ['paths', 'Expected paths'],
  ['metrics', 'Metrics'],
  ['gap', 'Outcome vs path'],
  ['modes', 'Failure modes'],
  ['mitigation', 'Mitigation'],
  ['regression', 'Regression'],
  ['injection', 'Injection'],
  ['owasp', 'OWASP Top 10'],
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
        <span>{run.latency_s.toFixed(2)} s</span>
        <span>{run.llm_calls} model calls</span>
        <span>{s.steps_taken} / {s.steps_needed} steps</span>
        {run.terminated && <span className="w8-warn">budget {run.terminated.budget} hit</span>}
      </div>
      <div className="w8-modes">
        <ModeChips modes={s.modes} />
        {s.tool_errors > 0 && (
          <span className="w8-chip warn">validator rejected {s.tool_errors} call{s.tool_errors === 1 ? '' : 's'}</span>
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

function Overview({ d }) {
  const b = d.before.summary
  const a = d.after.summary
  const top = d.top_mode
  return (
    <>
      <section className="w8-hero">
        <div className="w8-tile big">
          <span>outcome − path gap</span>
          <b>{pts(b.gap)}</b>
          <i>outcome {pct(b.outcome_pass_rate)} · path {pct(b.trajectory_pass_rate)}</i>
        </div>
        <div className="w8-tile">
          <span>right answer, wrong path</span>
          <b>{b.right_answer_wrong_path} / {b.runs}</b>
        </div>
        <div className="w8-tile">
          <span>top mode · {top}</span>
          <b>{b.modes[top]} → {a.modes[top]}</b>
          <i>after mitigation</i>
        </div>
        <div className="w8-tile">
          <span>price of the mitigation</span>
          <b>{signed(a.cost_p50 - b.cost_p50, (x) => usd(x))}</b>
          <i>p50 cost / ticket ({signed((a.cost_p50 / b.cost_p50 - 1), (x) => pct(x))}), {signed(a.latency_p50 - b.latency_p50, (x) => `${x.toFixed(2)} s`)} p50 latency</i>
        </div>
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
        <h3>Expected tool sequences</h3>
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
        <h3>Exact path vs accepted set</h3>
        <table className="w7-cmp">
          <thead><tr><th>match (before)</th><th>trajectory pass</th><th>gap</th></tr></thead>
          <tbody>
            <tr><td>Exact sequence</td><td>{pct(b.naive_trajectory_pass_rate)}</td><td>{pts(b.naive_gap)}</td></tr>
            <tr><td>Accepted set</td><td className="win">{pct(b.trajectory_pass_rate)}</td><td className="win">{pts(b.gap)}</td></tr>
          </tbody>
        </table>
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
    ['Tool-choice accuracy', pct(b.tool_choice_accuracy), pct(a.tool_choice_accuracy)],
    ['Argument validity rate', pct(b.argument_validity), pct(a.argument_validity)],
    ['Step efficiency', b.step_efficiency.toFixed(3), a.step_efficiency.toFixed(3)],
    ['Step efficiency per run, p50 / max', `${b.step_efficiency_p50.toFixed(2)} / ${b.step_efficiency_max.toFixed(2)}`, `${a.step_efficiency_p50.toFixed(2)} / ${a.step_efficiency_max.toFixed(2)}`],
    ['Cost per ticket — p50', usd(b.cost_p50), usd(a.cost_p50)],
    ['Cost per ticket — p95', usd(b.cost_p95), usd(a.cost_p95)],
    ['Cost per ticket — p99', usd(b.cost_p99), usd(a.cost_p99)],
    ['Cost per ticket — MAX', usd(b.cost_max), usd(a.cost_max)],
    ['Cost per ticket — mean', usd(b.cost_mean), usd(a.cost_mean)],
    ['Tokens per ticket p50 / max', `${num(b.tokens_p50)} / ${num(b.tokens_max)}`, `${num(a.tokens_p50)} / ${num(a.tokens_max)}`],
    ['Latency per ticket p50 / max', `${b.latency_p50.toFixed(2)} s / ${b.latency_max.toFixed(2)} s`, `${a.latency_p50.toFixed(2)} s / ${a.latency_max.toFixed(2)} s`],
    ['Outcome pass rate', pct(b.outcome_pass_rate), pct(a.outcome_pass_rate)],
    ['Trajectory pass rate', pct(b.trajectory_pass_rate), pct(a.trajectory_pass_rate)],
  ]
  return (
    <>
      <section className="w7-card">
        <h3>Path metrics ({b.runs} runs)</h3>
        <table className="w7-cmp w8-metrics">
          <thead><tr><th>metric</th><th>BEFORE</th><th>AFTER</th></tr></thead>
          <tbody>
            {rows.map(([m, bv, av]) => (
              <tr key={m} className={m.includes('MAX') || m.includes('p99') ? 'w8-hl' : ''}>
                <td>{m}</td><td>{bv}</td><td>{av}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="w7-card">
        <h3>Cost per run</h3>
        <div className="w8-charts">
          <CostChart runs={d.before.runs} color={C_BEFORE} title="Before" stats={b}
            onPick={(r) => setPick({ ...r, mitigate: false })} />
          <CostChart runs={d.after.runs} color={C_AFTER} title="After" stats={a}
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
          <span>outcome − path gap ({cond})</span>
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
          <span><i className="w8-cell warn">!</i> right answer, wrong path</span>
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
        <h3>{pick.ticket_id}, seed {pick.seed}</h3>
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
  const hits = d.before.runs.filter((r) => r.modes.includes(mode))
  return (
    <>
      <section className="w7-card">
        <h3>Failure modes, ranked (before)</h3>
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
      </section>
      <section className="w7-card">
        <h3><code>{mode}</code> — {hits.length} run{hits.length === 1 ? '' : 's'} BEFORE</h3>
        <div className="w8-chips">
          {hits.length ? hits.map((r) => (
            <button key={`${r.ticket_id}${r.seed}`} type="button"
              className={`w8-chip btn ${r.outcome_pass ? 'warn' : 'bad'} ${pick === r ? 'on' : ''}`}
              
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
    ['Latency / ticket p50', b.latency_p50, a.latency_p50, (x) => `${x.toFixed(3)} s`],
    ['Latency / ticket max', b.latency_max, a.latency_max, (x) => `${x.toFixed(3)} s`],
  ]
  return (
    <>
      <section className="w8-hero">
        <div className="w8-tile big">
          <span><code>{top}</code> runs</span>
          <b>{b.modes[top]} → {a.modes[top]}</b>
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
        <h3>Before → after</h3>
        <table className="w7-cmp">
          <thead><tr><th></th><th>BEFORE</th><th>AFTER</th><th>price</th></tr></thead>
          <tbody>
            <tr className="w8-hl"><td><code>{top}</code> runs</td><td>{b.modes[top]}</td><td>{a.modes[top]}</td><td /></tr>
            <tr><td>Outcome pass rate</td><td>{pct(b.outcome_pass_rate)}</td><td>{pct(a.outcome_pass_rate)}</td><td /></tr>
            <tr><td>Tool calls rejected with an error</td><td>{b.tool_errors}</td><td>{a.tool_errors}</td><td /></tr>
            {price.map(([l, x, y, f]) => (
              <tr key={l}><td>{l}</td><td>{f(x)}</td><td>{f(y)}</td>
                <td><b>{signed(y - x, f)}</b> <span className="mut">({signed(y / x - 1, (v) => pct(v))})</span></td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="w7-card">
        <h3>TCK-7001 seed 2</h3>
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
    else if (x === 0 && y > 0) { v = 'NEW'; cls = 'bad' }
    else if (y > x) { v = 'WORSE'; cls = 'bad' }
    else if (y < x) { v = 'better (side effect)'; cls = 'ok' }
    else { v = 'unchanged'; cls = '' }
    return { m, x, y, v, cls }
  })
  const worse = rows.filter((r) => r.cls === 'bad' && r.m !== top)
  return (
    <section className="w7-card">
      <h3>Per-mode counts, before → after</h3>
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
          ? <>Worse or new: {worse.map((r) => <code key={r.m}>{r.m} </code>)}</>
          : <>No mode got worse.</>}
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
            {v.sandboxed && <span className="w8-chip warn">sandboxed</span>}
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
          <h3>Prompt injection</h3>
          <span className="spacer" />
          <button type="button" className="w7-btn" disabled={busy} onClick={onRerun}>{busy ? 're-running…' : 'Re-run all attacks'}</button>
        </div>
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
      </section>

      <section className="w7-card">
        <h3>Indirect injection ({n} seeds each)</h3>
        <ResultTable results={indirect} attacks={d.attacks} configs={['undefended', 'defended', 'sandboxed']} n={n} />
      </section>

      <section className="w7-card">
        <h3>Direct injection ({n} seeds each)</h3>
        <ResultTable results={inj.direct} attacks={d.direct_attacks} configs={['undefended', 'defended', 'defended+screen']} n={n} />
      </section>

      <section className="w7-card">
        <h3>Tool access</h3>
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
        <h4 className="w8-h4">Read-only vs sandboxed</h4>
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
      </section>

      <AttackRunner d={d} />

      <section className="w7-card">
        <h3>Defence cost on normal tickets</h3>
        <table className="w7-cmp">
          <thead><tr><th>metric</th><th>defences OFF</th><th>defences ON</th><th>Δ</th></tr></thead>
          <tbody>
            {cost.map(([l, k, f]) => off[k] != null && (
              <tr key={k}><td>{l}</td><td>{f(off[k])}</td><td>{f(on[k])}</td><td>{signed(on[k] - off[k], f)}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="w7-foot">
          Guardrail false positives: {inj.guardrail_false_positives.length}
        </p>
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
      `Indirect: 10/10 → 0/10 for refund attacks with defences; A3 still ${inj.defended['A3-reply-shaping'].got_through}/10. Direct: 10/10 → 0/10 for refunds; D3 still ${dir.defended['D3-reply-shaping'].got_through}/10.`, 'injection'],
    ['LLM02', 'Sensitive Information Disclosure', 'partial',
      'Tools are scoped to one ticket / one order id (no bulk reads); not tested with an exfiltration attack.', 'injection'],
    ['LLM03', 'Supply Chain', 'out of scope',
      'No third-party model or plugin loaded at run time.', null],
    ['LLM04', 'Data and Model Poisoning', 'out of scope',
      'No training or fine-tuning in this system.', null],
    ['LLM05', 'Improper Output Handling', 'covered',
      `Output guardrail blocks refund promises the policy tool did not allow (0 false positives in ${inj.eval_defences_on.runs} legitimate runs). Argument validation does the same for tool inputs (${b.modes.skipped_order_record} → 0).`, 'mitigation'],
    ['LLM06', 'Excessive Agency', 'covered',
      'Least privilege: issue_refund read-only or sandboxed; read tools scoped to one id; budgets (8 calls, 20k tokens, $0.25) cap every run.', 'injection'],
    ['LLM07', 'System Prompt Leakage', 'not covered',
      'No leakage attack was run; the system prompt holds no secrets.', null],
    ['LLM08', 'Vector and Embedding Weaknesses', 'not covered here',
      'No retrieval in this agent.', null],
    ['LLM09', 'Misinformation', 'covered',
      `skipped_order_record (${b.modes.skipped_order_record} runs), invented_id (${b.modes.invented_id}); gap ${pts(b.gap)}.`, 'gap'],
    ['LLM10', 'Unbounded Consumption', 'covered',
      `budget_exhausted: ${b.modes.budget_exhausted} runs. Cost p50 ${usd(b.cost_p50)} / p99 ${usd(b.cost_p99)} / max ${usd(b.cost_max)}.`, 'metrics'],
  ]
  const cls = { covered: 'ok', partial: 'warn' }
  return (
    <section className="w7-card">
      <h3>OWASP Top 10 for LLM Applications (2025)</h3>
      <div className="w7-scroll">
        <table className="w7-cmp w8-owasp">
          <thead><tr><th>id</th><th>risk</th><th>status</th><th>evidence</th><th /></tr></thead>
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

  if (err && !d) return <div className="view"><div className="banner bad"><strong>Failed to load.</strong><pre>{err}</pre></div></div>
  if (!d) return <div className="view"><p className="ev-note">Loading…</p></div>

  return (
    <div className="view ev w7 w8">
      <header className="ev-head w8-head">
        <h2>Path-checked agent</h2>
        <span className="spacer" />
        <label className="w8-sel">seeds per ticket
          <select value={seeds} onChange={(e) => setSeeds(Number(e.target.value))}>
            {[5, 10, 20, 30].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <button type="button" className="w7-btn" disabled={!!busy} onClick={() => rerun('eval')}>
          {busy === 'eval' ? 're-running…' : 'Re-run eval'}
        </button>
      </header>
      <nav className="ev-filters w7-tabs">
        {TABS.map(([k, label]) => (
          <button key={k} type="button" data-on={tab === k ? 1 : 0} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>
      {err && <div className="banner bad"><pre>{err}</pre></div>}
      {tab === 'overview' && <Overview d={d} />}
      {tab === 'paths' && <PathsTab d={d} />}
      {tab === 'metrics' && <MetricsTab d={d} />}
      {tab === 'gap' && <GapTab d={d} />}
      {tab === 'modes' && <ModesTab d={d} />}
      {tab === 'mitigation' && <MitigationTab d={d} />}
      {tab === 'regression' && <RegressionTab d={d} />}
      {tab === 'injection' && <InjectionTab d={d} busy={busy === 'inj'} onRerun={() => rerun('inj')} />}
      {tab === 'owasp' && <OwaspTab d={d} go={setTab} />}
    </div>
  )
}
