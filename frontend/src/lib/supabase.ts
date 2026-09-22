import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

export const supabaseConfigured = Boolean(url && anonKey)

if (!supabaseConfigured) {
  // Loud in dev console — silent auth failures are the worst kind to debug
  // under hackathon time pressure.
  console.warn(
    '[auth] VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set — email OTP login will not work. ' +
    'Add them to frontend/.env and restart the dev server.'
  )
}

// Dummy fallback values so createClient doesn't throw when unconfigured;
// AuthGate checks supabaseConfigured before ever calling into this client.
export const supabase = createClient(
  url || 'https://placeholder.supabase.co',
  anonKey || 'placeholder-anon-key',
)
