import { FanoutArms } from './Week10View.jsx'
import React, { useEffect, useRef } from 'react'
import CrewAnswer from './CrewAnswer.jsx'

const STAGE = {
  retrieving: 'searching the knowledge base…',
  generating: 'composing a grounded answer…',
  answering: 'writing verified claims…',
  refusing: 'no verifiable answer — writing the refusal…',
}

function Trace({ retrieval }) {
  if (!retrieval) return null
  return (
    <details className="trace">
      <summary>
        retrieved {retrieval.hits.length} chunk
        {retrieval.hits.length === 1 ? '' : 's'} in {retrieval.ms} ms
      </summary>
      <ol>
        {retrieval.hits.map((h) => (
          <li key={h.chunk_id}>
            <div className="cite">{h.chunk_id}</div>
            <pre>{h.text}</pre>
          </li>
        ))}
      </ol>
    </details>
  )
}

const W6_CHECK = {
  ticket_id_echoed: 'ticket ID',
  refund_amount_numeric: 'refund figure',
  escalation_tag_when_priority: 'escalation tag',
  no_refund_outside_window: '30-day window',
}

function TraceLink({ url }) {
  return url
    ? <a className="trace-link" href={url} target="_blank" rel="noreferrer">Langfuse trace ↗</a>
    : <span className="trace-link off">not traced</span>
}

function Verdict({ v }) {
  if (!v) return <span className="vd none">no label</span>
  return <span className={`vd ${v === 'RESOLVED' ? 'yes' : 'no'}`}>
    {v === 'RESOLVED' ? 'RESOLVED' : 'NOT RESOLVED'}</span>
}

/** Week 6: the drafted ticket reply, graded by the chosen judge. */
function Week6Answer({ m }) {
  const d = m.data
  const judgeName = d.judge === 'judge_v1' ? 'Judge v1' : 'Judge v2'
  return (
    <>
      <div className="res-head">
        <span className={`pf ${d.passed ? 'ok' : 'bad'}`}>{d.passed ? 'PASS' : 'FAIL'}</span>
        <span className="res-meta">
          {d.case_id === 'live' ? 'new question — not in the eval set' : `eval case ${d.case_id}`}
          {d.replay_verbatim ? ' · regression, replayed verbatim' : ''}
          {' · '}{d.ticket.ticket_id} · {d.ticket.tier} · day {d.ticket.days_since_purchase}
          {d.ticket.refund_requested ? ' · refund requested' : ''}
        </span>
        <span className="spacer" />
        <TraceLink url={d.trace_url} />
      </div>
      <div className="grade-row">
        <div className="grade sel">
          <span className="gl">{judgeName}</span><Verdict v={d.verdict} />
          <span className="gwhy">{d.reasoning}</span>
        </div>
        {d.case_id !== 'live' && (
          <div className="grade">
            <span className="gl">Human</span><Verdict v={d.human} />
            {d.human && <span className={`agree ${d.human === d.verdict ? 'yes' : 'no'}`}>
              {d.human === d.verdict ? 'judge agrees' : 'judge disagrees'}</span>}
          </div>
        )}
      </div>
      <div className="checks">
        {Object.entries(d.checks).map(([name, r]) => (
          <span key={name} title={r.detail || r.status}
            className={`chk ${r.status === 'PASS' ? 'ok' : r.status === 'FAIL' ? 'bad' : 'na'}`}>
            {r.status === 'PASS' ? '✓' : r.status === 'FAIL' ? '✕' : '–'} {W6_CHECK[name]}
          </span>
        ))}
      </div>
      <pre className="reply-box">{d.reply}</pre>
      {d.claims?.length > 0 && (
        <div className="sources">
          <p className="sources-title">Cited knowledge base sources</p>
          {[...new Map(d.claims.map((c) => [c.chunk_id, c])).values()].map((c) => (
            <a className="chip" key={c.chunk_id} href={`/api/chunk/${c.chunk_id}`}
              target="_blank" rel="noreferrer">{c.article_id}{c.section ? ` — ${c.section}` : ''}</a>
          ))}
        </div>
      )}
    </>
  )
}

const usd = (x) => `$${Number(x).toFixed(4)}`

