import React, { useEffect, useState } from 'react'

/**
 * Week 6: the judge validation, as a page.
 *
 * Everything shown here comes from /api/eval_week6, which reads the files
 * week6/run_week6.py writes and runs week6/assertions.py itself. Nothing is
 * recomputed in the browser, so this page and the terminal table cannot
 * disagree about a number.
 *
 * The page leads with the two figures the whole week is about — agreement
 * before and after — and puts kappa immediately beside them, because on a set
 * where 22 of 25 replies are unresolved, 88% agreement is mostly a judge
 * guessing the majority class.
 */

const MODE_LABEL = {
  mode_1: 'filter hid the answer',
  mode_2: 'fixes nobody asked for',
  mode_3: 'refused on wording',
  mode_4: 'confident, off-topic',
  mode_5: 'instruction, wrong article',
  no_failure: 'no failure observed',
}
const MODE_CLS = {
  mode_1: 'cls-retrieval', mode_2: 'cls-generation', mode_3: 'cls-guardrail',
  mode_4: 'cls-hallucination', mode_5: 'cls-generation', no_failure: 'cls-clean',
}
const A_LABEL = {
  ticket_id_echoed: 'ticket ID',
  refund_amount_numeric: 'refund figure',
  escalation_tag_when_priority: 'escalation tag',
  no_refund_outside_window: '30-day window',
}

function Verdict({ v }) {
  if (!v) return <span className="ev-v none">not judged</span>
  return (
    <span className={`ev-v ${v === 'RESOLVED' ? 'yes' : 'no'}`}>
      {v === 'RESOLVED' ? 'RESOLVED' : 'NOT RESOLVED'}
    </span>
  )
}

const GRADER_KEYS = ['judge_v1', 'judge_v2', 'human']
const GRADER_SHORT = { judge_v1: 'Judge v1', judge_v2: 'Judge v2', human: 'Human' }

function Case({ c, onAsk, grader }) {
  const [open, setOpen] = useState(false)
  return (
    <li className={c.passed ? 'ev-case pass' : 'ev-case fail'}>
      <div className="ev-case-top">
        <span className="ev-cid">{c.case_id}</span>
        <span className={`ev-tag ${MODE_CLS[c.mode]}`}>{MODE_LABEL[c.mode]}</span>
        {c.replay_verbatim && (
          <span className="ev-tag verbatim" title={`Replayed verbatim from ${c.source_trace}`}>
            regression · {c.source_trace}
          </span>
        )}
        {c.tier === 'Priority' && <span className="ev-tag prio">Priority</span>}
        <span className="ev-meta">
          {c.ticket_id} · day {c.days_since_purchase}
          {c.refund_requested
            ? ` · refund ${c.refund_amount_usd != null ? `USD ${c.refund_amount_usd.toFixed(2)}` : 'requested'}`
            : ' · no refund asked'}
          {' · area '}{c.product_area || 'all'}
        </span>
        <button type="button" className="ev-ask"
          onClick={() => onAsk(c.question, c.product_area || '')}>
          re-run
        </button>
      </div>

      {/* The question is the case. It is what the customer actually wrote and
          what every verdict below is a verdict about, so it leads. */}
      <p className="ev-q">{c.question}</p>

      <div className="ev-checks">
        {Object.entries(c.checks).map(([name, r]) => (
          <span key={name}
            className={`ev-chk ${r.status === 'PASS' ? 'ok' : r.status === 'FAIL' ? 'bad' : 'na'}`}
            title={r.detail || `${A_LABEL[name]}: ${r.status}`}>
            {r.status === 'PASS' ? '✓' : r.status === 'FAIL' ? '✕' : '–'} {A_LABEL[name]}
          </span>
        ))}
      </div>

      <div className="ev-verdicts">
        <div className={grader === 'human' ? 'ev-sel' : ''}>
          <span className="ev-vl">human</span><Verdict v={c.human} />
        </div>
        <div className={grader === 'judge_v1' ? 'ev-sel' : ''}>
          <span className="ev-vl">judge v1</span><Verdict v={c.judge_v1} />
          {c.human && (
            <span className={`ev-agree ${c.agree_v1 ? 'yes' : 'no'}`}>
              {c.agree_v1 ? 'agrees' : 'disagrees'}
            </span>
          )}
        </div>
        <div className={grader === 'judge_v2' ? 'ev-sel' : ''}>
          <span className="ev-vl">judge v2</span><Verdict v={c.judge_v2} />
          {c.human && (
            <span className={`ev-agree ${c.agree_v2 ? 'yes' : 'no'}`}>
              {c.agree_v2 ? 'agrees' : 'disagrees'}
            </span>
          )}
        </div>
        {c.ragas && (
          <div className="ev-ragas"
            title="RAGAS faithfulness / context precision (policy-backed case)">
            <span className="ev-vl">ragas</span>
            <span className="ev-num">faith {c.ragas.faithfulness?.toFixed(2) ?? '—'}</span>
            <span className="ev-num">ctx {c.ragas.context_precision?.toFixed(2) ?? '—'}</span>
            {!!c.ragas.wrong_section?.length && (
              <span className="ev-num wrong">wrong policy section</span>
            )}
          </div>
        )}
      </div>

      {!c.judged && (
        <p className="ev-note">Not judged — {c.not_judged_because}</p>
      )}
      {grader !== 'human' && c.human && c.grader_verdict !== c.human && (
        <p className="ev-note dis">
          <b>Disagreement.</b> Human: {c.human_why} <br />
          <b>{GRADER_SHORT[grader]}:</b> {c[`${grader}_why`]}
        </p>
      )}

      <button type="button" className="ev-more" onClick={() => setOpen(!open)}>
        {open ? 'hide drafted reply' : 'show drafted reply'}
      </button>
      {open && <pre className="ev-reply">{c.reply}</pre>}
    </li>
  )
}

