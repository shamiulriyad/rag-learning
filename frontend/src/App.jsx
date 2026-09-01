import ChatBox from './components/ChatBox'
import Login from './components/Login'
import { useAuth } from './context/AuthContext'
import { isSupabaseConfigured } from './lib/supabase'
import './App.css'

// Guest mode: explicitly opted in, or unavoidable because Supabase is not set up.
const allowAnonymous =
  import.meta.env.VITE_ALLOW_ANONYMOUS === 'true' || !isSupabaseConfigured

export default function App() {
  const { user, loading, signOut } = useAuth()
  const showChat = Boolean(user) || allowAnonymous

  return (
    <main className="app">
      <header>
        <div>
          <h1>English Learning Assistant</h1>
          <p>Powered by RAG over your grammar book</p>
        </div>
        {user ? (
          <div className="account">
            <span>{user.email}</span>
            <button type="button" onClick={signOut}>
              Log out
            </button>
          </div>
        ) : (
          showChat && <div className="account"><span>Guest</span></div>
        )}
      </header>

      {loading ? (
        <p className="empty">Loading…</p>
      ) : showChat ? (
        <ChatBox />
      ) : (
        <Login />
      )}
    </main>
  )
}
