import { useEffect, useRef, useState } from 'react'
import { askQuestion } from '../api/chat'
import { useAuth } from '../context/AuthContext'
import Message from './Message'

const STORAGE_KEY = 'chat:history'

// Restore a previous conversation from localStorage (guest mode has no DB).
function loadSaved() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY))
    if (parsed && Array.isArray(parsed.messages)) {
      return parsed
    }
  } catch {
    // no/invalid saved state - start fresh
  }
  return null
}

export default function ChatBox() {
  const { token } = useAuth()
  const saved = loadSaved()
  const [messages, setMessages] = useState(saved?.messages ?? [])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const conversationId = useRef(saved?.conversationId ?? crypto.randomUUID())

  // Save after every change so the chat survives a reload or closing the tab.
  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ conversationId: conversationId.current, messages }),
      )
    } catch {
      // storage blocked (private mode) or full - not fatal
    }
  }, [messages])

  function clearChat() {
    setMessages([])
    setError('')
    conversationId.current = crypto.randomUUID()
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const question = input.trim()
    if (!question || loading) {
      return
    }

    setError('')
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setLoading(true)

    try {
      const data = await askQuestion(question, conversationId.current, token)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.answer },
      ])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat">
      <div className="history">
        {messages.length === 0 && (
          <p className="empty">Ask a question about the English grammar book.</p>
        )}
        {messages.map((m, i) => (
          <Message key={i} {...m} />
        ))}
        {loading && <div className="message assistant"><div className="bubble">Thinking…</div></div>}
      </div>

      {error && <p className="error">{error}</p>}

      <form className="composer" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          placeholder="e.g. When do I use the present perfect?"
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" disabled={loading}>
          Send
        </button>
        {messages.length > 0 && (
          <button type="button" onClick={clearChat} disabled={loading}>
            Clear
          </button>
        )}
      </form>
    </div>
  )
}
