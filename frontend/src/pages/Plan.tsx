/**
 * Plan page (Phase 5)
 * Shows: SVG Gantt chart, CarbonStrip, Pareto slider, step inspector drawer,
 * constraint panel, and live /api/plan call.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import type { PlanResult, StepPlan, Totals } from '../api/types'
import { api } from '../api/client'
import fixtureData from '../../../fixtures/plan_market_brief.json'

const fixture = fixtureData as PlanResult

// ── Color helpers ────────────────────────────────────────────────────────────
const MODEL_COLORS: Record<string, string> = {
  small: '#10b981',
  medium: '#3b82f6',
  large: '#f59e0b',
  'local-3b': '#8b5cf6',
}
const CI_GRADIENT = (ci: number) => {
  if (ci < 150) return '#10b981'
  if (ci < 300) return '#84cc16'
  if (ci < 500) return '#f59e0b'
  if (ci < 700) return '#f97316'
  return '#ef4444'
}

// ── SVG Gantt ─────────────────────────────────────────────────────────────────
function GanttChart({ steps, deadline }: { steps: StepPlan[]; deadline: number }) {
  const [hovered, setHovered] = useState<string | null>(null)
  const W = 700
  const H = steps.length * 44 + 60
  const PAD = { l: 110, r: 20, t: 30, b: 30 }
  const innerW = W - PAD.l - PAD.r
  const rowH = 36
  const scale = (s: number) => (s / deadline) * innerW

  // x-axis ticks
  const ticks = Array.from({ length: 6 }, (_, i) => Math.round((deadline / 5) * i))

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      {/* Background grid */}
      {ticks.map(t => (
        <line
          key={t}
          x1={PAD.l + scale(t)} y1={PAD.t}
          x2={PAD.l + scale(t)} y2={H - PAD.b}
          stroke="#1a3321" strokeDasharray="3,3"
        />
      ))}

      {/* Deadline line */}
      <line
        x1={PAD.l + innerW} y1={PAD.t - 10}
        x2={PAD.l + innerW} y2={H - PAD.b}
        stroke="#ef4444" strokeWidth={1.5} strokeDasharray="4,3"
      />
      <text x={PAD.l + innerW - 2} y={PAD.t - 14} fill="#ef4444" fontSize={9} textAnchor="end">deadline</text>

      {/* Steps */}
      {steps.map((sp, i) => {
        const y = PAD.t + i * 44 + 4
        const x = PAD.l + scale(sp.start_s)
        const w = Math.max(4, scale(sp.option.dur_expected_s))
        const wWC = scale(sp.option.dur_worstcase_s)
        const color = MODEL_COLORS[sp.option.model] ?? '#6b7280'
        const isHovered = hovered === sp.step_id

        return (
          <g key={sp.step_id} onMouseEnter={() => setHovered(sp.step_id)} onMouseLeave={() => setHovered(null)}>
            {/* Step label */}
            <text x={PAD.l - 8} y={y + rowH / 2 + 4} fill="#94a3b8" fontSize={10} textAnchor="end">
              {sp.step_id}
            </text>

            {/* Slack bar (light) */}
            {sp.slack_s > 0 && (
              <rect
                x={x} y={y + 10}
                width={scale(sp.slack_s)} height={rowH - 20}
                fill={color + '18'} rx={3}
              />
            )}

            {/* Worst-case bar (dim) */}
            <rect
              x={x} y={y + 6}
              width={wWC} height={rowH - 12}
              fill={color + '25'} rx={4}
            />

            {/* Expected bar */}
            <rect
              x={x} y={y + 6}
              width={w} height={rowH - 12}
              fill={color + (isHovered ? 'ee' : 'bb')} rx={4}
              style={{ transition: 'fill 0.15s' }}
            />

            {/* Critical indicator */}
            {sp.is_critical && (
              <circle cx={x - 6} cy={y + rowH / 2} r={3} fill="#ef4444" />
            )}

            {/* Carbon label */}
            <text x={x + w + 4} y={y + rowH / 2 + 4} fill={CI_GRADIENT(sp.ci_g_per_kwh)} fontSize={9}>
              {sp.carbon_g_expected.toFixed(3)}g
            </text>
          </g>
        )
      })}

      {/* X axis ticks */}
      {ticks.map(t => (
        <text key={t} x={PAD.l + scale(t)} y={H - PAD.b + 12} fill="#475569" fontSize={9} textAnchor="middle">
          {t}s
        </text>
      ))}
    </svg>
  )
}

