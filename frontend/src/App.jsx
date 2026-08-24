import React, { useEffect, useState } from 'react'

const BACKEND_HINT =
  'Backend not reachable on http://127.0.0.1:8000. Start it with:  ' +
  '.venv/bin/uvicorn backend.app.main:app --port 8000'

async function jsonOrThrow(res) {
  // Vite's proxy answers 500 with an EMPTY body when the backend is down,
  // so parsing blind here throws "Unexpected end of JSON input" instead of
  // saying what is actually wrong.
  const raw = await res.text()
  if (!raw) throw new Error(res.ok ? 'Empty response body.' : BACKEND_HINT)
  let data
  try {
    data = JSON.parse(raw)
  } catch {
    throw new Error(`Non-JSON response (HTTP ${res.status}): ${raw.slice(0, 200)}`)
  }
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

const post = (url, body) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(jsonOrThrow, () => { throw new Error(BACKEND_HINT) })

const get = (url) => fetch(url).then(jsonOrThrow, () => { throw new Error(BACKEND_HINT) })

function Hit({ h }) {
  return (
    <div className="card">
      <div className="sc">
        #{h.rank} · score {h.score} · dense {h.dense} · bm25 {h.bm25}
      </div>
      <div className="cid">{h.chunk_id}</div>
      <div style={{ margin: '4px 0' }}>
        <span className="tag">{h.meta.article_id}</span>
        <span className="tag">{h.meta.product_area}</span>
        <span className="tag">upd {h.meta.last_updated}</span>
      </div>
      <pre>{h.text}</pre>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('compare')
  const [q, setQ] = useState('')
  const [area, setArea] = useState('')
  const [areas, setAreas] = useState([])
  const [health, setHealth] = useState(null)
  const [healthErr, setHealthErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [cmp, setCmp] = useState(null)
  const [ans, setAns] = useState(null)

  useEffect(() => {
    get('/api/health').then(setHealth).catch((e) => setHealthErr(e.message))
    get('/api/product_areas')
      .then((d) => setAreas(d.product_areas))
      .catch(() => {})
  }, [])

  const switchTab = (next) => {
    if (next === tab) return
    setTab(next)
    setQ('')
    setArea('')
    setCmp(null)
    setAns(null)
    setErr(null)
    setBusy(false)
  }

  const run = async () => {
    setBusy(true)
    setErr(null)
    const body = { query: q, question: q, k: tab === 'compare' ? 5 : 3 }
    if (area) body.product_area = area
    try {
      if (tab === 'compare') setCmp(await post('/api/compare', body))
      else setAns(await post('/api/ask', body))
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  const hasResults = tab === 'compare' ? Boolean(cmp) : Boolean(ans)

  return (
    <main className={hasResults ? '' : 'centered'}>
      <header className="head">
        <h1>Help Centre RAG — billing migration drop</h1>
        <p className="sub">
          {healthErr
            ? '⚠ backend unavailable'
            : health
            ? `${health.articles_indexed} new articles indexed · fixed_window ${health.strategies.fixed_window} chunks · structure_aware ${health.strategies.structure_aware} chunks · generation: ${health.generation_engine} · historical corpus re-indexed: ${health.historical_corpus_reindexed ? 'yes' : 'no'}`
            : 'loading…'}
        </p>
      </header>

      <section className="panel">
        {(err || healthErr) && (
          <div className="card refuse">
            <strong>Request failed.</strong>
            <pre>{err || healthErr}</pre>
          </div>
        )}

        <div className="tabs">
          <button data-on={tab === 'compare' ? 1 : 0} onClick={() => switchTab('compare')}>
            Compare chunkers (search only)
          </button>
          <button data-on={tab === 'ask' ? 1 : 0} onClick={() => switchTab('ask')}>
            Ask (grounded, refuses)
          </button>
        </div>

        <div className="row">
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Ask about the billing migration…"
                 onKeyDown={(e) => e.key === 'Enter' && run()} />
          <select value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="">all product areas</option>
            {areas.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <button className="go" onClick={run} disabled={busy || q.length === 0}>
            {busy ? 'Running…' : 'Run'}
          </button>
        </div>
      </section>

      {tab === 'compare' && cmp && (
        <div className="cols">
          {['fixed_window', 'structure_aware'].map((s) => (
            <div key={s}>
              <h3>{s}</h3>
              {cmp.by_strategy[s].map((h) => <Hit key={h.chunk_id} h={h} />)}
            </div>
          ))}
        </div>
      )}

      {tab === 'ask' && ans && (
        <div className={`card ${ans.answered ? 'ok' : 'refuse'}`}>
          <div className="sc">engine: {ans.engine} · retrieved: {ans.retrieved.length} chunks</div>
          {ans.answered ? (
            <ol>
              {ans.claims.map((c, i) => (
                <li key={i} style={{ marginBottom: 10 }}>
                  <div>{c.claim}</div>
                  <div className="cid">
                    cite <a href={`/api/chunk/${c.chunk_id}`} target="_blank" rel="noreferrer">
                      {c.chunk_id}
                    </a> — {c.article_id} “{c.section}”
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <>
              <p><strong>Refused.</strong></p>
              <pre>{ans.refusal}</pre>
            </>
          )}
        </div>
      )}
    </main>
  )
}
