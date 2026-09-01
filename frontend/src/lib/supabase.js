import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const isSupabaseConfigured = Boolean(url && anonKey)

// Without Supabase env vars the app runs in guest mode (see VITE_ALLOW_ANONYMOUS
// / backend ALLOW_ANONYMOUS). This stub keeps AuthContext working - no session,
// and any sign-in attempt returns a clear error instead of crashing on import.
function stubClient() {
  const noSession = { data: { session: null }, error: null }
  const notConfigured = {
    data: { session: null, user: null },
    error: new Error('Supabase is not configured - running in guest mode.'),
  }
  return {
    auth: {
      getSession: async () => noSession,
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signInWithPassword: async () => notConfigured,
      signOut: async () => ({ error: null }),
    },
  }
}

if (!isSupabaseConfigured) {
  console.warn(
    'Supabase env vars missing - running in guest mode. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to enable login.',
  )
}

export const supabase = isSupabaseConfigured ? createClient(url, anonKey) : stubClient()
