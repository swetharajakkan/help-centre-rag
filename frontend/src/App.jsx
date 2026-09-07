import React, { useCallback, useEffect, useState } from 'react'
import Sidebar from './Sidebar.jsx'
import Chat from './Chat.jsx'
import { streamSSE } from './sse'

const BACKEND_HINT =
  'Backend not reachable on http://127.0.0.1:8000. Start it with: ' +
  '.venv/bin/uvicorn backend.app.main:app --port 8000'

async function getJSON(url) {
  let res
  try {
    res = await fetch(url)
  } catch {
    throw new Error(BACKEND_HINT)
  }
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

const MODES = [
  { value: 'week4', label: 'Week 4 — reranked' },
  { value: 'week3', label: 'Week 3 — baseline' },
]

/** One exception below must not take the whole page down with it. */
class ErrorBoundary extends React.Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="view">
        <div className="banner bad">
          <strong>The UI hit an error and stopped rendering.</strong>
          <pre>{String(this.state.error?.stack || this.state.error)}</pre>
        </div>
      </div>
    )
  }
}

function DocumentsView({ documents }) {
  return (
    <div className="view">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Source</th><th>Article</th><th>Product area</th>
              <th>Updated</th><th>Origin</th><th>Text from</th>
              <th className="num">Chunks</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((d) => (
              <tr key={d.source_file}>
                <td>{d.source_file}</td>
                <td>{d.article_id}</td>
                <td>{d.product_area}</td>
                <td>{d.last_updated}</td>
                <td>{d.uploaded ? 'uploaded' : 'shipped'}</td>
                <td>
                  {d.extracted_by
                    ? <span className="ocr-tag" title={`Read from ${d.original_file}`}>
                        {d.extracted_by}
                      </span>
                    : <span className="faint">typed</span>}
                </td>
                <td className="num">{d.chunks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CompareView({ compare }) {
  if (!compare) {
    return (
      <div className="view">
        <div className="empty">
          <h2>Compare chunkers</h2>
          <p>
            Ask a question below to run it through both chunking strategies at
            once, with the retriever and every other variable held constant.
          </p>
        </div>
      </div>
    )
  }
  return (
    <div className="view">
      <div className="cols">
        {['fixed_window', 'structure_aware'].map((s) => (
          <div key={s}>
            <h3>{s}</h3>
            {compare.by_strategy[s].map((h) => (
              <div className="hit" key={h.chunk_id}>
                <div className="score">
                  #{h.rank} fused {h.score} · dense {h.dense} · bm25 {h.bm25}
                  {h.rerank_score != null ? ` · rerank ${h.rerank_score}` : ''}
                </div>
                <div className="cite">{h.chunk_id}</div>
                <pre className="claim-text" style={{ fontSize: 11.5, color: 'var(--mut)' }}>
                  {h.text}
                </pre>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [view, setView] = useState('chat')
  const [health, setHealth] = useState(null)
  const [healthErr, setHealthErr] = useState(null)
  const [documents, setDocuments] = useState([])
  const [examples, setExamples] = useState([])
  const [areas, setAreas] = useState([])

  const [messages, setMessages] = useState([])
  const [compare, setCompare] = useState(null)
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('week4')
  const [k, setK] = useState(3)
  const [area, setArea] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [abort, setAbort] = useState(null)

  const refresh = useCallback(() => {
    getJSON('/api/health').then((d) => { setHealth(d); setHealthErr(null) })
      .catch((e) => setHealthErr(e.message))
    getJSON('/api/documents').then((d) => setDocuments(d.documents)).catch(() => {})
    getJSON('/api/product_areas').then((d) => setAreas(d.product_areas)).catch(() => {})
    // A backend too old to serve this returns a 404 with a JSON body, which
    // parses fine -- so the array shape, not the parse, is what is checked.
    getJSON('/api/examples')
      .then((d) => setExamples(Array.isArray(d.examples) ? d.examples : []))
      .catch(() => setExamples([]))
  }, [])

  useEffect(refresh, [refresh])

  const patch = (fn) =>
    setMessages((ms) => {
      if (!ms.length) return ms
      const next = ms.slice()
      next[next.length - 1] = fn(next[next.length - 1])
      return next
    })

  const ask = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setView('chat')
    setQ('')
    setErr(null)
    setBusy(true)
    setMessages((ms) => [...ms,
      { role: 'user', text: question },
      { role: 'bot', streaming: true, stage: 'retrieving', claims: [], refusal: '',
        meta: null, retrieval: null, done: null, error: null, stopped: false },
    ])

    const body = { question, k: Number(k), mode }
    if (area) body.product_area = area
    const controller = new AbortController()
    setAbort(controller)

    try {
      await streamSSE('/api/chat', body, (event, data) => {
        if (event === 'meta') patch((m) => ({ ...m, meta: data }))
        else if (event === 'status') patch((m) => ({ ...m, stage: data.stage }))
        else if (event === 'retrieval') patch((m) => ({ ...m, retrieval: data }))
        else if (event === 'claim_start')
          patch((m) => ({ ...m, claims: [...m.claims, { ...data, text: '' }] }))
        else if (event === 'delta')
          patch((m) => {
            // Deltas before the first claim_start belong to a refusal.
            if (m.stage === 'refusing' || !m.claims.length)
              return { ...m, refusal: m.refusal + data.text }
            const claims = m.claims.slice()
            const last = claims[claims.length - 1]
            claims[claims.length - 1] = { ...last, text: last.text + data.text }
            return { ...m, claims }
          })
        else if (event === 'claim_end')
          patch((m) => {
            const claims = m.claims.slice()
            if (claims[data.index])
              claims[data.index] = { ...claims[data.index],
                                     supporting_quote: data.supporting_quote }
            return { ...m, claims }
          })
        else if (event === 'done') patch((m) => ({ ...m, done: data, streaming: false }))
        else if (event === 'error')
          patch((m) => ({ ...m, error: data.message, streaming: false }))
      }, controller.signal)
    } catch (e) {
      const stopped = e.name === 'AbortError'
      patch((m) => ({ ...m, error: stopped ? null : e.message, stopped,
                      streaming: false }))
    } finally {
      setAbort(null)
      setBusy(false)
      patch((m) => ({ ...m, streaming: false }))
    }
  }

  const runCompare = async () => {
    const query = q.trim()
    if (!query || busy) return
    setBusy(true)
    setErr(null)
    try {
      const body = { query, k: Number(k), mode }
      if (area) body.product_area = area
      const res = await fetch('/api/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setCompare(data)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  const submit = () => (view === 'compare' ? runCompare() : ask())

  const removeDocument = async (name) => {
    try {
      const res = await fetch(`/api/documents/${encodeURIComponent(name)}`,
                              { method: 'DELETE' })
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`)
      refresh()
    } catch (e) {
      setErr(e.message)
    }
  }

  return (
    <div className="shell">
      <Sidebar
        documents={documents} examples={examples} onAsk={ask}
        onUploaded={refresh} onDelete={removeDocument}
        onClear={() => { setMessages([]); setCompare(null) }}
        ocrEngines={health ? (health.ocr_engines || []) : null}
      />

      <main className="main">
        <div className="topbar">
          <nav className="nav">
            <button data-on={view === 'chat' ? 1 : 0} onClick={() => setView('chat')}>
              Chat
            </button>
            <button data-on={view === 'compare' ? 1 : 0}
                    onClick={() => setView('compare')}>
              Compare chunkers
            </button>
            <button data-on={view === 'documents' ? 1 : 0}
                    onClick={() => setView('documents')}>
              Documents
            </button>
          </nav>

          <span className="spacer" />

          <span className={`health ${healthErr ? 'off' : ''}`}
                title={healthErr || 'Backend online'}>
            <i className="led" />
            {healthErr ? 'offline' : `${health?.indexed_chunks ?? '—'} chunks`}
          </span>

          <label className="control">
            <span>retrieval</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </label>
          <label className="control">
            <span>top k</span>
            <select value={k} onChange={(e) => setK(e.target.value)}>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) =>
                <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="control">
            <span>area</span>
            <select value={area} onChange={(e) => setArea(e.target.value)}>
              <option value="">all</option>
              {areas.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
        </div>

        {(err || healthErr) && (
          <div style={{ padding: '14px 20px 0' }}>
            <div className="banner bad">
              <strong>Request failed.</strong>
              <pre>{err || healthErr}</pre>
            </div>
          </div>
        )}

        <ErrorBoundary>
          {view === 'chat' && <Chat messages={messages} health={health} />}
          {view === 'compare' && <CompareView compare={compare} />}
          {view === 'documents' && <DocumentsView documents={documents} />}
        </ErrorBoundary>

        {view !== 'documents' && (
          <div className="composer">
            <div className="composer-inner">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submit()}
                placeholder={view === 'compare'
                  ? 'Query to run through both chunkers…'
                  : 'Ask about the billing migration, or your uploaded documents…'}
              />
              {busy && view === 'chat' && abort ? (
                <button className="send stop" onClick={() => abort.abort()}>Stop</button>
              ) : (
                <button className="send" onClick={submit} disabled={busy || !q.trim()}>
                  {busy ? 'Working…' : 'Send'}
                </button>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
