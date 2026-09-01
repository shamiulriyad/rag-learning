import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

export default function Login() {
  const { signIn, signUp } = useAuth()
  const [mode, setMode] = useState('signin') // 'signin' | 'signup'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setMessage('')
    setBusy(true)

    try {
      const action = mode === 'signin' ? signIn : signUp
      const { error } = await action(email.trim(), password)
      if (error) {
        setMessage(error.message)
      }
      // on success the auth state changes and this screen unmounts
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-card">
      <h2>{mode === 'signin' ? 'Sign in' : 'Create account'}</h2>

      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            value={email}
            required
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            required
            minLength={6}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Sign up'}
        </button>
      </form>

      {message && <p className="auth-message">{message}</p>}

      <button
        type="button"
        className="link-button"
        onClick={() => {
          setMode(mode === 'signin' ? 'signup' : 'signin')
          setMessage('')
        }}
      >
        {mode === 'signin'
          ? "Don't have an account? Sign up"
          : 'Already have an account? Sign in'}
      </button>
    </div>
  )
}
