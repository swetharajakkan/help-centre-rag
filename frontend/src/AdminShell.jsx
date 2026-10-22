import React, { useState } from 'react'
import App from './App.jsx'
import DocumentsView from './DocumentsView.jsx'
import TrackView from './TrackView.jsx'

/**
 * The admin's tabs. Track: what users asked and what the agents did.
 * Documents: upload files (with categories) into MongoDB for the Week 9 agent.
 * Chat: the app as it was. App stays mounted while Track is open, so a chat
 * in progress is not lost by switching tabs.
 */
export default function AdminShell({ user, onLogout }) {
  const [tab, setTab] = useState(() => (localStorageGet('admin_tab') || 'track'))
  const pick = (t) => { setTab(t); localStorageSet('admin_tab', t) }
  return (
    <div className="admin">
      <header className="admin-bar">
        <span className="brand-mark">◈</span>
        <b className="admin-title">Help Centre · Admin</b>
        <div className="seg" role="tablist">
          {[['track', 'Track'], ['docs', 'Documents'], ['chat', 'Chat']].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} data-on={tab === k ? 1 : 0}
              onClick={() => pick(k)}>{label}</button>
          ))}
        </div>
        <span className="spacer" />
        <span className="who">{user.name || user.username} · admin</span>
        {onLogout && <button className="ghost" onClick={onLogout}>Sign out</button>}
      </header>
      <div className="admin-body">
        {tab === 'track' && <TrackView />}
        {tab === 'docs' && <DocumentsView />}
        <div className="admin-pane" style={{ display: tab === 'chat' ? 'block' : 'none' }}>
          <App />
        </div>
      </div>
    </div>
  )
}

function localStorageGet(k) {
  try { return window.localStorage.getItem(k) } catch { return null }
}

function localStorageSet(k, v) {
  try { window.localStorage.setItem(k, v) } catch { /* private mode: not remembered */ }
}
