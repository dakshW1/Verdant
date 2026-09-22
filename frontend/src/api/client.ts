/**
 * Verdant API client — typed wrappers around the FastAPI backend.
 * Uses the Vite dev proxy to forward /api calls to port 8000.
 */
import type { CIForecast, PlanResult, Workflow } from './types'

const BASE = '/api'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export interface PlanRequest {
  workflow: Workflow
  constraints?: Partial<import('./types').Constraints>
  weights?: Partial<import('./types').Weights>
  preset?: string
  solver?: import('./types').SolverType
}

export const api = {
  health: () => fetchJson<Record<string, unknown>>('/health'),
  models: () => fetchJson<Record<string, unknown>>('/models'),
  sites: () => fetchJson<Record<string, unknown>>('/sites'),

  carbonForecast: (zones: string[], horizon_s = 86400, window_s = 1800) =>
    fetchJson<CIForecast[]>(
      `/carbon/forecast?zones=${zones.join(',')}&horizon_s=${horizon_s}&window_s=${window_s}`
    ),

  validateWorkflow: (workflow: Workflow) =>
    fetchJson<Record<string, unknown>>('/workflows/validate', {
      method: 'POST',
      body: JSON.stringify(workflow),
    }),

  plan: (req: PlanRequest) =>
    fetchJson<PlanResult>('/plan', { method: 'POST', body: JSON.stringify(req) }),

  getPlan: (planId: string) => fetchJson<PlanResult>(`/plan/${planId}`),

  createRun: (planId: string, mode: 'virtual' | 'live' = 'virtual') =>
    fetchJson<{ run_id: string }>('/runs', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, mode }),
    }),

  quickAnswer: (question: string, quality_floor = 0.8, mode: 'virtual' | 'live' = 'virtual') =>
    fetchJson<{ plan_id: string; run_id: string; workflow: Workflow; totals: import('./types').Totals }>(
      '/quick-answer',
      { method: 'POST', body: JSON.stringify({ question, quality_floor, mode }) }
    ),

  getRun: (runId: string) => fetchJson<Record<string, unknown>>(`/runs/${runId}`),
  getReceipt: (runId: string) => fetchJson<Record<string, unknown>>(`/runs/${runId}/receipt`),

  pareto: (req: PlanRequest) =>
    fetchJson<{ points: import('./types').Totals[] }>('/pareto', { method: 'POST', body: JSON.stringify(req) }),

  /** SSE stream — returns EventSource; caller must close it. */
  runEvents: (runId: string) => new EventSource(`${BASE}/runs/${runId}/events`),
}
