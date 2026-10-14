import React, { useState } from 'react'

/**
 * Sign in, or sign up. Anyone may sign up as a user; an admin sign-up also
 * needs the admin code, and the backend only accepts it for an email on the
 * admin list (MongoDB `admin_emails`).
 */
export default function Login({ onLogin }) {
  const [mode, setMode] = useState('signin')          // signin | signup
  const [role, setRole] = useState('user')            // signup only
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  const signup = mode === 'signup'
  const ready = signup
    ? name.trim() && email.trim() && password.length >= 8 && (role === 'user' || code.trim())
    : email.trim() && password

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      const res = await fetch(signup ? '/api/auth/signup' : '/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(signup
          ? { name, email, password, role, admin_code: role === 'admin' ? code : null }
          : { username: email, password }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail(data) || `HTTP ${res.status}`)
      onLogin(data)
    } catch (e2) {
      setErr(e2.message === 'Failed to fetch'
        ? 'Backend not reachable on http://127.0.0.1:8000.' : e2.message)
    } finally {
      setBusy(false)
    }
  }

  const switchTo = (m) => { setMode(m); setErr(null) }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark">◈</span>
          <div>
            <h1>Help Centre</h1>
            <p className="kicker">Billing migration support</p>
          </div>
        </div>

        <div className="seg login-seg" role="tablist">
          {[['signin', 'Sign in'], ['signup', 'Sign up']].map(([k, label]) => (
            <button type="button" key={k} role="tab" aria-selected={mode === k}
              data-on={mode === k ? 1 : 0} onClick={() => switchTo(k)}>{label}</button>
          ))}
        </div>

        {signup && (
          <div className="login-field">
            <span>Account type</span>
            <div className="seg login-seg">
              {[['user', 'User'], ['admin', 'Admin']].map(([k, label]) => (
                <button type="button" key={k} data-on={role === k ? 1 : 0}
                  onClick={() => setRole(k)}>{label}</button>
              ))}
            </div>
          </div>
        )}
        {signup && (
          <label className="login-field">
            <span>Name</span>
            <input value={name} autoComplete="name" onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label className="login-field">
          <span>{signup ? 'Email' : 'Email or username'}</span>
          <input value={email} autoFocus autoComplete={signup ? 'email' : 'username'}
            type={signup ? 'email' : 'text'} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="login-field">
          <span>Password{signup && ' (8+ characters)'}</span>
          <input type="password" value={password}
            autoComplete={signup ? 'new-password' : 'current-password'}
            onChange={(e) => setPassword(e.target.value)} />
        </label>
        {signup && role === 'admin' && (
          <label className="login-field">
            <span>Admin code</span>
            <input value={code} autoComplete="off" onChange={(e) => setCode(e.target.value)} />
          </label>
        )}

        {err && <p className="note bad">{err}</p>}
        <button className="send login-btn" disabled={busy || !ready}>
          {busy ? (signup ? 'Creating account…' : 'Signing in…') : (signup ? 'Create account' : 'Sign in')}
        </button>
        <p className="login-hint">
          {signup && role === 'admin'
            ? <>Admin accounts need the admin code <b>and</b> an email on the admin list.</>
            : <><b>Users</b> ask the support agent questions. <b>Admins</b> also upload
              documents and see the MCP servers and every trace.</>}
        </p>
      </form>
    </div>
  )
}

function detail(data) {
  const d = data?.detail
  if (Array.isArray(d)) return d.map((x) => x.msg?.replace(/^Value error, /, '')).join('; ')
  return typeof d === 'string' ? d : null
}
