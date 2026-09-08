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

const trim = (q) => (q.length > 52 ? `${q.slice(0, 52)}…` : q)

/**
 * The replay target, shown with the answer it originally produced.
 *
 * This trace was a SECOND, independent draw from the same seed, so it is not
 * one of the twenty and appears nowhere in the list above. It is here so the
 * replay claim can be demonstrated live: ask it, then compare what comes back
 * against the recorded claims printed underneath.
 */
function ReplayCard({ replay, onAsk }) {
  return (
    <div className="replay-card">
      <p className="sampled-head">
        Replay proof
        <span className="sampled-count">{replay.id} · not one of the 20</span>
      </p>
      <button type="button" className="replay-ask"
              onClick={() => onAsk(replay.question, replay.product_area || '')}>
        Ask it again
      </button>
      <p className="replay-q">{replay.question}</p>
      <p className="note">
        Recorded {new Date().getFullYear() ? 'earlier' : ''} on k={replay.k},{' '}
        {replay.mode}, area {replay.product_area || 'all'}. It answered with
        these {replay.claims.length} claims — the live answer should match them
        word for word:
      </p>
      <ol className="replay-claims">
        {replay.claims.map((c, i) => <li key={i}>{c}</li>)}
      </ol>
    </div>
  )
}

/**
 * The Week 5 random sample, listed rather than hidden in the picker.
 *
 * These are the twenty traces that were read by hand to build the taxonomy,
 * shown with the verdict each one originally got. Clicking one re-asks it with
 * the product-area filter it actually ran under, so the trace reproduces
 * instead of being approximated.
 */
function SampledList({ sampled, onAsk }) {
  const refused = sampled.filter((s) => !s.answered).length
  return (
    <div className="sampled">
      {/* <p className="sampled-head">
        The 20 traces read by hand
        <span className="sampled-count">{refused} refused · {sampled.length - refused} answered</span>
      </p>
      <ol className="sampled-list">
        {sampled.map((ex) => (
          <li key={ex.id}>
            <button type="button"
                    className={ex.answered ? 'ok' : 'bad'}
                    title={`Ask again with area=${ex.product_area || 'all'}, k=${ex.k}`}
                    onClick={() => onAsk(ex.question, ex.product_area || '')}>
              <span className="sid">{ex.id}</span>
              <span className="sq">{ex.question}</span>
              <span className="sarea">{ex.product_area || 'all'}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="note">
        Drawn from 182 traces with seed 20260907. Click one to re-run it on the
        arm selected above.
      </p> */}
    </div>
  )
}

function QuickQuestions({ examples, sampled = [], replay = null, onAsk }) {
  const [picked, setPicked] = useState('')
  if (!examples.length && !sampled.length) return null

  const choose = (id) => {
    setPicked(id)
    const ex = [...examples, ...sampled].find((e) => e.id === id)
    // A sampled trace carries the product-area filter it originally ran with.
    // Asking it without that filter would not reproduce the recorded trace.
    if (ex) onAsk(ex.question, ex.product_area || '')
    // Reset so picking the same question twice in a row asks it again.
    setPicked('')
  }

  return (
    <section className="block">
      <p className="block-title">Quick test questions</p>
      <select className="picker" value={picked}
              onChange={(e) => choose(e.target.value)}>
        <option value="">Choose a question…</option>
        <optgroup label="Golden set — the questions we demo">
          {examples.map((ex) => (
            <option key={ex.id} value={ex.id} title={ex.question}>
              {ex.id} — {trim(ex.question)}
            </option>
          ))}
        </optgroup>
        {sampled.length ? (
          <optgroup label="Week 5 random sample — the 20 read by hand">
            {sampled.map((ex) => (
              <option key={ex.id} value={ex.id}
                      title={`${ex.question}\n\narea: ${ex.product_area || 'all'} · k=${ex.k} · originally ${ex.answered ? 'answered' : 'refused'}`}>
                {ex.id} {ex.answered ? '·' : '✕'} {trim(ex.question)}
              </option>
            ))}
          </optgroup>
        ) : null}
      </select>

      {sampled.length ? <SampledList sampled={sampled} onAsk={onAsk} /> : null}
      {replay ? <ReplayCard replay={replay} onAsk={onAsk} /> : null}
      {/* <p className="note">
        The {examples.length} questions the Week 4 eval scores. G10 and G11
        answer only on the reranked arm; G12 declines on both.
      </p> */}
    </section>
  )
}

export default function Sidebar({ documents, examples, sampled, replay, onAsk,
                                  onUploaded, onDelete, onClear, ocrEngines }) {
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
      <QuickQuestions examples={examples} sampled={sampled} replay={replay} onAsk={onAsk} />

      <div className="sidebar-foot">
        <button className="ghost" onClick={onClear}>Clear chat session</button>
      </div>
    </aside>
  )
}