// ── Carbon strip ──────────────────────────────────────────────────────────────
function CarbonStrip({ steps }: { steps: StepPlan[] }) {
  const total = steps.reduce((s, p) => s + p.carbon_g_expected, 0)
  return (
    <div className="flex h-6 rounded-full overflow-hidden gap-px">
      {steps.map(sp => (
        <div
          key={sp.step_id}
          title={`${sp.step_id}: ${sp.carbon_g_expected.toFixed(3)}g CO₂e`}
          style={{
            width: `${(sp.carbon_g_expected / Math.max(total, 0.001)) * 100}%`,
            background: CI_GRADIENT(sp.ci_g_per_kwh),
            minWidth: 4,
          }}
        />
      ))}
    </div>
  )
}

// ── Pareto chart ──────────────────────────────────────────────────────────────
function ParetoChart({ points }: { points: Totals[] }) {
  if (!points.length) return <div className="text-slate-500 text-sm text-center py-8">No Pareto data</div>
  const maxC = Math.max(...points.map(p => p.carbon_g))
  const maxL = Math.max(...points.map(p => p.makespan_s))
  const W = 300, H = 160, PAD = 30

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      <text x={PAD} y={12} fill="#475569" fontSize={9}>Carbon (g)</text>
      <text x={W - PAD} y={H - 4} fill="#475569" fontSize={9} textAnchor="end">Latency (s)</text>

      {/* Axes */}
      <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#1e3a2a" />
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#1e3a2a" />

      {/* Pareto line */}
      <polyline
        points={points.map(p => {
          const x = PAD + ((p.makespan_s / Math.max(maxL, 1)) * (W - 2 * PAD))
          const y = H - PAD - ((p.carbon_g / Math.max(maxC, 1)) * (H - 2 * PAD))
          return `${x},${y}`
        }).join(' ')}
        fill="none" stroke="#10b981" strokeWidth={1.5}
      />

      {/* Points */}
      {points.map((p, i) => {
        const x = PAD + ((p.makespan_s / Math.max(maxL, 1)) * (W - 2 * PAD))
        const y = H - PAD - ((p.carbon_g / Math.max(maxC, 1)) * (H - 2 * PAD))
        return (
          <circle key={i} cx={x} cy={y} r={4}
            fill="#10b981" stroke="#020d07" strokeWidth={1.5}>
            <title>{`Carbon: ${p.carbon_g.toFixed(3)}g | Latency: ${p.makespan_s}s`}</title>
          </circle>
        )
      })}
    </svg>
  )
}

// ── Constraint panel ──────────────────────────────────────────────────────────
interface ConstraintState {
  deadline_s: number
  quality_floor: number
  carbon_budget_g: string
  cost_budget_usd: string
  allow_deferral: boolean
  allow_cascade: boolean
  solver: string
  preset: string
}

function ConstraintPanel({
  value, onChange,
}: {
  value: ConstraintState
  onChange: (v: ConstraintState) => void
}) {
  const set = (k: keyof ConstraintState, v: unknown) => onChange({ ...value, [k]: v })

  return (
    <div className="space-y-4">
      <div>
        <label className="text-xs text-slate-400 block mb-1">Deadline (s)</label>
        <input
          type="range" min={60} max={3600} step={30}
          value={value.deadline_s}
          onChange={e => set('deadline_s', +e.target.value)}
          className="w-full accent-emerald-500"
        />
        <div className="text-xs text-emerald-400 mt-0.5">{value.deadline_s}s</div>
      </div>

      <div>
        <label className="text-xs text-slate-400 block mb-1">Quality floor</label>
        <input
          type="range" min={0} max={1} step={0.05}
          value={value.quality_floor}
          onChange={e => set('quality_floor', +e.target.value)}
          className="w-full accent-emerald-500"
        />
        <div className="text-xs text-emerald-400 mt-0.5">{(value.quality_floor * 100).toFixed(0)}%</div>
      </div>

      <div>
        <label className="text-xs text-slate-400 block mb-1">Carbon budget (g CO₂e, blank = none)</label>
        <input
          type="number" placeholder="e.g. 5"
          value={value.carbon_budget_g}
          onChange={e => set('carbon_budget_g', e.target.value)}
          className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-600"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
          <input
            type="checkbox" checked={value.allow_deferral}
            onChange={e => set('allow_deferral', e.target.checked)}
            className="accent-emerald-500"
          />
          Allow deferral
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
          <input
            type="checkbox" checked={value.allow_cascade}
            onChange={e => set('allow_cascade', e.target.checked)}
            className="accent-emerald-500"
          />
          Allow cascade
        </label>
      </div>

      <div>
        <label className="text-xs text-slate-400 block mb-1">Preset</label>
        <select
          value={value.preset}
          onChange={e => set('preset', e.target.value)}
          className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-600"
        >
          <option value="">Custom</option>
          <option value="green">🌿 Green (minimize carbon)</option>
          <option value="fast">⚡ Fast (minimize latency)</option>
          <option value="balanced">⚖️ Balanced</option>
          <option value="cheap">💰 Cheap (minimize cost)</option>
        </select>
      </div>

      <div>
        <label className="text-xs text-slate-400 block mb-1">Solver</label>
        <select
          value={value.solver}
          onChange={e => set('solver', e.target.value)}
          className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-600"
        >
          <option value="auto">Auto (CP-SAT → greedy)</option>
          <option value="greedy">Greedy</option>
          <option value="cpsat">CP-SAT</option>
        </select>
      </div>
    </div>
  )
}

