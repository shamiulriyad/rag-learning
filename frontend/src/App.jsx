import ChatBox from './components/ChatBox'
import Login from './components/Login'
import { useAuth } from './context/AuthContext'
import './App.css'

export default function App() {
  const { user, loading, signOut } = useAuth()

  return (
    <main className="app">
      <header>
        <div>
          <h1>English Learning Assistant</h1>
          <p>Powered by RAG over your grammar book</p>
        </div>
        {user && (
          <div className="account">
            <span>{user.email}</span>
            <button type="button" onClick={signOut}>
              Log out
            </button>
          </div>
        )}
      </header>

      {loading ? (
        <p className="empty">Loading…</p>
      ) : user ? (
        <ChatBox />
      ) : (
        <Login />
      )}
    </main>
  )
}
