import emailjs from '@emailjs/browser'

const PUBLIC_KEY = import.meta.env.VITE_EMAILJS_PUBLIC_KEY as string | undefined
const SERVICE_ID = import.meta.env.VITE_EMAILJS_SERVICE_ID as string | undefined
const TEMPLATE_ID = import.meta.env.VITE_EMAILJS_TEMPLATE_ID as string | undefined

export const emailjsConfigured = Boolean(PUBLIC_KEY && SERVICE_ID && TEMPLATE_ID)

if (!emailjsConfigured) {
  console.warn(
    '[auth] VITE_EMAILJS_PUBLIC_KEY / VITE_EMAILJS_SERVICE_ID / VITE_EMAILJS_TEMPLATE_ID are not set — ' +
    'email OTP will not send. Add them to frontend/.env and restart the dev server.'
  )
}

/** Sends a 6-digit code to `email` via EmailJS. Template must accept `to_email` and `otp_code` variables. */
export async function sendOtpEmail(email: string, code: string): Promise<void> {
  if (!emailjsConfigured) {
    throw new Error('EmailJS is not configured (missing env vars).')
  }
  await emailjs.send(
    SERVICE_ID!,
    TEMPLATE_ID!,
    { to_email: email, email, otp_code: code, passcode: code, code },
    { publicKey: PUBLIC_KEY! },
  )
}

export function generateOtp(): string {
  return Math.floor(100000 + Math.random() * 900000).toString()
}
