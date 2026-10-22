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
        <span className="drop-main">{busy ? 'Uploading…' : 'Drop documents here'}</span>
        <span className="drop-sub">
          text or images
        </span>
      </button>
      {/* No `accept`: every file type may be chosen, and the server decides
          what it can recover text from. */}
      <input ref={picker} type="file" multiple hidden
        onChange={(e) => send(e.target.files)} />

      {ocrEngines && !ocrEngines.length && (
        <p className="note bad">Images can't be read on this server.</p>
      )}

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
              {d.article_id}
            </div>
          </div>
          <button className="icon-btn" title={`Delete ${d.source_file}`}
            onClick={() => onDelete(d.source_file)}>✕</button>
        </div>
      ))}
    </section>
  )
}

// The latest question set: the ten tickets the triage squad is raced on.
export const LATEST_IDS = ['C-01', 'C-02', 'C-04', 'C-05', 'C-06',
                           'C-07', 'C-08', 'C-09', 'C-10', 'C-11']

// Race 2 (week10/fanout.py): tickets with several independent error codes.
export const FANOUT_QUESTIONS = [
  { id: 'F-01', product_area: null, question: 'After cutover we see ERR-4215 on invoices, ERR-4301 on a subscription and ERR-4036 on a card update. What does each mean and what do we do?' },
  { id: 'F-02', product_area: null, question: 'Four errors since migration: ERR-4502, ERR-4114, ERR-4005 and ERR-4216. How do we fix each one?' },
  { id: 'F-03', product_area: null, question: 'Our finance team hit ERR-4001, ERR-4033, ERR-4212, ERR-4303 and ERR-4503 this week. Please explain each and the fix.' },
  { id: 'F-04', product_area: null, question: 'Six codes across our workspaces: ERR-4002, ERR-4030, ERR-4110, ERR-4211, ERR-4302 and ERR-4504. What is each and what should we do?' },
]

export const latestQuestions = (cases) =>
  [...LATEST_IDS.map((id) => (cases || []).find((c) => c.id === id)).filter(Boolean),
   ...FANOUT_QUESTIONS]

const trim = (q) => (q.length > 60 ? `${q.slice(0, 60)}…` : q)

/**
 * Quick questions. `items` is one flat list (the user screen); `groups` is
 * every set, each picked question carrying the system that answers it.
 */
export function QuickQuestions({ items, groups, onAsk }) {
  const all = groups
    ? groups.flatMap((g) => g.items.map((ex) => ({ ...ex, mode: g.mode, key: `${g.mode}:${ex.id}` })))
    : (items || []).map((ex) => ({ ...ex, key: ex.id }))
  const choose = (key) => {
    const ex = all.find((e) => e.key === key)
    if (ex) onAsk(ex.question, { area: ex.product_area ?? undefined, caseId: ex.id, mode: ex.mode })
  }
  const option = (ex) => (
    <option key={ex.key} value={ex.key} title={ex.question}>{ex.id} — {trim(ex.question)}</option>
  )
  return (
    <section className="block">
      <p className="block-title">Quick questions {groups && <span className="count">{all.length}</span>}</p>
      {/* value is pinned to "" so picking the same question twice asks it again. */}
      <select className="picker" value="" disabled={!all.length}
        onChange={(e) => choose(e.target.value)}>
        <option value="">{all.length ? 'Choose a question…' : 'No questions'}</option>
        {groups
          ? groups.map((g) => (
            <optgroup key={g.mode} label={`${g.label} (${g.items.length})`}>
              {all.filter((ex) => ex.mode === g.mode).map(option)}
            </optgroup>
          ))
          : all.map(option)}
      </select>
    </section>
  )
}

export default function Sidebar({ documents, groups, onAsk,
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
      <QuickQuestions groups={groups} onAsk={onAsk} />

      <div className="sidebar-foot">
        <button className="ghost" onClick={onClear}>Clear chat session</button>
      </div>
    </aside>
  )
}