// ── Step Inspector Drawer ─────────────────────────────────────────────────────
function StepInspector({ step, onClose }: { step: StepPlan; onClose: () => void }) {
  const color = MODEL_COLORS[step.option.model] ?? '#6b7280'
  return (
    <div
      className="fixed inset-y-0 right-0 w-96 bg-[#060f09] border-l border-emerald-900/40 shadow-2xl z-50 flex flex-col"
      onClick={e => e.stopPropagation()}
    >
      <div className="px-6 py-4 border-b border-emerald-900/30 flex items-center justify-between">
        <div>
          <div className="font-semibold text-slate-100">{step.step_id}</div>
          <div className="text-xs text-slate-500">{step.option.mode} · {step.option.site}</div>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-200 text-xl leading-none">✕</button>
      </div>
      <div className="p-6 space-y-5 overflow-y-auto flex-1">
        {/* Model badge */}
        <div className="flex items-center gap-2">
          <span
            className="px-3 py-1 rounded-full text-xs font-bold"
            style={{ background: color + '22', color, border: `1px solid ${color}44` }}
          >{step.option.model.toUpperCase()}</span>
          {step.is_critical && <span className="text-xs text-red-400 font-medium">⚡ Critical path</span>}
        </div>

        {/* Metrics grid */}
        <div className="grid grid-cols-2 gap-3">
          {[
            ['Start', `${step.start_s}s`],
            ['Duration', `${step.option.dur_expected_s}s`],
            ['Worst-case', `${step.option.dur_worstcase_s}s`],
            ['Slack', `${step.slack_s}s`],
            ['Carbon', `${step.carbon_g_expected.toFixed(4)} g`],
            ['Carbon (robust)', `${step.carbon_g_robust.toFixed(4)} g`],
            ['CI', `${step.ci_g_per_kwh.toFixed(0)} gCO₂e/kWh`],
            ['Energy', `${(step.option.energy_wh * 1000).toFixed(2)} mWh`],
            ['Cost', `$${step.option.cost_usd.toFixed(6)}`],
            ['Quality', `${(step.option.quality * 100).toFixed(1)}%`],
            ['Tokens in', `${step.option.tokens_in}`],
            ['Tokens out', `${step.option.tokens_out}`],
          ].map(([l, v]) => (
            <div key={l} className="bg-[#0a1a10] rounded-lg p-3">
              <div className="text-xs text-slate-500">{l}</div>
              <div className="text-sm font-medium text-slate-200 mt-0.5">{v}</div>
            </div>
          ))}
        </div>

        {/* Rationale */}
        <div className="bg-[#0a1a10] rounded-xl p-4">
          <div className="text-xs text-slate-500 mb-2">Rationale</div>
          <p className="text-sm text-slate-300 leading-relaxed">{step.rationale}</p>
        </div>

        {/* Cascade */}
        {step.option.mode === 'cascade' && (
          <div className="bg-blue-950/30 border border-blue-800/40 rounded-xl p-4">
            <div className="text-xs text-blue-400 font-medium mb-1">Cascade mode</div>
            <div className="text-sm text-slate-300">
              {step.option.model} → {step.option.escalate_model}<br />
              P(accept) = {((step.option.p_accept ?? 0.65) * 100).toFixed(0)}%
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Plan page ────────────────────────────────────────────────────────────
interface PlanPageProps {
  onRun: (planId: string) => void
  initialPlanId?: string | null
}

export function PlanPage({ onRun, initialPlanId }: PlanPageProps) {
  const [plan, setPlan] = useState<PlanResult>(fixture)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedStep, setSelectedStep] = useState<StepPlan | null>(null)
  const [paretoPoints, setParetoPoints] = useState<Totals[]>([])
  const [loadingPareto, setLoadingPareto] = useState(false)
  const [showConstraints, setShowConstraints] = useState(false)
  const [constraints, setConstraints] = useState<ConstraintState>({
    deadline_s: 600, quality_floor: 0.85, carbon_budget_g: '',
    cost_budget_usd: '', allow_deferral: true, allow_cascade: true,
    solver: 'auto', preset: 'balanced',
  })

  useEffect(() => {
    if (initialPlanId && initialPlanId !== 'fixture-market-brief-001') {
      api.getPlan(initialPlanId).then(p => {
        if (p) setPlan(p)
      }).catch(() => {})
    }
  }, [initialPlanId])


  const workflowRef = useRef(plan)

  const handlePlan = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const req = {
        workflow: workflowRef.current.steps ? {
          id: 'ui_workflow', name: 'UI Workflow',
          inputs: {}, steps: [],  // in a real UI we'd have editable steps
        } : workflowRef.current,
        constraints: {
          deadline_s: constraints.deadline_s,
          quality_floor: constraints.quality_floor,
          carbon_budget_g: constraints.carbon_budget_g ? +constraints.carbon_budget_g : undefined,
          cost_budget_usd: constraints.cost_budget_usd ? +constraints.cost_budget_usd : undefined,
          allow_deferral: constraints.allow_deferral,
          allow_cascade: constraints.allow_cascade,
        },
        preset: constraints.preset || undefined,
        solver: constraints.solver as 'auto' | 'greedy' | 'cpsat',
      }
      // Use the fixture workflow for now (Builder page will provide real workflow in full impl)
      const result = await api.plan({ ...req, workflow: { ...fixture } as never })
      setPlan(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [constraints])

  const handlePareto = useCallback(async () => {
    setLoadingPareto(true)
    try {
      const result = await api.pareto({ workflow: { ...fixture } as never, constraints: { deadline_s: constraints.deadline_s, quality_floor: constraints.quality_floor } })
      setParetoPoints(result.points)
    } catch { /* ignore */ } finally {
      setLoadingPareto(false)
    }
  }, [constraints])

  const savedG = plan.baselines.naive.carbon_g - plan.totals.carbon_g
  const savedPct = (savedG / Math.max(plan.baselines.naive.carbon_g, 0.001)) * 100

  return (
    <div className="space-y-6" onClick={() => setSelectedStep(null)}>
      {/* Top explainer card in simple terms */}
      <div className="bg-[#030e06] border border-emerald-900/50 rounded-2xl p-4 text-xs text-slate-300 leading-relaxed flex items-start gap-3">
        <span className="text-xl flex-shrink-0">💡</span>
        <div>
          <strong className="text-emerald-400 font-semibold">How to Read the Schedule:</strong> Steps with a <span className="text-red-400 font-bold">Red dot</span> are on the <em>Critical Path</em> (zero slack; cannot be delayed without delaying the entire workflow). Other steps have <em>Slack</em> (headroom) and are strategically time-shifted into low-carbon solar/wind windows or routed to cleaner cloud sites (like Finland hydro at 120 gCO₂e/kWh).
        </div>
      </div>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <span>Workflow Schedule</span>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-950 border border-emerald-800 text-emerald-300 font-mono">
              {plan.plan_id.slice(0, 16)}…
            </span>
          </h1>
          <p className="text-slate-400 text-xs mt-1">
            Solver: <span className="text-emerald-400 font-medium">{plan.solver}</span> ·
            Status: <span className={plan.status === 'optimal' ? 'text-emerald-400 font-semibold' : plan.status === 'feasible' ? 'text-blue-400 font-semibold' : 'text-amber-400 font-semibold'}>{plan.status.toUpperCase()}</span> ·
            {plan.solve_ms}ms
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setShowConstraints(v => !v)}
            className="px-3.5 py-2 text-xs font-semibold border border-emerald-800 rounded-xl text-slate-300 hover:border-emerald-600 bg-[#06170c] transition-colors"
          >
            ⚙️ Constraints
          </button>
          <button
            onClick={handlePareto}
            disabled={loadingPareto}
            className="px-3.5 py-2 text-xs font-semibold border border-blue-800 rounded-xl text-blue-300 hover:border-blue-600 bg-[#06111a] transition-colors disabled:opacity-50"
          >
            {loadingPareto ? 'Calculating…' : '📊 Pareto Frontier'}
          </button>
          <button
            onClick={handlePlan}
            disabled={loading}
            className="px-4 py-2 bg-[#0a2414] hover:bg-[#0f341d] border border-emerald-700 text-emerald-300 font-semibold rounded-xl text-xs transition-all hover:scale-105 disabled:opacity-50 disabled:scale-100"
          >
            {loading ? '⏳ Solving…' : '🌿 Re-plan'}
          </button>
          <button
            onClick={() => onRun(plan.plan_id)}
            className="px-5 py-2 bg-gradient-to-r from-blue-600 to-teal-600 hover:from-blue-500 hover:to-teal-500 text-white font-semibold rounded-xl text-xs shadow-md shadow-blue-900/30 transition-all hover:scale-105 active:scale-95 flex items-center gap-1.5"
          >
            <span>▶ Execute in Run</span>
            <span>→</span>
          </button>
        </div>
      </div>


      {error && (
        <div className="bg-red-950/40 border border-red-800/40 rounded-xl p-4 text-red-300 text-sm">{error}</div>
      )}

      {/* Constraint panel */}
      {showConstraints && (
        <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6">
          <h2 className="font-semibold text-slate-100 mb-4">Constraints</h2>
          <ConstraintPanel value={constraints} onChange={setConstraints} />
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { l: 'Carbon saved', v: `${savedPct.toFixed(0)}%`, s: `vs naive (${savedG.toFixed(3)}g)` },
          { l: 'Total carbon', v: `${plan.totals.carbon_g.toFixed(3)} g`, s: `robust: ${plan.totals.carbon_g_robust.toFixed(3)}g` },
          { l: 'Makespan', v: `${plan.totals.makespan_s}s`, s: `deadline: ${plan.steps.length > 0 ? constraints.deadline_s : '–'}s` },
          { l: 'Cost', v: `$${plan.totals.cost_usd.toFixed(5)}`, s: `vs naive $${plan.baselines.naive.cost_usd.toFixed(5)}` },
          { l: 'Energy', v: `${(plan.totals.energy_wh * 1000).toFixed(2)} mWh`, s: 'estimate' },
          { l: 'Quality', v: `${(plan.totals.quality * 100).toFixed(1)}%`, s: `floor: ${(constraints.quality_floor * 100).toFixed(0)}%` },
        ].map(({ l, v, s }) => (
          <div key={l} className="bg-[#0a1a10] border border-emerald-900/30 rounded-xl p-4">
            <div className="text-xs text-slate-500 uppercase tracking-wider">{l}</div>
            <div className="text-xl font-bold text-emerald-400 mt-1">{v}</div>
            <div className="text-xs text-slate-500 mt-0.5">{s}</div>
          </div>
        ))}
      </div>

      {/* Gantt + Carbon strip */}
      <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-slate-100">Schedule (Gantt)</h2>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {Object.entries(MODEL_COLORS).map(([m, c]) => (
              <span key={m} className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm" style={{ background: c }} />
                {m}
              </span>
            ))}
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />critical</span>
          </div>
        </div>
        <GanttChart steps={plan.steps} deadline={constraints.deadline_s} />
        <div className="space-y-1">
          <div className="text-xs text-slate-500">Carbon distribution</div>
          <CarbonStrip steps={plan.steps} />
        </div>
      </div>

      {/* Pareto chart */}
      {paretoPoints.length > 0 && (
        <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6">
          <h2 className="font-semibold text-slate-100 mb-4">
            Pareto Frontier <span className="text-xs text-slate-500 font-normal ml-1">Carbon vs Latency</span>
          </h2>
          <div className="max-w-sm">
            <ParetoChart points={paretoPoints} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {paretoPoints.map((p, i) => (
              <div key={i} className="bg-[#0a1a10] border border-emerald-900/30 rounded-lg px-3 py-1.5 text-xs">
                <span className="text-emerald-400">{p.carbon_g.toFixed(3)}g</span>
                <span className="text-slate-500 mx-1">·</span>
                <span className="text-blue-400">{p.makespan_s}s</span>
                <span className="text-slate-500 mx-1">·</span>
                <span className="text-slate-400">${p.cost_usd.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Step table */}
      <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-emerald-900/30">
          <h2 className="font-semibold text-slate-100">Step Details</h2>
          <p className="text-xs text-slate-500 mt-0.5">Click a row to inspect</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-emerald-900/20">
                {['Step', 'Site', 'Model', 'Start', 'Dur', 'Slack', 'CI', 'Carbon', 'Quality', 'Rationale'].map(h => (
                  <th key={h} className="py-2 px-3 text-left text-xs text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {plan.steps.map(sp => (
                <tr
                  key={sp.step_id}
                  onClick={e => { e.stopPropagation(); setSelectedStep(sp) }}
                  className={`border-b border-emerald-900/10 cursor-pointer transition-colors hover:bg-emerald-950/20 ${selectedStep?.step_id === sp.step_id ? 'bg-emerald-950/30' : ''}`}
                >
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1.5">
                      {sp.is_critical && <span className="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0" />}
                      <span className="font-medium text-slate-200">{sp.step_id}</span>
                    </div>
                  </td>
                  <td className="py-2 px-3 text-xs text-slate-400">{sp.option.site}</td>
                  <td className="py-2 px-3">
                    <span className="text-xs font-bold" style={{ color: MODEL_COLORS[sp.option.model] ?? '#6b7280' }}>
                      {sp.option.model}
                    </span>
                    {sp.option.mode === 'cascade' && <span className="text-xs text-slate-500 ml-1">→</span>}
                  </td>
                  <td className="py-2 px-3 tabular-nums text-slate-400">{sp.start_s}s</td>
                  <td className="py-2 px-3 tabular-nums text-slate-400">{sp.option.dur_expected_s}s</td>
                  <td className="py-2 px-3 tabular-nums">
                    <span className={sp.slack_s === 0 ? 'text-red-400 font-bold' : 'text-slate-500'}>{sp.slack_s}s</span>
                  </td>
                  <td className="py-2 px-3 text-xs tabular-nums" style={{ color: CI_GRADIENT(sp.ci_g_per_kwh) }}>
                    {sp.ci_g_per_kwh.toFixed(0)}
                  </td>
                  <td className="py-2 px-3 tabular-nums text-emerald-400">{sp.carbon_g_expected.toFixed(4)}g</td>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1.5">
                      <div className="w-12 h-1 bg-[#0a1a10] rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-500" style={{ width: `${sp.option.quality * 100}%` }} />
                      </div>
                      <span className="text-xs text-slate-400">{(sp.option.quality * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="py-2 px-3 text-xs text-slate-500 max-w-xs truncate" title={sp.rationale}>
                    {sp.rationale.slice(0, 60)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Baselines */}
      <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6">
        <h2 className="font-semibold text-slate-100 mb-4">
          Baselines <span className="text-xs text-slate-500 font-normal">(modelled estimates)</span>
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-emerald-900/20">
                {['', 'Carbon (g)', 'Energy (mWh)', 'Cost ($)', 'Latency (s)', 'Quality'].map(h => (
                  <th key={h} className="py-2 px-3 text-left text-xs text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { key: 'verdant', label: '🌿 Verdant', t: plan.totals, hi: true },
                { key: 'naive', label: 'Naive (large)', t: plan.baselines.naive },
                { key: 'fastest', label: 'Fastest (medium)', t: plan.baselines.fastest },
                { key: 'smallest', label: 'Smallest (S only)', t: plan.baselines.smallest },
              ].map(({ key, label, t, hi }) => (
                <tr key={key} className={`border-b border-emerald-900/10 ${hi ? 'bg-emerald-950/20' : ''}`}>
                  <td className="py-2 px-3 font-medium text-slate-200">{label}</td>
                  <td className="py-2 px-3 tabular-nums text-emerald-400">{t.carbon_g.toFixed(4)}</td>
                  <td className="py-2 px-3 tabular-nums text-slate-300">{(t.energy_wh * 1000).toFixed(2)}</td>
                  <td className="py-2 px-3 tabular-nums text-slate-300">{t.cost_usd.toFixed(5)}</td>
                  <td className="py-2 px-3 tabular-nums text-slate-300">{t.makespan_s}</td>
                  <td className="py-2 px-3 tabular-nums text-slate-300">{(t.quality * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Step inspector drawer */}
      {selectedStep && (
        <StepInspector step={selectedStep} onClose={() => setSelectedStep(null)} />
      )}
    </div>
  )
}
