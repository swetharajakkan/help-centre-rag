import React, { useEffect, useRef, useState } from 'react'
import CrewAnswer from './CrewAnswer.jsx'
import { QuickQuestions, latestQuestions } from './Sidebar.jsx'

const SUGGESTIONS = [
  'Why was TCK-4403 escalated?',
  'What happens to stored cards during the migration?',
  'What is the status of TCK-4405?',
  'Why was my VAT number rejected after the migration?',
]

const ROUTED = { crew: 'the support crew', single: 'the single agent',
  single_par: 'the single agent (parallel lookups)', squad: 'the triage squad' }

/**
 * The whole UI a `user` gets: pick a week's question or type one, read the
 * verified reply. Every question is answered by the Week 9 crew and recorded
 * for the admin's Track view.
 */
export default function UserChat({ user, onLogout }) {
  const [messages, setMessages] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [sets, setSets] = useState({})
  const bottom = useRef(null)
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => {
    fetch('/api/w9/questions').then((r) => (r.ok ? r.json() : { groups: {} }))
      .then((d) => setSets(d.groups || {})).catch(() => setSets({}))
  }, [])

  const ask = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setQ('')
    setBusy(true)
    setMessages((ms) => [...ms, { role: 'user', text: question }, { role: 'bot', pending: true }])
    let reply
    try {
      // The router picks the agent: no error code -> the support crew; one issue ->
      // the single agent; a few -> single agent with parallel lookups; many -> the squad.
      const res = await fetch('/api/w10/auto', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.status === 401) { onLogout(); return }
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      reply = { role: 'bot', data }
    } catch (e) {
      reply = { role: 'bot', error: e.message }
    } finally {
      setBusy(false)
    }
    setMessages((ms) => [...ms.slice(0, -1), reply])
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <div>
            <h1>Help Centre</h1>
            <p className="kicker">Ask the support agent</p>
          </div>
        </div>
        <QuickQuestions items={latestQuestions(sets.week6)} onAsk={(text) => ask(text)} />
        <div className="sidebar-foot">
          <button className="ghost" onClick={() => setMessages([])}>Clear chat</button>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <span className="spacer" />
          <span className="who">{user.name || user.username}</span>
          <button className="ghost" onClick={onLogout}>Sign out</button>
        </div>

        {!messages.length ? (
          <div className="view">
            <div className="empty">
              <h2>How can we help?</h2>
              <p>Pick a question on the left, or type your own.</p>
              <div className="hints">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="hint-chip" onClick={() => ask(s)}>{s}</button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="view">
            <div className="thread">
              {messages.map((m, i) => m.role === 'user'
                ? <div className="msg you" key={i}>{m.text}</div>
                : (
                  <div className={`msg bot ${m.error ? 'failed' : ''}`} key={i}>
                    {m.pending && <div className="stage"><i className="led-dot" />working…</div>}
                    {m.data && m.data.route && (
                      <div className="route-tag">Handled by <b>{ROUTED[m.data.route.arm]}</b> · {m.data.route.reason}</div>
                    )}
                    {m.data && (m.data.crew ? <CrewAnswer data={m.data.crew} />
                      : m.data.reply ? <pre className="reply-box">{m.data.reply}</pre>
                        : !m.data.route && <CrewAnswer data={m.data} />)}
                    {m.error && <div className="claim-text"><strong>Something went wrong.</strong> {m.error}</div>}
                  </div>
                ))}
              <div ref={bottom} />
            </div>
          </div>
        )}

        <div className="composer">
          <div className="composer-inner">
            <input value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && ask()}
              placeholder="Type your question…" />
            <button className="send" onClick={() => ask()} disabled={busy || !q.trim()}>
              {busy ? 'Working…' : 'Send'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