/** Week 7: one ticket through the agent or the fixed workflow. */
function Week7Answer({ m }) {
  const d = m.data
  const o = d.output
  return (
    <>
      <div className="res-head">
        {d.grade
          ? <span className={`pf ${d.grade.passed ? 'ok' : 'bad'}`}>{d.grade.passed ? 'PASS' : 'FAIL'}</span>
          : <span className="pf na">NEW TICKET</span>}
        <span className="res-meta">
          {d.ticket.ticket_id} · {d.ticket.customer_tier} · {d.ticket.request_type.replace('_', ' ')}
          {' · orders '}{d.ticket.order_ids.length ? d.ticket.order_ids.join(', ') : 'none named'}
          {!d.known ? ' · no answer key, so not graded' : ''}
        </span>
        <span className="spacer" />
        <TraceLink url={d.trace_url} />
      </div>
      <div className="decision">
        <div><span className="gl">decision</span><b>{o.decision ? o.decision.replaceAll('_', ' ') : 'handed to a human'}</b></div>
        <div><span className="gl">refund</span><b>{o.refund_amount_usd != null ? `USD ${o.refund_amount_usd.toFixed(2)} · ${o.refund_order_id}` : '—'}</b></div>
        <div><span className="gl">escalate</span><b className={o.escalate ? 'warn' : ''}>{o.escalate ? 'yes' : 'no'}</b></div>
      </div>
      {d.grade?.mismatches?.length > 0 && (
        <p className="miss">
          {d.grade.mismatches.map((x) => (
            <span key={x.field}><b>{x.field}</b>: expected <code>{String(x.expected)}</code>, got <code>{String(x.got)}</code></span>
          ))}
        </p>
      )}
      <div className="path">
        {d.path.map((t, i) => <span key={i} className="step">{t}</span>)}
        {!d.path.length && <span className="step none">no tools</span>}
      </div>
      <pre className="reply-box">{o.reply}</pre>
      <details className="trace">
        <summary>{d.steps.length} steps · {d.llm_calls} model call{d.llm_calls === 1 ? '' : 's'}</summary>
        <ol className="steps">
          {d.steps.map((s, i) => s.kind === 'llm'
            ? <li key={i}><b>model call</b> · {s.stop_reason} · {s.input_tokens} in / {s.output_tokens} out · {usd(s.cost_usd)}</li>
            : <li key={i}><b>{s.name}</b> <code>{JSON.stringify(s.args)}</code><br /><span className="res">→ {JSON.stringify(s.result)}</span></li>)}
        </ol>
      </details>
      <div className="foot">
        {d.total_tokens.toLocaleString()} tokens · {usd(d.cost_usd)} · {d.latency_s.toFixed(2)} s
      </div>
    </>
  )
}


/** Week 8: one ticket through the sampled agent, its PATH scored as well. */
function Week8Answer({ m }) {
  const d = m.data
  const o = d.output
  const s = d.score
  const accepted = (d.accepted || []).map((q) => JSON.stringify(q))
  return (
    <>
      <div className="res-head">
        {s ? (
          <>
            <span className={`pf ${s.outcome_pass ? 'ok' : 'bad'}`}>outcome {s.outcome_pass ? 'PASS' : 'FAIL'}</span>
            <span className={`pf ${s.trajectory_pass ? 'ok' : 'bad'}`}>trajectory {s.trajectory_pass ? 'PASS' : 'FAIL'}</span>
          </>
        ) : <span className="pf na">NEW TICKET</span>}
        <span className="res-meta">
          {d.ticket.ticket_id} · seed {d.seed} · mitigation {d.mitigate ? 'on' : 'off'}
          {!d.known ? ' · no expected path, so not scored' : ''}
        </span>
      </div>
      {s && s.outcome_pass && !s.trajectory_pass && (
        <p className="miss"><span><b>Right answer, wrong path.</b></span></p>
      )}
      {s && (
        <p className="miss">
          <span><b>failure modes</b>: {s.modes.length ? s.modes.join(', ') : 'none'}</span>
          <span><b>steps</b>: {s.steps_taken} taken / {s.steps_needed} needed</span>
          <span><b>valid args</b>: {s.valid_args}/{s.n_calls}</span>
        </p>
      )}
      <div className="decision">
        <div><span className="gl">decision</span><b>{o.decision ? o.decision.replaceAll('_', ' ') : 'handed to a human'}</b></div>
        <div><span className="gl">refund</span><b>{o.refund_amount_usd != null ? `USD ${o.refund_amount_usd.toFixed(2)} · ${o.refund_order_id}` : '—'}</b></div>
        <div><span className="gl">escalate</span><b className={o.escalate ? 'warn' : ''}>{o.escalate ? 'yes' : 'no'}</b></div>
      </div>
      <div className="path">
        {d.tool_calls.map((c, i) => (
          <span key={i} className={`step ${c.error ? 'none' : ''}`}
            title={c.key ? `${c.key[1]} · ${c.error ? 'rejected' : c.valid ? 'valid' : 'NOT grounded'}` : ''}>
            {c.name}{c.key ? `(${c.key[1]})` : ''}{c.error ? ' ✗' : c.valid === false ? ' ⚠' : ''}
          </span>
        ))}
      </div>
      {s && (
        <details className="trace">
          <summary>accepted path{d.accepted.length > 1 ? `s (${d.accepted.length}, any one is correct)` : ''} — taken path {accepted.includes(JSON.stringify(s.keys)) ? 'matches' : 'matches none'}</summary>
          <ol className="steps">
            {d.accepted.map((q, i) => <li key={i}>{q.map((k) => `${k[0]}(${k[1]})`).join(' → ')}</li>)}
          </ol>
        </details>
      )}
      <pre className="reply-box">{o.reply}</pre>
      <details className="trace">
        <summary>{d.tool_calls.length} tool calls · {d.llm_calls} model calls</summary>
        <ol className="steps">
          {d.tool_calls.map((c, i) => <li key={i}><b>{c.name}</b> <code>{JSON.stringify(c.args)}</code><br /><span className="res">→ {JSON.stringify(c.result)}</span></li>)}
        </ol>
      </details>
      <div className="foot">
        {d.total_tokens.toLocaleString()} tokens · {usd(d.cost_usd)} · {d.latency_s.toFixed(2)} s
      </div>
    </>
  )
}

