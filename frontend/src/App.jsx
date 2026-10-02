import React, { useCallback, useEffect, useState } from 'react'
import Sidebar from './Sidebar.jsx'
import Chat from './Chat.jsx'
import EvalView from './EvalView.jsx'
import Week7View from './Week7View.jsx'
import Week8View from './Week8View.jsx'
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

// The filter bar. Weeks 3-5 are retrieval arms of the streamed RAG answer;
// Week 6 drafts a ticket reply and grades it with a judge; Week 7 runs the
// refund-chase ticket through the agent or the fixed workflow.
const WEEKS = [
  { value: 'week3', short: 'Week 3', label: 'Week 3 — baseline retrieval' },
  { value: 'week4', short: 'Week 4', label: 'Week 4 — reranked' },
  { value: 'week5', short: 'Week 5', label: 'Week 5 — area-filter fallback' },
  { value: 'week6', short: 'Week 6', label: 'Week 6 — ticket reply + judge' },
  { value: 'week7', short: 'Week 7', label: 'Week 7 — agent vs workflow' },
  { value: 'week8', short: 'Week 8', label: 'Week 8 — trajectory-scored agent (sampled engine)' },
]
const JUDGES = [['judge_v1', 'Judge v1'], ['judge_v2', 'Judge v2']]
const SYSTEMS = [['agent', 'Agent'], ['workflow', 'Fixed workflow']]
const MITIGATION = [[false, 'Off'], [true, 'Arg validation']]
// Week 6's drafter uses Week 4 retrieval, and Week 7 retrieves nothing, so
// the chunk comparison runs on the Week 4 arm for both.
const RETRIEVAL_ARM = { week3: 'week3', week4: 'week4', week5: 'week5',
                        week6: 'week4', week7: 'week4', week8: 'week4' }

const VIEWS = [
  ['chat', 'Chat'], ['chunks', 'Chunks'], ['eval', 'Eval'],
  ['agent', 'Agent · W7'], ['trajectory', 'Trajectory · W8'], ['documents', 'Documents'],
]
// Links shared before the views were renamed keep working.
const OLD_HASH = { compare: 'chunks', errors: 'eval', evals: 'eval', week7: 'agent', week8: 'trajectory' }

function filterLabel(week, judge, system, mitigate, seed) {
  const w = WEEKS.find((x) => x.value === week)
  if (week === 'week8') return `${w.short} · seed ${seed} · mitigation ${mitigate ? 'on' : 'off'}`
  if (week === 'week6') return `${w.short} · ${JUDGES.find((j) => j[0] === judge)[1]}`
  if (week === 'week7') return `${w.short} · ${SYSTEMS.find((x) => x[0] === system)[1]}`
  return w.label
}

function Seg({ options, value, onChange, label }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v}
          data-on={value === v ? 1 : 0} onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  )
}

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

