/**
 * Verdant TypeScript types — manually bootstrapped from schemas.py.
 * Phase 5 will replace this with auto-generated types from openapi-typescript.
 */

export type StepType =
  | 'planning'
  | 'extraction'
  | 'summarization'
  | 'reasoning'
  | 'verification'
  | 'formatting'
  | 'code'

export type SolverType = 'greedy' | 'cpsat' | 'auto'
export type PlanStatus = 'optimal' | 'feasible' | 'relaxed' | 'infeasible'
export type RunMode = 'virtual' | 'live'
export type CarbonSource = 'live' | 'snapshot' | 'synthetic'

export interface Step {
  id: string
  name: string
  step_type: StepType
  prompt_template: string
  depends_on: string[]
  omega: number
  min_quality: number
  est_tokens_in?: number
  est_tokens_out?: number
  max_tokens_out: number
  release_s: number
  deadline_s?: number
  cascade_allowed: boolean
  allowed_sites?: string[]
  verifier?: 'schema' | 'code_exec' | 'llm_judge' | 'none'
  output_schema?: Record<string, unknown>
}

export interface Workflow {
  id: string
  name: string
  inputs: Record<string, string>
  steps: Step[]
}

export interface Constraints {
  deadline_s: number
  carbon_budget_g?: number
  cost_budget_usd?: number
  quality_floor: number
  robust_z: number
  start_time_iso?: string
  allow_deferral: boolean
  allow_cascade: boolean
  allowed_sites?: string[]
}

export interface Weights {
  latency: number
  cost: number
  energy: number
  carbon: number
  quality: number
}

export interface ConfigOption {
  step_id: string
  model: string
  site: string
  mode: 'single' | 'cascade'
  escalate_model?: string
  verifier_model?: string
  dur_expected_s: number
  dur_worstcase_s: number
  energy_wh: number
  energy_wh_worst: number
  cost_usd: number
  quality: number
  p_accept?: number
  tokens_in: number
  tokens_out: number
}

export interface StepPlan {
  step_id: string
  option: ConfigOption
  start_s: number
  slack_s: number
  is_critical: boolean
  carbon_g_expected: number
  carbon_g_robust: number
  ci_g_per_kwh: number
  rationale: string
}

export interface Totals {
  makespan_s: number
  cost_usd: number
  energy_wh: number
  carbon_g: number
  carbon_g_robust: number
  quality: number
}

export interface PlanResult {
  plan_id: string
  status: PlanStatus
  steps: StepPlan[]
  totals: Totals
  baselines: Record<string, Totals>
  relaxations: Array<Record<string, unknown>>
  pareto: Totals[]
  solver: 'greedy' | 'cpsat'
  solve_ms: number
}

export interface StepRunResult {
  step_id: string
  option_used: ConfigOption
  escalated: boolean
  start_s: number
  end_s: number
  tokens_in: number
  tokens_out: number
  energy_wh: number
  carbon_g: number
  cost_usd: number
  verifier_score?: number
  output_text: string
  model_used?: string
}

export interface RunSummary {
  run_id: string
  plan_id: string
  status: 'running' | 'completed' | 'failed'
  mode: RunMode
  steps?: StepRunResult[]
  totals?: Totals
  final_output?: string
}

export interface ReceiptEquivalent {
  label: string
  value: number
  note: string
}

export interface AblationStage {
  label: string
  carbon_g: number
  delta_g: number
}

export interface CarbonReceipt {
  run_id: string
  plan_id: string
  actual: Totals
  naive_baseline: Totals
  saved_carbon_g: number
  saved_pct: number
  saved_cost_usd: number
  latency_delta_s: number
  quality_delta: number
  equivalents: ReceiptEquivalent[]
  ablation_stages: AblationStage[]
  estimates_badge: string
  final_output?: string
  step_outputs?: Record<string, string>
}

export interface CIForecast {
  zone: string
  window_s: number
  start_ts: number
  mean: number[]
  sigma: number[]
  source: CarbonSource
}

export interface PlanRequest {
  workflow: Workflow
  constraints?: Partial<Constraints>
  weights?: Weights
  preset?: string
  solver?: SolverType
}

// Site tier colors for UI

export const SITE_COLORS: Record<string, string> = {
  'local': '#6366f1',
  'gcp-mumbai': '#f59e0b',
  'gcp-delhi': '#ef4444',
  'gcp-singapore': '#8b5cf6',
  'gcp-finland': '#10b981',
}

export const STEP_TYPE_COLORS: Record<StepType, string> = {
  planning: '#3b82f6',
  extraction: '#8b5cf6',
  summarization: '#06b6d4',
  reasoning: '#f59e0b',
  verification: '#ef4444',
  formatting: '#10b981',
  code: '#f97316',
}