const WAIT = {
  week6: 'drafting the reply and running the judge…',
  week7: 'resolving the ticket…',
  week8: 'running the ticket and scoring its path…',
  week9: 'writing the answer and checking it…',
  week10: 'running the selected agents…',
}

/** Triage squad: the same question through both arms, with each bill. */
function SquadAnswer({ d }) {
  return <FanoutArms d={d} />
}

function Answer({ m }) {
  if (['week6', 'week7', 'week8', 'week9', 'week10'].includes(m.kind)) {
    return (
      <div className={`msg bot ${m.error ? 'failed' : ''}`}>
        <span className="ftag">{m.filter}</span>
        {m.data && (m.kind === 'week6' ? <Week6Answer m={m} />
          : m.kind === 'week9' ? <CrewAnswer data={m.data} />
          : m.kind === 'week10' ? <SquadAnswer d={m.data} />
            : m.kind === 'week8' ? <Week8Answer m={m} /> : <Week7Answer m={m} />)}
        {m.error && (
          <div className="claim">
            <div className="claim-text"><strong>Request failed.</strong></div>
            <pre className="cite">{m.error}</pre>
          </div>
        )}
        {m.streaming && <div className="stage"><i className="led-dot" />{WAIT[m.kind]}</div>}
        {m.stopped && <div className="foot">stopped</div>}
      </div>
    )
  }
  return <RagAnswer m={m} />
}

function RagAnswer({ m }) {
  const refused = m.done && !m.done.answered
  const sources = m.done
    ? [...new Map(m.claims.filter((c) => c.chunk_id)
        .map((c) => [c.article_id || c.chunk_id, c])).values()]
    : []

  return (
    <div className={`msg bot ${refused ? 'refused' : ''} ${m.error ? 'failed' : ''}`}>
      {m.filter && <span className="ftag">{m.filter}</span>}
      <Trace retrieval={m.retrieval} />

      {m.claims.map((c) => (
        <div className="claim" key={c.index}>
          <div className="claim-text">{c.text}</div>
          {c.chunk_id && (
            <div className="cite">
              ↳ <a href={`/api/chunk/${c.chunk_id}`} target="_blank" rel="noreferrer">
                {c.chunk_id}
              </a>
            </div>
          )}
        </div>
      ))}

      {m.refusal && (
        <div className="claim">
          <div className="claim-text"><strong>No grounded answer.</strong></div>
          <div className="claim-text">{m.refusal}</div>
        </div>
      )}

      {m.error && (
        <div className="claim">
          <div className="claim-text"><strong>Request failed.</strong></div>
          <pre className="cite">{m.error}</pre>
        </div>
      )}

      {sources.length > 0 && (
        <div className="sources">
          <p className="sources-title">Cited knowledge base sources</p>
          {sources.map((c) => (
            <span className="chip" key={c.chunk_id}>
              {c.article_id || c.chunk_id}{c.section ? ` — ${c.section}` : ''}
            </span>
          ))}
        </div>
      )}

      {m.streaming && (
        <div className="stage"><i className="led-dot" />{STAGE[m.stage] || 'working…'}</div>
      )}

      {m.done && (
        <div className="foot">
          {m.done.timings.retrieval_ms + m.done.timings.generation_ms} ms
        </div>
      )}
      {m.stopped && <div className="foot">stopped</div>}
    </div>
  )
}

const EMPTY = {
  week6: 'Ticket reply',
  week7: 'Refund agent',
  week8: 'Path-checked agent',
  week9: 'Support crew',
  week10: 'Triage squad',
}

export default function Chat({ messages, health, week }) {
  const bottom = useRef(null)
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  if (!messages.length) {
    return (
      <div className="view">
        <div className="empty">
          <h2>{EMPTY[week] || 'Ask about the billing migration'}</h2>
          <p>Pick a question on the left, or type below.</p>
          <div className="hints">
            <span className="hint-chip">
              <b>{health?.indexed_chunks ?? '—'}</b> chunks indexed
            </span>
            <span className="hint-chip">
              <b>{health?.articles_indexed ?? '—'}</b> shipped
              {health?.uploaded_documents
                ? <> · <b>{health.uploaded_documents}</b> yours</> : null}
            </span>
          </div>
        </div>
        <div ref={bottom} />
      </div>
    )
  }

  return (
    <div className="view">
      <div className="thread">
        {messages.map((m, i) =>
          m.role === 'user'
            ? <div className="msg you" key={i}>{m.text}</div>
            : <Answer m={m} key={i} />)}
        <div ref={bottom} />
      </div>
    </div>
  )
}