function CompareView({ compare, week }) {
  const note = RETRIEVAL_ARM[week] !== week
    ? <p className="filter-note">{week === 'week7' || week === 'week8' ? `${week === 'week7' ? 'Week 7' : 'Week 8'} calls tools instead of retrieving chunks`
        : 'Week 6 drafts from Week 4 retrieval'}, so chunks are compared on the Week 4 arm.</p>
    : null
  if (!compare) {
    return (
      <div className="view">
        <div className="empty">
          <h2>Compare chunkers</h2>
          <p>
            Ask a question below to run it through both chunking strategies at
            once, with the retriever and every other variable held constant.
          </p>
          {note}
        </div>
      </div>
    )
  }
  return (
    <div className="view">
      {note}
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

const SEV_CLASS = { embarrasses: 'sev-bad', annoys: 'sev-warn', clean: 'sev-ok' }

/**
 * Week 5 error analysis: every sampled trace with the failure mode it was
 * coded into.
 *
 * The data comes from /api/error_analysis, which reads week5/coding.json, so
 * what the UI shows and what taxonomy.md reports cannot drift apart. Clicking
 * a mode filters the trace list to it.
 */
function ErrorAnalysisView({ analysis, onAsk }) {
  const [picked, setPicked] = useState(null)
  const [onlyTrace, setOnlyTrace] = useState(null)
  if (!analysis || !analysis.traces?.length) {
    return (
      <div className="view">
        <div className="empty">
          <h2>No error analysis found</h2>
          <p>Run the Week 5 scripts to generate <code>week5/coding.json</code>.</p>
        </div>
      </div>
    )
  }
  const { modes, traces, seed, population, sample_size: size } = analysis
  const byId = Object.fromEntries(modes.map((m) => [m.id, m]))
  const shown = onlyTrace
    ? traces.filter((t) => t.trace_id === onlyTrace)
    : picked === null ? traces : traces.filter((t) => t.mode === picked)
  const worst = Math.max(...modes.map((m) => m.count))

  return (
    <div className="view ea">
      <header className="ea-head">
        <div>
          <h2>Error analysis</h2>
          <p className="ea-sub">
            {size} traces drawn at random from {population}, seed <b>{seed}</b>,
            read one at a time before any category existed.
          </p>
        </div>
        <div className="ea-stats">
          <div><b>{traces.filter((t) => t.mode !== 0).length}</b><span>failed</span></div>
          <div><b>{traces.filter((t) => t.mode === 0).length}</b><span>clean</span></div>
          <div><b>{modes.filter((m) => m.id !== 0).length}</b><span>modes</span></div>
        </div>
      </header>

      <div className="ea-modes">
        {modes.map((m) => (
          <div key={m.id}
            className={`ea-mode ${SEV_CLASS[m.severity]} ${picked === m.id ? 'on' : ''}`}>
            {/* The row is a div, not a button: the trace-id chips below are
                themselves buttons, and nesting a button inside one is invalid. */}
            <button type="button" className="ea-mode-hit"
              aria-pressed={picked === m.id}
              onClick={() => setPicked(picked === m.id ? null : m.id)}>
              <span className="ea-rank">{m.id === 0 ? '—' : m.id}</span>
              <span className="ea-mode-body">
                {/* The class is the engineering name for the fault (which stage
                    of the pipeline broke); the line under it is what a reader
                    of the transcript actually sees. Both are kept, because a
                    fix is scoped by the first and recognised by the second. */}
                <span className={`ea-class cls-${m.class_slug}`}>
                  <b>{m.failure_class}</b>
                  <i>{m.failure_subtype}</i>
                </span>
                <span className="ea-mode-name">{m.name}</span>
                <span className="ea-mode-desc">{m.desc}</span>
                <span className="ea-sev">{m.sev_label}</span>
              </span>
              <span className="ea-freq">
                <span className="ea-pct">{m.pct}%</span>
                <span className="ea-n">{m.count} / {size}</span>
                <span className="ea-track">
                  <span className="ea-fill" style={{ width: `${(m.count / worst) * 100}%` }} />
                </span>
              </span>
            </button>
            <div className="ea-ids">
              <span className="ea-ids-label">
                {m.count === 1 ? 'trace' : `all ${m.count} traces`}
              </span>
              {m.trace_ids.map((id) => (
                <button key={id} type="button"
                  className={`ea-id ${onlyTrace === id ? 'on' : ''}`}
                  title={`Show ${id} on its own`}
                  onClick={() => setOnlyTrace(onlyTrace === id ? null : id)}>
                  {id}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="ea-listhead">
        <span>
          {onlyTrace || (picked === null
            ? `All ${size} traces`
            : `${byId[picked].failure_class} — ${byId[picked].name}`)}
        </span>
        {(picked !== null || onlyTrace) && (
          <button type="button" className="ea-clear"
            onClick={() => { setPicked(null); setOnlyTrace(null) }}>
            show all {size}
          </button>
        )}
      </div>

      <ol className="ea-traces">
        {shown.map((t) => {
          const m = byId[t.mode]
          return (
            <li key={t.trace_id} className={SEV_CLASS[m.severity]}>
              <div className="ea-tr-top">
                <span className="ea-tid">{t.trace_id}</span>
                <span className={`ea-tag-cls cls-${m.class_slug}`}>{m.failure_class}</span>
                <span className="ea-tag">{m.short}</span>
                <span className="ea-meta">
                  {t.answered ? 'answered' : 'refused'} · area {t.product_area || 'all'} ·
                  k={t.k} · {t.arm || 'default'}
                  {t.coverage != null ? ` · coverage ${t.coverage}` : ''}
                </span>
                <button type="button" className="ea-ask"
                  onClick={() => onAsk(t.question, t.product_area || '')}>
                  re-run
                </button>
              </div>
              <p className="ea-q">{t.question}</p>
              <p className="ea-obs">{t.observation}</p>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/** Eval: Week 6 judge validation, with Week 5's error analysis one click away. */
function EvalPage({ analysis, onAsk }) {
  const [which, setWhich] = useState('week6')
  return (
    <div className="eval-page">
      <div className="subbar">
        <Seg label="Evaluation" value={which} onChange={setWhich}
          options={[['week6', 'Week 6 · judges vs human'], ['week5', 'Week 5 · error analysis']]} />
      </div>
      {which === 'week6'
        ? <EvalView onAsk={onAsk} />
        : <ErrorAnalysisView analysis={analysis} onAsk={onAsk} />}
    </div>
  )
}

async function postJSON(url, body, signal) {
  let res
  try {
    res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new Error(BACKEND_HINT)
  }
  const raw = await res.text()
  let data
  try { data = JSON.parse(raw) } catch { throw new Error(`HTTP ${res.status}: ${raw.slice(0, 200)}`) }
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`)
  return data
}

export default function App() {
  // Hash routing so a view is linkable: #eval opens the evaluation straight
  // away, which is what you want when demoing from a pasted link.
  const viewFromHash = () => {
    const h = window.location.hash.replace('#', '')
    const v = OLD_HASH[h] || h
    return VIEWS.some(([k]) => k === v) ? v : null
  }
  const [view, setView] = useState(() => viewFromHash() || 'chat')
  useEffect(() => {
    const onHash = () => { const v = viewFromHash(); if (v) setView(v) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => { window.location.hash = view }, [view])

  const [health, setHealth] = useState(null)
  const [healthErr, setHealthErr] = useState(null)
  const [documents, setDocuments] = useState([])
  const [sets, setSets] = useState({ golden: [], week5: [], week6: [], week7: [], week8: [] })
  const [analysis, setAnalysis] = useState(null)
  const [areas, setAreas] = useState([])

  const [messages, setMessages] = useState([])
  const [compare, setCompare] = useState(null)
  const [q, setQ] = useState('')
  // The filter bar.
  const [week, setWeek] = useState('week4')
  const [judge, setJudge] = useState('judge_v2')
  const [system, setSystem] = useState('agent')
  const [mitigate, setMitigate] = useState(false)
  const [seed, setSeed] = useState(2)
  const [k, setK] = useState(3)
  const [area, setArea] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [abort, setAbort] = useState(null)
  // One id per chat session, so Langfuse groups the turns of a conversation
  // instead of showing them as unrelated traces. Reset by "Clear chat session".
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())


  const refresh = useCallback(() => {
    getJSON('/api/health').then((d) => { setHealth(d); setHealthErr(null) })
      .catch((e) => setHealthErr(e.message))
    getJSON('/api/documents').then((d) => setDocuments(d.documents)).catch(() => { })
    getJSON('/api/product_areas').then((d) => setAreas(d.product_areas)).catch(() => { })
    getJSON('/api/error_analysis').then(setAnalysis).catch(() => setAnalysis(null))
    // A backend too old to serve this returns a 404 with a JSON body, which
    // parses fine -- so the array shape, not the parse, is what is checked.
    getJSON('/api/examples')
      .then((d) => {
        const arr = (x) => (Array.isArray(x) ? x : [])
        setSets({
          golden: arr(d.examples).map((e) => ({ ...e, product_area: undefined })),
          week5: [
            ...(d.replay ? [{ ...d.replay, product_area: d.replay.product_area || '',
              badge: 'replay proof', badgeCls: 'accent' }] : []),
            // A sampled trace carries the product-area filter it originally
            // ran with; asking without it would not reproduce the trace.
            ...arr(d.sampled).map((e) => ({ ...e, product_area: e.product_area || '',
              badge: e.answered ? 'answered' : 'refused', badgeCls: e.answered ? 'ok' : 'bad' })),
          ],
          week6: arr(d.week6).map((e) => ({ ...e,
            badge: e.replay_verbatim ? 'regression' : (e.human ? (e.human === 'RESOLVED' ? 'human: resolved' : 'human: not resolved') : 'unlabelled'),
            badgeCls: e.replay_verbatim ? 'accent' : (e.human === 'RESOLVED' ? 'ok' : '') })),
          week7: arr(d.week7).map((e) => ({ ...e, product_area: undefined,
            badge: e.cls === 'multi_order' ? 'multi-order' : e.cls,
            badgeCls: e.cls === 'multi_order' ? 'bad' : e.cls === 'branch' ? 'warn' : '' })),
          week8: arr(d.week8).map((e) => ({ ...e, product_area: undefined,
            badge: e.wording === 'week7' ? 'Week 7 wording'
              : e.alternate ? 'alternate paths' : '',
            badgeCls: e.wording === 'week7' ? 'accent' : e.alternate ? 'warn' : '' })),
        })
      })
      .catch(() => setSets({ golden: [], week5: [], week6: [], week7: [], week8: [] }))
  }, [])

  useEffect(refresh, [refresh])

  const patch = (fn) =>
    setMessages((ms) => {
      if (!ms.length) return ms
      const next = ms.slice()
      next[next.length - 1] = fn(next[next.length - 1])
      return next
    })

  // Weeks 3-5: the streamed, grounded RAG answer.
  const streamAnswer = async (question, useArea, controller) => {
    const body = { question, k: Number(k), mode: week, session_id: sessionId }
    if (useArea) body.product_area = useArea
    await streamSSE('/api/chat', body, (event, data) => {
      if (event === 'meta') patch((m) => ({ ...m, meta: data }))
      else if (event === 'status') patch((m) => ({ ...m, stage: data.stage }))
      else if (event === 'retrieval') patch((m) => ({ ...m, retrieval: data }))
      // Week 5: the area filter came back empty-handed and the search was
      // rerun across every article. A second 'retrieval' event has already
      // replaced the evidence above; this records why.
      else if (event === 'fallback') patch((m) => ({ ...m, fallback: data }))
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
            claims[data.index] = { ...claims[data.index], supporting_quote: data.supporting_quote }
          return { ...m, claims }
        })
      else if (event === 'done') patch((m) => ({ ...m, done: data, streaming: false }))
      else if (event === 'error') patch((m) => ({ ...m, error: data.message, streaming: false }))
    }, controller.signal)
  }

  const ask = async (text, opts = {}) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    // A question picked from a list may carry the area filter it was recorded
    // under; the AREA dropdown is moved to match so the filter stays honest.
    const useArea = opts.area === undefined ? area : opts.area
    if (opts.area !== undefined) setArea(opts.area)
    setView('chat')
    setQ('')
    setErr(null)
    setBusy(true)
    const kind = ['week6', 'week7', 'week8'].includes(week) ? week : 'rag'
    const label = filterLabel(week, judge, system, mitigate, seed)
    setMessages((ms) => [...ms,
      { role: 'user', text: question, filter: label },
      { role: 'bot', kind, filter: label,
        streaming: true, stage: kind === 'rag' ? 'retrieving' : kind,
        claims: [], refusal: '', meta: null, retrieval: null, done: null,
        data: null, error: null, stopped: false },
    ])
    const controller = new AbortController()
    setAbort(controller)
    try {
      if (kind === 'rag') {
        await streamAnswer(question, useArea, controller)
      } else if (kind === 'week6') {
        const body = { question, judge, session_id: sessionId,
                       case_id: opts.caseId || null }
        if (useArea) body.product_area = useArea
        const data = await postJSON('/api/ask_week6', body, controller.signal)
        patch((m) => ({ ...m, data, streaming: false }))
      } else if (kind === 'week8') {
        const data = await postJSON('/api/ask_week8',
          { question, mitigate, seed, session_id: sessionId }, controller.signal)
        patch((m) => ({ ...m, data, streaming: false }))
      } else {
        const data = await postJSON('/api/ask_week7',
          { question, system, session_id: sessionId }, controller.signal)
        patch((m) => ({ ...m, data, streaming: false }))
      }
    } catch (e) {
      const stopped = e.name === 'AbortError'
      patch((m) => ({ ...m, error: stopped ? null : e.message, stopped, streaming: false }))
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
      const body = { query, k: Number(k), mode: RETRIEVAL_ARM[week] }
      if (area) body.product_area = area
      setCompare(await postJSON('/api/compare', body))
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  const submit = () => (view === 'chunks' ? runCompare() : ask())

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

  const showFilters = view === 'chat' || view === 'chunks'
  const retrieves = week !== 'week7' && week !== 'week8'

  return (
    <div className="shell">
      <Sidebar
        documents={documents} sets={sets} week={week}
        answerWith={filterLabel(week, judge, system, mitigate, seed)} onAsk={ask}
        onUploaded={refresh} onDelete={removeDocument}
        onClear={() => { setMessages([]); setCompare(null); setSessionId(crypto.randomUUID()) }}
        ocrEngines={health ? (health.ocr_engines || []) : null}
      />

      <main className="main">
        <div className="topbar">
          <nav className="nav" aria-label="View">
            {VIEWS.map(([v, label]) => (
              <button key={v} data-on={view === v ? 1 : 0} onClick={() => setView(v)}>{label}</button>
            ))}
          </nav>

          <span className="spacer" />

          <span className={`health ${healthErr ? 'off' : ''}`}
            title={healthErr || 'Backend online'}>
            <i className="led" />
            {healthErr ? 'offline' : `${health?.indexed_chunks ?? '—'} chunks`}
          </span>

          {/* Every answer is recorded when this is lit. Shown because the
              Week 5 analysis was blocked on there being no trace log at all. */}
          {health?.tracing ? (
            health.tracing.enabled ? (
              <a className="health trace-on" href={health.tracing.host}
                target="_blank" rel="noreferrer"
                title={`Every answer is traced to ${health.tracing.host} · prompt ${health.tracing.prompt_version}`}>
                <i className="led" />traced
              </a>
            ) : (
              <span className="health off"
                title={`Answers are NOT being recorded — ${health.tracing.reason}`}>
                <i className="led" />not traced
              </span>
            )
          ) : null}
        </div>

        {showFilters && (
          <div className="filterbar">
            <div className="fgroup">
              <span className="flabel">Answer with</span>
              <Seg label="Week" value={week} onChange={setWeek}
                options={WEEKS.map((w) => [w.value, w.short])} />
            </div>
            {week === 'week6' && (
              <div className="fgroup">
                <span className="flabel">Judge</span>
                <Seg label="Judge" value={judge} onChange={setJudge} options={JUDGES} />
              </div>
            )}
            {week === 'week7' && (
              <div className="fgroup">
                <span className="flabel">System</span>
                <Seg label="System" value={system} onChange={setSystem} options={SYSTEMS} />
              </div>
            )}
            {week === 'week8' && (
              <>
                <div className="fgroup">
                  <span className="flabel">Mitigation</span>
                  <Seg label="Mitigation" value={mitigate} onChange={setMitigate} options={MITIGATION} />
                </div>
                <label className="control">
                  <span>seed</span>
                  <select value={seed} onChange={(e) => setSeed(Number(e.target.value))}>
                    {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) =>
                      <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
              </>
            )}
            {retrieves && (
              <>
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
              </>
            )}
            <span className="fdesc">{WEEKS.find((w) => w.value === week).label}</span>
          </div>
        )}

        {(err || healthErr) && (
          <div style={{ padding: '14px 20px 0' }}>
            <div className="banner bad">
              <strong>Request failed.</strong>
              <pre>{err || healthErr}</pre>
            </div>
          </div>
        )}

        <ErrorBoundary>
          {view === 'chat' && <Chat messages={messages} health={health} week={week} />}
          {view === 'chunks' && <CompareView compare={compare} week={week} />}
          {view === 'eval' && <EvalPage analysis={analysis} onAsk={ask} />}
          {view === 'agent' && <Week7View />}
          {view === 'trajectory' && <Week8View />}
          {view === 'documents' && <DocumentsView documents={documents} />}
        </ErrorBoundary>

        {showFilters && (
          <div className="composer">
            <div className="composer-inner">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submit()}
                placeholder={view === 'chunks'
                  ? 'Query to run through both chunkers…'
                  : week === 'week8'
                    ? 'Pick a ticket (e.g. TCK-7001) or type a message — the path is scored, not just the answer…'
                  : week === 'week7'
                    ? 'Type a customer message (e.g. “Refund ORD-5101 please”) or a ticket id like TCK-7004…'
                    : week === 'week6'
                      ? 'Ask a customer question — a ticket reply is drafted and judged…'
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
