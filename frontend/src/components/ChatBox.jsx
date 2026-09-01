import { useRef, useState } from 'react'
import { askQuestion } from '../api/chat'
import { useAuth } from '../context/AuthContext'
import Message from './Message'

export default function ChatBox() {
  const { token } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const conversationId = useRef(crypto.randomUUID())

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
        { role: 'assistant', content: data.answer, sources: data.sources },
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
      </form>
    </div>
  )
}
