import React, { useEffect, useRef } from 'react'

const STAGE = {
  retrieving: 'searching the knowledge base…',
  generating: 'composing a grounded answer…',
  answering: 'writing verified claims…',
  refusing: 'no verifiable answer — writing the refusal…',
}

function Trace({ retrieval, mode }) {
  if (!retrieval) return null
  return (
    <details className="trace">
      <summary>
        retrieved {retrieval.hits.length} chunk
        {retrieval.hits.length === 1 ? '' : 's'} in {retrieval.ms} ms
        {mode === 'week4' ? ' · reranked' : ' · fused score only'}
      </summary>
      <ol>
        {retrieval.hits.map((h) => (
          <li key={h.chunk_id}>
            <div className="score">
              #{h.rank} fused {h.score} · dense {h.dense} · bm25 {h.bm25}
              {h.rerank_score != null ? ` · rerank ${h.rerank_score}` : ''}
            </div>
            <div className="cite">{h.chunk_id}</div>
            <pre>{h.text}</pre>
          </li>
        ))}
      </ol>
    </details>
  )
}

function Answer({ m }) {
  const refused = m.done && !m.done.answered
  const sources = m.done
    ? [...new Map(m.claims.filter((c) => c.chunk_id)
        .map((c) => [c.article_id || c.chunk_id, c])).values()]
    : []

  return (
    <div className={`msg bot ${refused ? 'refused' : ''} ${m.error ? 'failed' : ''}`}>
      <Trace retrieval={m.retrieval} mode={m.meta?.mode} />

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
          {m.meta?.engine} · {m.meta?.mode_label} · top {m.meta?.k} · retrieval{' '}
          {m.done.timings.retrieval_ms} ms · generation {m.done.timings.generation_ms} ms
          {m.done.rejected_claims?.length
            ? ` · ${m.done.rejected_claims.length} claim(s) dropped by verify()`
            : ''}
        </div>
      )}
      {m.stopped && <div className="foot">stopped</div>}
    </div>
  )
}

export default function Chat({ messages, health }) {
  const bottom = useRef(null)
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  if (!messages.length) {
    return (
      <div className="view">
        <div className="empty">
          <h2>Ask about the billing migration</h2>
          <p>
            Every answer is quoted from an indexed chunk and carries a citation
            you can open. When the corpus cannot support an answer, it refuses
            instead of guessing.
          </p>
          <p>
            Pick a quick test question on the left, drop your own documents in
            to index them, or just type below.
          </p>
          <div className="hints">
            <span className="hint-chip">
              <b>{health?.indexed_chunks ?? '—'}</b> chunks indexed
            </span>
            <span className="hint-chip">
              <b>{health?.articles_indexed ?? '—'}</b> shipped
              {health?.uploaded_documents
                ? <> · <b>{health.uploaded_documents}</b> yours</> : null}
            </span>
            <span className="hint-chip">
              engine <b>{health?.generation_engine ?? '—'}</b>
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
