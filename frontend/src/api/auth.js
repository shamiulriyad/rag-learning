const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:5000'

/**
 * Registers a user through the backend admin endpoint (no confirmation email).
 * Throws Error(message) on failure.
 */
export async function registerUser(email, password) {
  const res = await fetch(`${API_URL}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Sign-up failed (${res.status})`)
  }
}
