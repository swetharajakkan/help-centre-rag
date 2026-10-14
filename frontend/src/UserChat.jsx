import React, { useEffect, useRef, useState } from 'react'
import CrewAnswer from './CrewAnswer.jsx'
import { QuickQuestions } from './Sidebar.jsx'

const SUGGESTIONS = [
  'Why was TCK-4403 escalated?',
  'What happens to stored cards during the migration?',
  'What is the status of TCK-4405?',
  'Why was my VAT number rejected after the migration?',
]

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
      const res = await fetch('/api/w9/ask', {
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
        <QuickQuestions sets={sets} week="week9" onAsk={(text) => ask(text)}
          hint={<>Answered by the <b>support agent</b>: one agent writes the reply, a second checks it.</>} />
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
              <p>
                Pick a question on the left, or type your own. Ask about the billing
                migration, or quote a ticket id (e.g. TCK-4403). One agent writes the
                answer from the help centre and ticket history; a second agent
                re-checks every statement against the source before you see it.
              </p>
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
                    {m.pending && <div className="stage"><i className="led-dot" />writing the answer and checking it…</div>}
                    {m.data && <CrewAnswer data={m.data} />}
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
