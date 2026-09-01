const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:5000'

export async function askQuestion(question, conversationId, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const res = await fetch(`${API_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ question, conversationId }),
  })

  if (res.status === 401) {
    throw new Error('Your session expired. Please sign in again.')
  }
  if (!res.ok) {
    throw new Error(`Request failed (${res.status})`)
  }

  return res.json()
}
