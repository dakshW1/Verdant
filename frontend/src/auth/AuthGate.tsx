/**
 * Email OTP auth gate — hackathon-speed implementation using EmailJS
 * (sends mail directly from the browser, free tier, no backend needed).
 *
 * Wrap the app with <AuthGate>...</AuthGate>. Renders a login screen until
 * the user verifies a 6-digit code sent to their email; then renders
 * children. Session persists across reloads via localStorage.
 *
 * NOTE: verification happens client-side (the generated code is compared in
 * the browser, not on a server). That's an accepted simplification for a
 * time-boxed hackathon demo, not a hardened auth system — anyone with
 * devtools open on their *own* browser could inspect the code, but they
 * still need real access to the target inbox to receive it in the first
 * place for someone else's email.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { emailjsConfigured, generateOtp, sendOtpEmail } from '../lib/emailOtp'

const SESSION_KEY = 'verdant_auth_session'
const OTP_TTL_MS = 10 * 60 * 1000 // 10 minutes

interface AuthSession {
  email: string
  signedInAt: number
}

interface AuthContextValue {
  session: AuthSession | null
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthGate>')
  return ctx
}

type Stage = 'checking' | 'enter-email' | 'enter-code' | 'signed-in'

function loadSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    return raw ? (JSON.parse(raw) as AuthSession) : null
  } catch {
    return null
  }
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [stage, setStage] = useState<Stage>('checking')
  const [session, setSession] = useState<AuthSession | null>(null)
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [pendingOtp, setPendingOtp] = useState<{ code: string; expiresAt: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  useEffect(() => {
    const existing = loadSession()
    setSession(existing)
    setStage(existing ? 'signed-in' : 'enter-email')
  }, [])

  const sendCode = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!email.trim()) return
    setLoading(true)
    setError(null)
    setInfo(null)
    try {
      const otp = generateOtp()
      await sendOtpEmail(email.trim(), otp)
      setPendingOtp({ code: otp, expiresAt: Date.now() + OTP_TTL_MS })
      setInfo(`Code sent to ${email.trim()} — check your inbox (and spam folder).`)
      setStage('enter-code')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send code.')
    } finally {
      setLoading(false)
    }
  }

  const verifyCode = (e?: React.FormEvent) => {
    e?.preventDefault()
    setError(null)
    if (!pendingOtp) {
      setError('No code was sent yet — go back and request one.')
      return
    }
    if (Date.now() > pendingOtp.expiresAt) {
      setError('That code expired. Please request a new one.')
      return
    }
    if (code.trim() !== pendingOtp.code) {
      setError('Incorrect code. Please try again.')
      return
    }
    const newSession: AuthSession = { email: email.trim(), signedInAt: Date.now() }
    localStorage.setItem(SESSION_KEY, JSON.stringify(newSession))
    setSession(newSession)
    setStage('signed-in')
  }

  const signOut = () => {
    localStorage.removeItem(SESSION_KEY)
    setSession(null)
    setEmail('')
    setCode('')
    setPendingOtp(null)
    setStage('enter-email')
  }

  if (stage === 'checking') {
    return (
      <div className="min-h-screen bg-[#020d07] flex items-center justify-center">
        <div className="text-emerald-400 text-sm animate-pulse">Loading…</div>
      </div>
    )
  }

  if (stage === 'signed-in' && session) {
    return <AuthContext.Provider value={{ session, signOut }}>{children}</AuthContext.Provider>
  }

  return (
    <div className="min-h-screen bg-[#020d07] text-slate-200 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-[#060f09] border border-emerald-900/40 rounded-2xl p-7 space-y-5 shadow-2xl">
        <div className="text-center space-y-1">
          <div className="text-2xl">🌿</div>
          <h1 className="text-lg font-bold text-white">Sign in to Verdant</h1>
          <p className="text-xs text-slate-500">We'll email you a one-time code — no password needed.</p>
        </div>

        {!emailjsConfigured && (
          <div className="text-xs text-amber-300 bg-amber-950/40 border border-amber-800/50 rounded-lg p-2.5">
            Email sending isn't configured yet. Add <code className="font-mono">VITE_EMAILJS_PUBLIC_KEY</code>,{' '}
            <code className="font-mono">VITE_EMAILJS_SERVICE_ID</code>, and{' '}
            <code className="font-mono">VITE_EMAILJS_TEMPLATE_ID</code> to <code className="font-mono">frontend/.env</code>,
            then restart the dev server.
          </div>
        )}

        {stage === 'enter-email' && (
          <form onSubmit={sendCode} className="space-y-3">
            <input
              type="email"
              required
              autoFocus
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-emerald-600"
            />
            <button
              type="submit"
              disabled={loading || !emailjsConfigured}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold rounded-lg text-sm transition-colors"
            >
              {loading ? 'Sending…' : 'Send code'}
            </button>
          </form>
        )}

        {stage === 'enter-code' && (
          <form onSubmit={verifyCode} className="space-y-3">
            <p className="text-xs text-slate-400">
              Enter the 6-digit code sent to <span className="text-emerald-400">{email}</span>.
            </p>
            <input
              type="text"
              inputMode="numeric"
              autoFocus
              required
              autoComplete="off"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="123456"
              className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-emerald-600 tracking-[0.3em] text-center font-mono"
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold rounded-lg text-sm transition-colors"
            >
              Verify &amp; sign in
            </button>
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => { setStage('enter-email'); setCode(''); setError(null); setInfo(null) }}
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                ← Use a different email
              </button>
              <button
                type="button"
                onClick={() => sendCode()}
                className="text-xs text-emerald-500 hover:text-emerald-300"
              >
                Resend code
              </button>
            </div>
          </form>
        )}

        {info && <div className="text-xs text-emerald-400 bg-emerald-950/30 border border-emerald-800/40 rounded-lg p-2.5">{info}</div>}
        {error && <div className="text-xs text-red-300 bg-red-950/40 border border-red-800/40 rounded-lg p-2.5">{error}</div>}
      </div>
    </div>
  )
}
