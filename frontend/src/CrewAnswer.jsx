import React from 'react'

/**
 * Week 9: one answer from the Responder, checked by the Verifier.
 *
 * `data` is the /api/w9/ask response. A `user` gets the answer, the verdict
 * and the source ids. An admin's response also carries `full`, the whole
 * crew run, which is rendered underneath: every tools/call with the server
 * that answered it, the context the host attached, and each claim the
 * Verifier re-fetched and checked.
 */
export function Verdict({ data }) {
  if (data.kind === 'smalltalk') {
    return <span className="pf na">CHAT</span>
  }
  if (data.kind === 'refusal') {
    return <span className="pf na">NOT COVERED</span>
  }
  return data.approved
    ? <span className="pf ok">VERIFIED · {data.verified_claims} claim{data.verified_claims === 1 ? '' : 's'}</span>
    : <span className="pf bad">PARTLY VERIFIED</span>
}

export function Sources({ ids }) {
  if (!ids?.length) return null
  return (
    <div className="sources">
      <span className="sources-title">sources</span>
      {ids.map((s) => <span key={s} className="chip">{s}</span>)}
    </div>
  )
}

function CrewTrace({ full }) {
  if (full.kind === 'smalltalk') {
    return <p className="foot">Small talk · no tools called</p>
  }
  const steps = full.responder.steps
  const tools = steps.filter((s) => s.kind === 'tool')
  const last = full.rounds[full.rounds.length - 1]
  return (
    <>
      <div className="path">
        {full.responder.context.map((c) => (
          <span key={c.uri} className="step ctx">
            ⊕ {c.uri}
          </span>
        ))}
        {tools.map((s, i) => (
          <span key={i} className={`step ${s.is_error ? 'none' : ''}`} title={s.text}>
            {s.qualified}{s.is_error ? ' ✗' : ''}
          </span>
        ))}
      </div>
      <details className="trace">
        <summary>
          Responder · {full.responder.model_turns} model turn{full.responder.model_turns === 1 ? '' : 's'} ·{' '}
          {tools.length} tool call{tools.length === 1 ? '' : 's'}
        </summary>
        <ol className="steps">
          {steps.map((s, i) => s.kind === 'model'
            ? <li key={i}><b>model</b> · {s.stop_reason}{s.tool_uses.length ? ` → ${s.tool_uses.map((u) => u.name).join(', ')}` : ''} · {s.input_tokens} in / {s.output_tokens} out</li>
            : <li key={i}><b>{s.qualified}</b> <code>{JSON.stringify(s.args)}</code> · {s.ms} ms<br />
              <span className={`res ${s.is_error ? 'bad' : ''}`}>→ {s.is_error ? 'error: ' : ''}{s.text.slice(0, 400)}</span></li>)}
        </ol>
      </details>
      <details className="trace" open={!full.approved}>
        <summary>Verifier · {full.rounds.map((r) => `round ${r.round}: ${r.verdict.summary}`).join(' · ')}</summary>
        <ol className="steps">
          {last.verdict.checks.map((c, i) => (
            <li key={i}>
              <b className={c.ok ? 'okc' : 'badc'}>{c.ok ? '✓' : '✗'}</b> {c.claim.text}
              <br /><span className="res">source {c.claim.source_id}
                {c.reasons.length ? ` · ${c.reasons.join('; ')}` : ''}</span>
            </li>
          ))}
        </ol>
      </details>
    </>
  )
}

export default function CrewAnswer({ data }) {
  return (
    <>
      <div className="res-head">
        <Verdict data={data} />
        <span className="res-meta">
          {data.kind === 'smalltalk' ? 'support agent' : `Responder → Verifier${data.rounds > 1 ? ` · ${data.rounds} rounds` : ''}`} · {(data.ms / 1000).toFixed(1)} s
        </span>
      </div>
      <div className="reply-box crew-reply">{data.answer}</div>
      <Sources ids={data.sources} />
      {data.full && <CrewTrace full={data.full} />}
    </>
  )
}