export default function EvalView({ onAsk }) {
  const [filter, setFilter] = useState('all')
  const [mode, setMode] = useState(null)
  // Whose verdict decides pass/fail. Every number below is recomputed by the
  // backend for the chosen grader, and each switch is traced to Langfuse.
  const [grader, setGrader] = useState('judge_v2')
  const [evals, setEvals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    setLoading(true)
    fetch(`/api/eval_week6?grader=${grader}`)
      .then((r) => r.ok ? r.json() : r.text().then((t) => { throw new Error(t) }))
      .then((d) => { if (live) { setEvals(d); setError(null) } })
      .catch((e) => { if (live) setError(String(e.message || e)) })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [grader])

  if (!evals && loading) {
    return <div className="view"><p className="ev-note">Loading Week 6 eval…</p></div>
  }
  if (!evals || !evals.ok) {
    return (
      <div className="view">
        <div className="empty">
          <h2>No Week 6 eval found</h2>
          <p>
            Run it with <code>.venv-test/bin/python week6/run_week6.py</code>,
            then reload.{error && <><br />{error}</>}
          </p>
        </div>
      </div>
    )
  }

  const { cases, modes, assertions, summary: s } = evals
  const shown = cases.filter((c) => {
    if (mode && c.mode !== mode) return false
    if (filter === 'disagree') return c.human && c.grader_verdict !== c.human
    if (filter === 'moved') return c.judge_v1 !== c.judge_v2
    if (filter === 'failed') return !c.passed
    if (filter === 'regression') return c.replay_verbatim
    return true
  })

  return (
    <div className="view ev">
      <header className="ev-head">
        <div>
          <h2>Judge validation — Week 6</h2>
          <p className="ev-sub">
            {s.n_cases} cases, {s.n_verbatim} replayed verbatim from real failed
            traces. {s.n_judged} hand-labelled blind on{' '}
            {new Date(s.labelled_at).toLocaleString()}, before the judge was
            ever run. Judge engine <b>{s.engine}</b> ({s.judge_model}).
          </p>
        </div>
        <div className="ev-grader">
          <span className="ev-k">grade with</span>
          <div className="ev-seg" role="radiogroup" aria-label="Grader">
            {GRADER_KEYS.map((g) => (
              <button key={g} type="button" role="radio"
                aria-checked={grader === g} data-on={grader === g ? 1 : 0}
                disabled={loading}
                onClick={() => {
                  if (g === 'human' && filter === 'disagree') setFilter('all')
                  setGrader(g)
                }}>
                {GRADER_SHORT[g]}
              </button>
            ))}
          </div>
          {evals.trace_url
            ? <a className="ev-trace" href={evals.trace_url} target="_blank"
              rel="noreferrer">
              {loading ? 'grading…' : `Langfuse trace for ${GRADER_SHORT[grader]} ↗`}
            </a>
            : <span className="ev-trace off">tracing off — not recorded</span>}
        </div>
      </header>

      <div className="ev-band">
        <div className="ev-stat big">
          <span className="ev-k">agreement</span>
          <b>{s.agreement_before}% <i>→</i> {s.agreement_after}%</b>
          <span className="ev-sub2">judge vs human, {s.n_judged} labels</span>
        </div>
        <div className="ev-stat big">
          <span className="ev-k">Cohen's kappa</span>
          <b>{s.kappa_before} <i>→</i> {s.kappa_after}</b>
          <span className="ev-sub2">
            the honest one: {s.human_resolved_rate}% of replies are RESOLVED, so
            a judge that always says NOT_RESOLVED already scores{' '}
            {(100 - s.human_resolved_rate).toFixed(0)}%
          </span>
        </div>
        <div className="ev-stat">
          <span className="ev-k">assertions vs judged criteria</span>
          <b>{s.n_assertions} <i>/</i> {s.n_judged_criteria}</b>
          <span className="ev-sub2">
            4 criteria moved out of the judge into code, 1 deleted, 1 kept and
            made binary
          </span>
        </div>
        <div className="ev-stat big sel">
          <span className="ev-k">cases passing · {GRADER_SHORT[grader]}</span>
          <b>{s.pass_total}<i>/</i>{s.n_cases}</b>
          <span className="ev-sub2">
            every assertion passes and {grader === 'human'
              ? 'the human label says RESOLVED'
              : `${GRADER_SHORT[grader]} says RESOLVED`} (unjudged cases pass
            on assertions alone)
          </span>
        </div>
        <div className="ev-stat">
          <span className="ev-k">{GRADER_SHORT[grader]} vs human</span>
          <b>{grader === 'human' ? 'reference' : `${evals.grader_agreement}%`}</b>
          <span className="ev-sub2">
            {grader === 'human'
              ? 'the hand labels are the yardstick the judges are scored against'
              : `agreement on the ${s.n_judged} hand-labelled cases; ${evals.grader_resolved} RESOLVED verdicts`}
          </span>
        </div>
      </div>

      <div className="ev-cols">
        <section>
          <h3>Pass rate by failure mode</h3>
          <div className="ev-modes">
            {modes.map((m) => {
              const pct = (m.pass / m.n) * 100
              return (
                <button key={m.mode} type="button"
                  className={`ev-mrow ${mode === m.mode ? 'on' : ''}`}
                  aria-pressed={mode === m.mode}
                  onClick={() => setMode(mode === m.mode ? null : m.mode)}>
                  <span className={`ev-mname ${MODE_CLS[m.mode]}`}>
                    <b>{m.mode.replace('_', ' ')}</b>
                    <i>{MODE_LABEL[m.mode]}</i>
                  </span>
                  <span className="ev-mtrack"
                    title={`${m.pass} of ${m.n} cases pass — ${pct.toFixed(0)}%`}>
                    <span className={`ev-mfill${pct === 0 ? ' zero' : ''}`}
                      style={{ width: pct === 0 ? '100%' : `${pct}%` }} />
                  </span>
                  <span className="ev-mnum">{m.pass}/{m.n}</span>
                </button>
              )
            })}
          </div>
          {grader === 'judge_v2' ? (
            <p className="ev-warn">
              <b>mode 5 reads 100%.</b> That row is one case, and it passes only
              because the judge got it wrong. Switch the grader to Human and it
              drops to 0/1 — a pass rate computed from a judge inherits every
              blind spot that judge has.
            </p>
          ) : (
            <p className="ev-warn">
              Graded by <b>{GRADER_SHORT[grader]}</b>. Compare with the other
              graders to see which rows move: a row that changes is a case the
              graders disagree on.
            </p>
          )}
        </section>

        <section>
          <h3>Deterministic assertions</h3>
          <table className="ev-atable">
            <thead>
              <tr><th>check</th><th>PASS</th><th>FAIL</th><th>n/a</th></tr>
            </thead>
            <tbody>
              {assertions.map((a) => (
                <tr key={a.name} className={a.FAIL ? 'has-fail' : ''}>
                  <td>{A_LABEL[a.name]}</td>
                  <td className="ok">{a.PASS}</td>
                  <td className={a.FAIL ? 'bad' : ''}>{a.FAIL}</td>
                  <td className="mut">{a['n/a']}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="ev-warn">
            <b>The 30-day window check is 0 PASS / 7 FAIL.</b> The drafter has
            no date check at all — every ticket past day 30 that asked for a
            refund got one promised, including day 61. No judge had ever
            flagged it.
          </p>
        </section>
      </div>

      <div className="ev-listhead">
        <div className="ev-filters">
          {[['all', `all ${cases.length}`],
          ...(grader === 'human' ? [] : [['disagree', `${GRADER_SHORT[grader]} disagrees with human`]]),
          ['moved', 'verdict changed v1 → v2'],
          ['failed', 'failing'],
          ['regression', 'regression cases']].map(([k, label]) => (
            <button key={k} type="button" data-on={filter === k ? 1 : 0}
              onClick={() => setFilter(k)}>
              {label}
            </button>
          ))}
        </div>
        {mode && (
          <button type="button" className="ev-clear" onClick={() => setMode(null)}>
            clear {mode.replace('_', ' ')} filter
          </button>
        )}
      </div>

      <ol className="ev-cases">
        {shown.map((c) => <Case key={c.case_id} c={c} onAsk={onAsk} grader={grader} />)}
      </ol>
      {!shown.length && <p className="ev-note">No cases match that filter.</p>}
    </div>
  )
}
