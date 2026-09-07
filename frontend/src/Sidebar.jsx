import React, { useRef, useState } from 'react'

function Upload({ onUploaded, ocrEngines }) {
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const picker = useRef(null)

  const send = async (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    setBusy(true)
    setResult(null)
    const form = new FormData()
    files.forEach((f) => form.append('files', f, f.name))
    try {
      const res = await fetch('/api/documents', { method: 'POST', body: form })
      const raw = await res.text()
      let data
      try { data = JSON.parse(raw) } catch { data = null }
      if (!data) throw new Error(`HTTP ${res.status}`)
      // 422 means every file was rejected; its detail carries the reasons.
      const body = res.ok ? data : (data.detail || data)
      setResult({ accepted: body.accepted || [], rejected: body.rejected || [] })
      if ((body.accepted || []).length) onUploaded()
    } catch (e) {
      setResult({ accepted: [], rejected: [{ filename: 'upload', reason: e.message }] })
    } finally {
      setBusy(false)
      if (picker.current) picker.current.value = ''
    }
  }

  return (
    <section className="block">
      <p className="block-title">Upload &amp; store documents</p>
      <button
        className={`drop ${over ? 'over' : ''} ${busy ? 'busy' : ''}`}
        onClick={() => picker.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files) }}
      >
        <span className="drop-icon">{busy ? '◌' : '↥'}</span>
        <span className="drop-main">{busy ? 'Indexing…' : 'Drop documents here'}</span>
        <span className="drop-sub">
          text or images — md, txt, csv, json, html, png, jpg, heic
        </span>
      </button>
      {/* No `accept`: every file type may be chosen, and the server decides
          what it can recover text from. */}
      <input ref={picker} type="file" multiple hidden
             onChange={(e) => send(e.target.files)} />

      {ocrEngines?.length > 0 ? (
        <p className="note">
          Images are read with OCR ({ocrEngines[0]}) and the original is kept so
          a quote can be checked against the picture.
        </p>
      ) : ocrEngines ? (
        <p className="note bad">
          No OCR engine on this server, so images will be refused. Set{' '}
          <code>ANTHROPIC_API_KEY</code>, or install Apple Vision with{' '}
          <code>pip install pyobjc-framework-Vision</code>.
        </p>
      ) : null}

      {result?.accepted?.length > 0 && (
        <p className="note ok">
          Indexed {result.accepted.map((a) =>
            `${a.filename} (${a.chunks} chunk${a.chunks === 1 ? '' : 's'})`).join(', ')}
        </p>
      )}
      {result?.rejected?.length > 0 && (
        <p className="note bad">
          {result.rejected.map((r) => `${r.filename}: ${r.reason}`).join(' · ')}
        </p>
      )}
    </section>
  )
}

function MyDocuments({ documents, onDelete }) {
  const mine = documents.filter((d) => d.uploaded)
  if (!mine.length) return null
  return (
    <section className="block">
      <p className="block-title">Your documents <span className="count">{mine.length}</span></p>
      {mine.map((d) => (
        <div className="doc" key={d.source_file}>
          <div className="doc-name">
            {d.source_file}
            <div className="doc-meta">
              {d.article_id} · {d.chunks} chunks
              {d.extracted_by ? <span className="ocr-tag">OCR</span> : null}
            </div>
          </div>
          <button className="icon-btn" title={`Delete ${d.source_file}`}
                  onClick={() => onDelete(d.source_file)}>✕</button>
        </div>
      ))}
    </section>
  )
}

function QuickQuestions({ examples, onAsk }) {
  const [picked, setPicked] = useState('')
  if (!examples.length) return null

  const choose = (id) => {
    setPicked(id)
    const ex = examples.find((e) => e.id === id)
    if (ex) onAsk(ex.question)
    // Reset so picking the same question twice in a row asks it again.
    setPicked('')
  }

  return (
    <section className="block">
      <p className="block-title">Quick test questions</p>
      <select className="picker" value={picked}
              onChange={(e) => choose(e.target.value)}>
        <option value="">Choose a golden-set question…</option>
        {examples.map((ex) => (
          <option key={ex.id} value={ex.id} title={ex.question}>
            {ex.id} — {ex.question.length > 58
              ? `${ex.question.slice(0, 58)}…` : ex.question}
          </option>
        ))}
      </select>
      <p className="note">
        The {examples.length} questions the Week 4 eval scores. G10 and G11
        answer only on the reranked arm; G12 declines on both.
      </p>
    </section>
  )
}

export default function Sidebar({ documents, examples, onAsk, onUploaded,
                                  onDelete, onClear, ocrEngines }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">◈</span>
        <div>
          <h1>Help Centre RAG</h1>
          <p className="kicker">Billing migration KB</p>
        </div>
      </div>

      <Upload onUploaded={onUploaded} ocrEngines={ocrEngines} />
      <MyDocuments documents={documents} onDelete={onDelete} />
      <QuickQuestions examples={examples} onAsk={onAsk} />

      <div className="sidebar-foot">
        <button className="ghost" onClick={onClear}>Clear chat session</button>
      </div>
    </aside>
  )
}
