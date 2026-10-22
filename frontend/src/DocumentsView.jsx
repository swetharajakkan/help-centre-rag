import React, { useEffect, useState } from 'react'
import CrewAnswer from './CrewAnswer.jsx'

/**
 * Admin: upload documents into MongoDB with categories, list them, and try a
 * question. The Week 9 agent's admin-documents MCP server searches the same
 * collection on every call, so a new document is answerable straight away,
 * by users too.
 */
export default function DocumentsView() {
  const [docs, setDocs] = useState(null)
  const [cats, setCats] = useState([])
  const [filter, setFilter] = useState('')
  const [err, setErr] = useState(null)

  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [picked, setPicked] = useState(['Refund'])
  const [custom, setCustom] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const [inputKey, setInputKey] = useState(0)

  const [open, setOpen] = useState(null)       // a document's text
  const [q, setQ] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState(null)

  const load = async () => {
    try {
      const qs = filter ? `?category=${encodeURIComponent(filter)}` : ''
      const [d, c] = await Promise.all([fetch(`/api/docs${qs}`), fetch('/api/docs/categories')])
      const dj = await d.json().catch(() => ({}))
      if (!d.ok) throw new Error(dj.detail || `HTTP ${d.status}`)
      setDocs(dj.documents)
      if (c.ok) setCats((await c.json()).categories)
      setErr(null)
    } catch (e) {
      setErr(e.message)
      setDocs([])
    }
  }
  useEffect(() => { load() }, [filter])   // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (c) => setPicked((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c]))
  const addCustom = () => {
    const c = custom.trim()
    if (c && !picked.includes(c)) setPicked([...picked, c])
    setCustom('')
  }

  const upload = async (e) => {
    e.preventDefault()
    if (!file || !picked.length) return
    setBusy(true)
    setDone(null)
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    form.append('categories', JSON.stringify(picked))
    try {
      const res = await fetch('/api/docs', { method: 'POST', body: form })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setDone({ ok: true, text: `Stored as ${data.document.doc_id} under ${data.document.categories.join(', ')}. Ask about it below.` })
      setFile(null); setTitle(''); setInputKey((k) => k + 1)
      load()
    } catch (e2) {
      setDone({ ok: false, text: e2.message })
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id) => {
    if (!window.confirm(`Delete ${id}? The agent will stop answering from it.`)) return
    await fetch(`/api/docs/${id}`, { method: 'DELETE' })
    if (open?.doc_id === id) setOpen(null)
    load()
  }

  const view = async (id) => {
    const res = await fetch(`/api/docs/${id}`)
    if (res.ok) setOpen(await res.json())
  }

  const ask = async (e) => {
    e?.preventDefault()
    if (!q.trim()) return
    setAsking(true)
    setAnswer(null)
    try {
      const res = await fetch('/api/w9/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setAnswer({ data })
    } catch (e2) {
      setAnswer({ error: e2.message })
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="docs">
      <section className="docs-col">
        <h2 className="docs-h">Upload a document</h2>
        <form className="docs-card" onSubmit={upload}>
          <label className="login-field">
            <span>File (.pdf, .md, .txt, .csv, .json, .html, or an image)</span>
            <input key={inputKey} type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <label className="login-field">
            <span>Title (optional, defaults to the file name)</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <div className="login-field">
            <span>Categories (pick one or more)</span>
            <div className="docs-cats">
              {[...new Set([...cats, ...picked])].map((c) => (
                <button type="button" key={c} className="docs-cat" data-on={picked.includes(c) ? 1 : 0}
                  onClick={() => toggle(c)}>{c}</button>
              ))}
            </div>
            <div className="docs-row">
              <input value={custom} placeholder="Add a category…" onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCustom() } }} />
              <button type="button" className="ghost" onClick={addCustom} disabled={!custom.trim()}>Add</button>
            </div>
          </div>
          {done && <p className={`note ${done.ok ? 'ok' : 'bad'}`}>{done.text}</p>}
          <button className="send" disabled={busy || !file || !picked.length}>
            {busy ? 'Uploading…' : 'Upload to the database'}
          </button>
        </form>

        <h2 className="docs-h">Ask the Support crew</h2>
        <form className="docs-card" onSubmit={ask}>
          <div className="docs-row">
            <input value={q} placeholder="e.g. How long does a refund take?" onChange={(e) => setQ(e.target.value)} />
            <button className="send" disabled={asking || !q.trim()}>{asking ? 'Working…' : 'Ask'}</button>
          </div>
          {asking && <div className="stage"><i className="led-dot" />writing the answer and checking it…</div>}
          {answer?.data && <div className="msg bot docs-answer"><CrewAnswer data={answer.data} /></div>}
          {answer?.error && <p className="note bad">{answer.error}</p>}
        </form>
      </section>

      <section className="docs-col">
        <div className="docs-row docs-head">
          <h2 className="docs-h">Stored documents {docs && <span className="muted">({docs.length})</span>}</h2>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All categories</option>
            {cats.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        {err && <p className="note bad">{err}</p>}
        {docs && !docs.length && !err && <p className="login-hint">No documents yet.</p>}
        <div className="docs-list">
          {docs?.map((d) => (
            <div key={d.doc_id} className="docs-card docs-item">
              <div className="docs-row">
                <b className="docs-id">{d.doc_id}</b>
                <span className="docs-title">{d.title}</span>
                <span className="spacer" />
                <button className="ghost" onClick={() => view(d.doc_id)}>View</button>
                <button className="ghost" onClick={() => remove(d.doc_id)}>Delete</button>
              </div>
              <div>{d.categories.map((c) => <span key={c} className="chip">{c}</span>)}</div>
              <p className="login-hint">{d.filename} · {Math.max(1, Math.round(d.size / 1024))} KB · {d.chars} chars · by {d.uploaded_by} · {d.created_at?.slice(0, 16).replace('T', ' ')}</p>
              {open?.doc_id === d.doc_id && <pre className="docs-text">{open.text}</pre>}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
