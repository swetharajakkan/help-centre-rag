import React, { useEffect, useState } from 'react'
import AdminShell from './AdminShell.jsx'
import Login from './Login.jsx'
import UserChat from './UserChat.jsx'

/**
 * The login gate. The session is an HttpOnly cookie, so this only asks the
 * backend who it is; the backend enforces the roles on every request either
 * way (backend/app/auth.py).
 */
export default function Root() {
  const [who, setWho] = useState(undefined)   // undefined = still checking

  useEffect(() => {
    fetch('/api/auth/me')
      .then((r) => (r.ok ? r.json() : null))
      .then(setWho)
      .catch(() => setWho(null))
  }, [])

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => { })
    setWho(null)
  }

  if (who === undefined) return <div className="login-wrap"><div className="stage"><i className="led-dot" />checking session…</div></div>
  if (!who) return <Login onLogin={setWho} />
  if (who.role !== 'admin') return <UserChat user={who} onLogout={logout} />
  return <AdminShell user={who} onLogout={who.auth === 'disabled' ? null : logout} />
}
