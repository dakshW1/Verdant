/**
 * Builder page (Phase 5 — live)
 * 
 * A full workflow editor that:
 * - Lets the user define steps, step types, dependencies, and quality floors
 * - Calls the live POST /api/plan endpoint with Gemini / Ollama configured
 * - Shows real plan results with model names, carbon, cost
 * - Navigates to the Plan page on success
 */
import { useState, useCallback } from 'react'
import type { Workflow, Step } from '../api/types'
import { api } from '../api/client'
import type { PlanResult } from '../api/types'

// ── Types ─────────────────────────────────────────────────────────────────────
interface DraftStep {
  id: string
  name: string
  step_type: string
  prompt_template: string
  depends_on: string[]
  min_quality: number
  omega: number
  max_tokens: number
}

const STEP_TYPES = [
  'summarization',
  'reasoning',
  'extraction',
  'formatting',
  'code',
  'classification',
  'translation',
  'qa',
]

const STEP_TYPE_COLORS: Record<string, string> = {
  summarization: '#10b981',
  reasoning:     '#8b5cf6',
  extraction:    '#3b82f6',
  formatting:    '#f59e0b',
  code:          '#06b6d4',
  classification:'#f97316',
  translation:   '#ec4899',
  qa:            '#84cc16',
}

const STEP_TYPE_DESCRIPTIONS: Record<string, string> = {
  summarization: 'Condenses a long text into its key points.',
  reasoning:     'Thinks through a problem step by step to reach a conclusion (harder task — usually needs a stronger model).',
  extraction:    'Pulls specific facts or data points out of text.',
  formatting:    'Rewrites text into a clean, specific layout (e.g. markdown, a table).',
  code:          'Writes, reviews, or debugs code (usually needs a stronger model).',
  classification:'Sorts input into one of a few known categories.',
  translation:   'Converts text from one language or style to another.',
  qa:            'Answers a specific question using given information.',
}

/** Small "(?)" icon that shows a plain-language explanation on hover — for jargon a first-time user won't know. */
function Info({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-slate-600 text-slate-500 text-[9px] font-bold cursor-help select-none hover:border-emerald-500 hover:text-emerald-400 ml-1 align-middle"
    >
      ?
    </span>
  )
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

const PRESETS = [
  {
    id: 'market_brief',
    label: '📰 Market Brief',
    description: 'Summarize news → extract signals → write brief',
    inputs: {
      articles:
        "India's electric two-wheeler market crossed 850,000 units sold in FY25, up 28% year-over-year. " +
        'Ola Electric retained the top spot with roughly 34% market share, while TVS iQube and Ather Energy ' +
        'gained ground in Tier-2 cities. The government extended the EMPS subsidy scheme through March 2026 ' +
        'and tightened local battery-manufacturing requirements under the PLI scheme, pushing several importers ' +
        'to announce local assembly plants. Charging infrastructure remains the top-cited barrier to adoption ' +
        'in a recent industry survey of 2,000 prospective buyers.',
    },
    steps: [
      { id: 'summarize', name: 'Summarize news', step_type: 'summarization', prompt_template: 'Summarize the following news articles into key points:\n\n{{input.articles}}', depends_on: [], min_quality: 0.80, omega: 1.0, max_tokens: 400 },
      { id: 'extract',   name: 'Extract signals', step_type: 'extraction',   prompt_template: 'Extract market signals from:\n\n{{summarize.output}}', depends_on: ['summarize'], min_quality: 0.85, omega: 1.2, max_tokens: 300 },
      { id: 'brief',     name: 'Write brief',     step_type: 'formatting',   prompt_template: 'Write a market brief using signals:\n\n{{extract.output}}', depends_on: ['extract'],   min_quality: 0.80, omega: 1.0, max_tokens: 600 },
    ] as DraftStep[],
  },
  {
    id: 'code_review',
    label: '🔍 Code Review',
    description: 'Analyze code → reason about issues → format report',
    inputs: {
      code:
        'def get_user(user_id):\n' +
        '    query = "SELECT * FROM users WHERE id = " + user_id\n' +
        '    result = db.execute(query)\n' +
        '    return result[0]\n\n' +
        'def process_items(items):\n' +
        '    total = 0\n' +
        '    for i in range(len(items) + 1):\n' +
        '        total += items[i].price\n' +
        '    return total\n',
    },
    steps: [
      { id: 'analyze', name: 'Analyze code',    step_type: 'code',      prompt_template: 'Analyze this code for bugs and issues:\n\n{{input.code}}', depends_on: [], min_quality: 0.85, omega: 1.5, max_tokens: 500 },
      { id: 'reason',  name: 'Reason about fixes', step_type: 'reasoning', prompt_template: 'Suggest fixes for the issues:\n\n{{analyze.output}}', depends_on: ['analyze'], min_quality: 0.85, omega: 1.5, max_tokens: 400 },
      { id: 'report',  name: 'Format report',   step_type: 'formatting', prompt_template: 'Format a code review report:\n\n{{reason.output}}', depends_on: ['reason'], min_quality: 0.80, omega: 1.0, max_tokens: 600 },
    ] as DraftStep[],
  },
  {
    id: 'research_qa',
    label: '🔬 Research Q&A',
    description: 'Extract info → reason → answer questions',
    inputs: {
      document:
        'The Reserve Bank of India kept the repo rate unchanged at 6.5% in its latest monetary policy review, ' +
        'citing persistent food price inflation offset by easing core inflation. The central bank revised its ' +
        'GDP growth forecast for the fiscal year to 6.8%, down slightly from 7.0%, and flagged global trade ' +
        'tensions and volatile crude oil prices as key downside risks. The rupee has depreciated roughly 2% ' +
        'against the dollar over the past quarter.',
      question: 'What did the RBI decide about interest rates, and what risks did it flag?',
    },
    steps: [
      { id: 'extract', name: 'Extract facts',   step_type: 'extraction', prompt_template: 'Extract key facts from:\n\n{{input.document}}', depends_on: [], min_quality: 0.80, omega: 1.0, max_tokens: 400 },
      { id: 'reason',  name: 'Reason answers',  step_type: 'reasoning',  prompt_template: 'Answer the question using facts:\n\n{{extract.output}}\n\nQuestion: {{input.question}}', depends_on: ['extract'], min_quality: 0.90, omega: 2.0, max_tokens: 500 },
      { id: 'format',  name: 'Format answer',   step_type: 'formatting', prompt_template: 'Format the answer clearly:\n\n{{reason.output}}', depends_on: ['reason'], min_quality: 0.80, omega: 1.0, max_tokens: 300 },
    ] as DraftStep[],
  },
]

function newStep(idx: number): DraftStep {
  return {
    id: `step_${idx}`,
    name: `Step ${idx}`,
    step_type: 'summarization',
    prompt_template: 'Process: {{input.text}}',
    depends_on: [],
    min_quality: 0.80,
    omega: 1.0,
    max_tokens: 400,
  }
}

// ── Step editor card ──────────────────────────────────────────────────────────
function StepEditor({
  step, index, allIds, simpleMode, onUpdate, onRemove,
}: {
  step: DraftStep
  index: number
  allIds: string[]
  simpleMode: boolean
  onUpdate: (s: DraftStep) => void
  onRemove: () => void
}) {
  const color = STEP_TYPE_COLORS[step.step_type] ?? '#6b7280'
  const otherIds = allIds.filter(id => id !== step.id)

  return (
    <div className="border rounded-xl p-4 space-y-3 transition-all"
      style={{ borderColor: color + '44', background: color + '08' }}>
      <div className="flex items-start gap-3">
        <div
          className="w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold text-white mt-0.5"
          style={{ background: color }}
          title={`Step ${index + 1} of the pipeline`}
        >
          {index + 1}
        </div>
        <div className="flex-1 space-y-3">
          <div className="flex gap-2 items-center flex-wrap">
            {simpleMode ? (
              <input
                value={step.name}
                onChange={e => onUpdate({ ...step, name: e.target.value })}
                className="flex-1 min-w-[140px] bg-[#060f09] border border-emerald-900/40 rounded-lg px-2 py-1.5 text-sm font-medium text-slate-100 outline-none focus:border-emerald-600"
                placeholder="What does this step do?"
              />
            ) : (
              <>
                <input
                  value={step.id}
                  onChange={e => onUpdate({ ...step, id: e.target.value })}
                  className="w-28 bg-[#060f09] border border-emerald-900/40 rounded-lg px-2 py-1 text-sm font-mono text-slate-200 outline-none focus:border-emerald-600"
                  placeholder="step_id"
                  title="Internal ID — used by other steps to reference this step's output"
                />
                <input
                  value={step.name}
                  onChange={e => onUpdate({ ...step, name: e.target.value })}
                  className="flex-1 bg-[#060f09] border border-emerald-900/40 rounded-lg px-2 py-1 text-sm text-slate-200 outline-none focus:border-emerald-600"
                  placeholder="Step name"
                />
              </>
            )}
            <select
              value={step.step_type}
              onChange={e => onUpdate({ ...step, step_type: e.target.value })}
              className="bg-[#060f09] border border-emerald-900/40 rounded-lg px-2 py-1.5 text-xs outline-none focus:border-emerald-600"
              style={{ color }}
              title={STEP_TYPE_DESCRIPTIONS[step.step_type]}
            >
              {STEP_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <button onClick={onRemove} title="Remove this step" className="text-slate-600 hover:text-red-400 text-lg leading-none px-1">✕</button>
          </div>

          {simpleMode && (
            <p className="text-[11px] text-slate-500 -mt-1.5">{STEP_TYPE_DESCRIPTIONS[step.step_type]}</p>
          )}

          <div>
            <label className="text-[11px] text-slate-500 block mb-1">
              {simpleMode ? 'Instructions for the AI' : 'Prompt template'}
              {!simpleMode && <Info text="Use {{input.KEY}} for workflow inputs, or {{other_step_id.output}} to insert another step's answer." />}
            </label>
            <textarea
              value={step.prompt_template}
              onChange={e => onUpdate({ ...step, prompt_template: e.target.value })}
              rows={2}
              className="w-full bg-[#060f09] border border-emerald-900/40 rounded-lg px-3 py-2 text-xs font-mono text-slate-300 outline-none focus:border-emerald-600 resize-none"
              placeholder="Prompt template (use {{input.x}} or {{other_step.output}})"
            />
          </div>

          <div className={`grid gap-2 text-xs ${simpleMode ? 'grid-cols-1' : 'grid-cols-3'}`}>
            <div>
              <label className="text-slate-500 block mb-1 flex items-center">
                Quality needed
                <Info text="How good this step's answer must be. If Verdant's first attempt scores lower, it automatically retries with a stronger AI model." />
              </label>
              <input
                type="range" min={0.5} max={1.0} step={0.05}
                value={step.min_quality}
                onChange={e => onUpdate({ ...step, min_quality: +e.target.value })}
                className="w-full accent-emerald-500"
              />
              <span className="text-emerald-400">{(step.min_quality * 100).toFixed(0)}%</span>
            </div>
            {!simpleMode && (
              <>
                <div>
                  <label className="text-slate-500 block mb-1 flex items-center">
                    Importance (ω)
                    <Info text="How much this step's quality counts toward the workflow's overall quality score. Higher = more important." />
                  </label>
                  <input
                    type="range" min={0.5} max={3.0} step={0.5}
                    value={step.omega}
                    onChange={e => onUpdate({ ...step, omega: +e.target.value })}
                    className="w-full accent-emerald-500"
                  />
                  <span className="text-emerald-400">{step.omega}</span>
                </div>
                <div>
                  <label className="text-slate-500 block mb-1 flex items-center">
                    Max answer length
                    <Info text="Upper limit on how many tokens (roughly word-pieces) this step's answer can use." />
                  </label>
                  <input
                    type="number" min={50} max={2000} step={50}
                    value={step.max_tokens}
                    onChange={e => onUpdate({ ...step, max_tokens: +e.target.value })}
                    className="w-full bg-[#060f09] border border-emerald-900/40 rounded-lg px-2 py-1 outline-none focus:border-emerald-600 text-slate-200"
                  />
                </div>
              </>
            )}
          </div>

          {otherIds.length > 0 && (
            <div>
              <label className="text-slate-500 text-xs block mb-1 flex items-center">
                Runs after (needs their answer first)
                <Info text="This step will wait until the selected steps finish, and can use their output in its instructions." />
              </label>
              <div className="flex flex-wrap gap-2">
                {otherIds.map(depId => {
                  const selected = step.depends_on.includes(depId)
                  return (
                    <button
                      key={depId}
                      onClick={() => onUpdate({
                        ...step,
                        depends_on: selected
                          ? step.depends_on.filter(d => d !== depId)
                          : [...step.depends_on, depId],
                      })}
                      className={`px-2 py-0.5 rounded-full text-xs border transition-colors ${
                        selected
                          ? 'border-emerald-500 bg-emerald-950/50 text-emerald-400'
                          : 'border-slate-700 text-slate-500 hover:border-slate-500'
                      }`}
                    >
                      {selected ? '✓ ' : ''}{depId}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Plan result summary ───────────────────────────────────────────────────────
const MODEL_BADGES: Record<string, { label: string; color: string }> = {
  small:    { label: 'gemini-2.5-flash-lite', color: '#10b981' },
  medium:   { label: 'gemini-2.5-flash',      color: '#3b82f6' },
  large:    { label: 'gemini-2.5-pro',        color: '#f59e0b' },
  'local-3b': { label: 'llama3.2:3b (local)', color: '#8b5cf6' },
}

function PlanSummaryCard({ plan, onViewPlan }: { plan: PlanResult; onViewPlan: (planId: string) => void }) {
  const savedG = plan.baselines.naive.carbon_g - plan.totals.carbon_g
  const savedPct = (savedG / Math.max(plan.baselines.naive.carbon_g, 1e-9)) * 100

  return (
    <div className="bg-[#060f09] border border-emerald-700/40 rounded-2xl p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-slate-100">Plan ready</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Solver: <span className="text-emerald-400">{plan.solver}</span> ·
            Status: <span className={plan.status === 'optimal' ? 'text-emerald-400' : 'text-blue-400'}>{plan.status}</span> ·
            {plan.solve_ms}ms
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-emerald-400">{savedPct.toFixed(0)}%</div>
          <div className="text-xs text-slate-500">carbon saved vs naive</div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { l: 'Carbon', v: `${plan.totals.carbon_g.toFixed(4)} g`, s: `robust: ${plan.totals.carbon_g_robust.toFixed(4)}g` },
          { l: 'Makespan', v: `${plan.totals.makespan_s}s`, s: `saved ${savedPct.toFixed(0)}% CO₂` },
          { l: 'Cost', v: `$${plan.totals.cost_usd.toFixed(5)}`, s: `vs $${plan.baselines.naive.cost_usd.toFixed(5)} naive` },
          { l: 'Quality', v: `${(plan.totals.quality * 100).toFixed(1)}%`, s: `energy: ${(plan.totals.energy_wh * 1000).toFixed(2)} mWh` },
        ].map(({ l, v, s }) => (
          <div key={l} className="bg-[#0a1a10] rounded-xl p-3">
            <div className="text-xs text-slate-500">{l}</div>
            <div className="text-lg font-bold text-emerald-400 mt-0.5">{v}</div>
            <div className="text-xs text-slate-500 mt-0.5">{s}</div>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        {plan.steps.map(sp => {
          const badge = MODEL_BADGES[sp.option.model]
          return (
            <div key={sp.step_id} className="flex items-center gap-3 text-sm">
              <div className="w-2 h-2 rounded-full flex-shrink-0 bg-emerald-600" />
              <span className="font-medium text-slate-200 w-28 truncate">{sp.step_id}</span>
              <span
                className="px-2 py-0.5 rounded-full text-xs border"
                style={{ color: badge?.color ?? '#6b7280', borderColor: (badge?.color ?? '#6b7280') + '44', background: (badge?.color ?? '#6b7280') + '11' }}
              >
                {badge?.label ?? sp.option.model}
              </span>
              {sp.option.mode === 'cascade' && (
                <span className="text-xs text-slate-500">→ cascade</span>
              )}
              <span className="text-xs text-slate-500 ml-auto">{sp.option.site}</span>
              <span className="text-xs text-emerald-500 w-24 text-right">{sp.carbon_g_expected.toFixed(4)} gCO₂e</span>
              {sp.is_critical && <span className="text-xs text-red-400">⚡ critical</span>}
            </div>
          )
        })}
      </div>

      <div className="pt-3 flex justify-end gap-3 border-t border-emerald-900/30">
        <button
          onClick={() => onViewPlan(plan.plan_id)}
          className="px-6 py-2.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold rounded-xl text-xs shadow-md shadow-emerald-950/40 transition-all hover:scale-105 flex items-center gap-1.5"
        >
          <span>📊 View Schedule & Gantt Chart</span>
          <span>→</span>
        </button>
      </div>
    </div>
  )
}

// ── Main Builder page ─────────────────────────────────────────────────────────
interface BuilderPageProps {
  onPlan: (planId: string) => void
}


export function BuilderPage({ onPlan }: BuilderPageProps) {
  const [steps, setSteps] = useState<DraftStep[]>(PRESETS[0].steps)
  const [workflowId, setWorkflowId] = useState('market_brief')
  const [workflowName, setWorkflowName] = useState('Market Brief')
  const [inputs, setInputs] = useState<Record<string, string>>(PRESETS[0].inputs)

  const [deadline, setDeadline] = useState(600)
  const [qualityFloor, setQualityFloor] = useState(0.80)
  const [preset, setPreset] = useState('balanced')
  const [solver, setSolver] = useState('auto')
  const [simpleMode, setSimpleMode] = useState(true)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [planResult, setPlanResult] = useState<PlanResult | null>(null)

  // Tracks whether the user has typed anything of their own since the last example
  // was loaded, so switching examples can warn before wiping their work.
  const [dirty, setDirty] = useState(false)
  const [confirmPresetId, setConfirmPresetId] = useState<string | null>(null)

  const allIds = steps.map(s => s.id)

  const loadPreset = useCallback((presetId: string) => {
    const p = PRESETS.find(x => x.id === presetId)
    if (p) {
      setSteps(p.steps)
      setWorkflowId(presetId)
      setWorkflowName(p.label.replace(/^[^\s]+ /, ''))
      setInputs(p.inputs)
      setPlanResult(null)
      setError(null)
      setDirty(false)
    }
  }, [])

  const selectPreset = useCallback((presetId: string) => {
    if (presetId === workflowId && !dirty) return
    if (dirty) {
      setConfirmPresetId(presetId)
    } else {
      loadPreset(presetId)
    }
  }, [dirty, workflowId, loadPreset])

  const addStep = () => { setDirty(true); setSteps(prev => [...prev, newStep(prev.length + 1)]) }
  const updateStep = (i: number, s: DraftStep) => { setDirty(true); setSteps(prev => prev.map((x, j) => j === i ? s : x)) }
  const removeStep = (i: number) => { setDirty(true); setSteps(prev => prev.filter((_, j) => j !== i)) }

  const handlePlan = useCallback(async () => {
    setLoading(true)
    setError(null)
    setPlanResult(null)
    try {
      const workflow: Workflow = {
        id: workflowId,
        name: workflowName,
        inputs,
        steps: steps.map((s): Step => ({
          id: s.id,
          name: s.name,
          step_type: (s.step_type as import('../api/types').StepType) || 'summarization',
          prompt_template: s.prompt_template,
          depends_on: s.depends_on,
          // The global "Quality needed" slider is a floor for every step — a step
          // can ask for more than that, but never less, so raising the slider
          // always raises what the workflow actually delivers.
          min_quality: Math.max(s.min_quality, qualityFloor),
          omega: s.omega,
          max_tokens_out: s.max_tokens,
          release_s: 0,
          cascade_allowed: true,
        })),

      }
      const result = await api.plan({
        workflow,
        constraints: {
          deadline_s: deadline,
          quality_floor: qualityFloor,
          allow_deferral: true,
          allow_cascade: true,
        } as never,
        preset: preset || undefined,
        solver: solver as never,
      })
      setPlanResult(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [steps, workflowId, workflowName, deadline, qualityFloor, preset, solver])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-bold text-slate-100">Workflow Builder</h1>
          <p className="text-slate-400 text-sm mt-1.5 leading-relaxed">
            Describe your task as a short list of steps below (pick a ready-made example, or write your own).
            Verdant then figures out — for each step — the cheapest, greenest AI model and location that still
            meets your deadline and quality needs.
          </p>
        </div>

        <div className="flex gap-2 shrink-0 items-center">
          <button
            onClick={() => setSimpleMode(m => !m)}
            title="Advanced mode shows extra controls (step IDs, importance weights, token limits, solver choice) for power users"
            className="px-3 py-2.5 text-xs font-medium rounded-xl border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
          >
            {simpleMode ? '⚙️ Show advanced options' : '✓ Simple view'}
          </button>
          <button
            onClick={handlePlan}
            disabled={loading || steps.length === 0}
            className="flex items-center gap-2 px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl transition-all hover:scale-105 hover:shadow-lg hover:shadow-emerald-900/50 disabled:opacity-50 disabled:scale-100"
          >
            {loading
              ? <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Planning…</>
              : <>🌿 Plan Workflow</>
            }
          </button>
          {planResult && (
            <button
              onClick={() => onPlan(planResult.plan_id)}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-xl transition-all hover:scale-105"
            >
              View Full Plan →
            </button>
          )}
        </div>
      </div>

      {/* Live API badges */}
      <div className="flex flex-wrap gap-2">
        <span
          className="flex items-center gap-1.5 text-xs border border-emerald-800/50 bg-emerald-950/30 text-emerald-400 px-3 py-1 rounded-full"
          title="Runs call the real Google Gemini API, not a simulation"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          Real Gemini AI calls
        </span>
        <span
          className="flex items-center gap-1.5 text-xs border border-purple-800/50 bg-purple-950/30 text-purple-400 px-3 py-1 rounded-full"
          title="An optional model that runs on your own computer instead of the cloud — zero network carbon cost"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
          Local model available
        </span>
        <span
          className="flex items-center gap-1.5 text-xs border border-amber-800/50 bg-amber-950/30 text-amber-400 px-3 py-1 rounded-full"
          title="Electricity carbon-intensity numbers are realistic estimates, not live measurements, unless you configure a live carbon API"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          Carbon numbers are estimates
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Workflow config */}
        <div className="lg:col-span-2 space-y-4">
          {/* Preset selector */}
          <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-5">
            <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
              <h2 className="font-semibold text-slate-100">Workflow</h2>
              <div className="flex flex-col items-end gap-1">
                <span className="text-[10px] text-slate-500">Start from a ready-made example:</span>
                <div className="flex gap-2">
                  {PRESETS.map(p => (
                    <button
                      key={p.id}
                      onClick={() => selectPreset(p.id)}
                      title={`${p.description} — loading this replaces the steps below`}
                      className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
                        workflowId === p.id
                          ? 'border-emerald-500 bg-emerald-950/40 text-emerald-300'
                          : 'border-slate-700 text-slate-400 hover:border-slate-500'
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {confirmPresetId && (
              <div className="mt-3 mb-1 flex items-center justify-between gap-3 bg-amber-950/30 border border-amber-800/50 rounded-xl px-4 py-2.5 text-xs text-amber-200">
                <span>
                  Load <strong>{PRESETS.find(p => p.id === confirmPresetId)?.label}</strong>? This will replace the steps and prompts you've written below.
                </span>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => setConfirmPresetId(null)}
                    className="px-3 py-1 rounded-lg border border-slate-600 text-slate-300 hover:border-slate-400"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => { loadPreset(confirmPresetId); setConfirmPresetId(null) }}
                    className="px-3 py-1 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-semibold"
                  >
                    Replace steps
                  </button>
                </div>
              </div>
            )}

            <div className="flex gap-3 mb-4 mt-3">
              {!simpleMode && (
                <input
                  value={workflowId}
                  onChange={e => setWorkflowId(e.target.value)}
                  className="w-36 bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm font-mono text-slate-200 outline-none focus:border-emerald-600"
                  placeholder="workflow_id"
                  title="Internal ID for this workflow"
                />
              )}
              <input
                value={workflowName}
                onChange={e => { setDirty(true); setWorkflowName(e.target.value) }}
                className="flex-1 bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-600"
                placeholder="Name this workflow"
              />
            </div>

            {/* Step editors */}
            <div className="space-y-3">
              {steps.map((step, i) => (
                <StepEditor
                  key={i}
                  step={step}
                  index={i}
                  allIds={allIds}
                  simpleMode={simpleMode}
                  onUpdate={s => updateStep(i, s)}
                  onRemove={() => removeStep(i)}
                />
              ))}
              <button
                onClick={addStep}
                className="w-full py-2 border-2 border-dashed border-emerald-900/40 rounded-xl text-slate-600 hover:text-slate-400 hover:border-emerald-800 transition-colors text-sm"
              >
                + Add another step
              </button>
            </div>
          </div>
        </div>

        {/* Right: Constraints */}
        <div className="space-y-4">
          <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-5 space-y-4">
            <div>
              <h2 className="font-semibold text-slate-100">Your requirements</h2>
              <p className="text-[11px] text-slate-500 mt-0.5">Verdant will find the greenest plan that still satisfies these.</p>
            </div>

            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400 flex items-center">
                  Deadline
                  <Info text="The whole workflow must finish within this much time, from the moment you click Run." />
                </span>
                <span className="text-emerald-400 font-medium">{formatDuration(deadline)}</span>
              </div>
              <input type="range" min={60} max={3600} step={30} value={deadline}
                onChange={e => setDeadline(+e.target.value)}
                className="w-full accent-emerald-500" />
              <div className="flex justify-between text-xs text-slate-600 mt-0.5">
                <span>1 min</span><span>1 hour</span>
              </div>
            </div>

            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400 flex items-center">
                  Quality needed
                  <Info text="Minimum answer quality across every step. Raise this for more careful (but slower/costlier) answers; if a real answer falls short, Verdant automatically retries with a stronger model." />
                </span>
                <span className="text-emerald-400 font-medium">{(qualityFloor * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={0.5} max={1.0} step={0.05} value={qualityFloor}
                onChange={e => setQualityFloor(+e.target.value)}
                className="w-full accent-emerald-500" />
              <div className="flex justify-between text-xs text-slate-600 mt-0.5">
                <span>Draft quality</span><span>Highest quality</span>
              </div>
            </div>

            <div>
              <label className="text-xs text-slate-400 block mb-1 flex items-center">
                What matters most?
                <Info text="Tells Verdant how to balance speed, cost, and carbon when there's a tradeoff. Quality is always protected by the slider above." />
              </label>
              <select value={preset} onChange={e => setPreset(e.target.value)}
                className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-600">
                <option value="green">🌿 Lowest carbon (recommended)</option>
                <option value="balanced">⚖️ Balanced</option>
                <option value="fast">⚡ Fastest</option>
                <option value="cheap">💰 Cheapest</option>
              </select>
            </div>

            {!simpleMode && (
              <div>
                <label className="text-xs text-slate-400 block mb-1 flex items-center">
                  Planning method
                  <Info text="Auto tries an exact mathematical optimizer (CP-SAT) first and falls back to a fast rule-of-thumb (Greedy) if that takes too long or isn't available. Most people should leave this on Auto." />
                </label>
                <select value={solver} onChange={e => setSolver(e.target.value)}
                  className="w-full bg-[#0a1a10] border border-emerald-900/40 rounded-lg px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-600">
                  <option value="auto">Auto (recommended)</option>
                  <option value="greedy">Fast estimate (Greedy)</option>
                  <option value="cpsat">Exact optimum (CP-SAT, slower)</option>
                </select>
              </div>
            )}

            {/* Models info */}
            <div className="border-t border-emerald-900/30 pt-4 space-y-2">
              {simpleMode ? (
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Verdant automatically picks between a small/fast, medium, and large AI model
                  (plus an optional local one) for each step — you don't need to choose.
                </p>
              ) : (
                <>
                  <div className="text-xs text-slate-500 mb-2">Models Verdant can choose from</div>
                  {[
                    { id: 'S', name: 'gemini-2.5-flash-lite', note: 'fast, cheap', color: '#10b981' },
                    { id: 'M', name: 'gemini-2.5-flash', note: 'balanced', color: '#3b82f6' },
                    { id: 'L', name: 'gemini-2.5-pro', note: 'highest quality', color: '#f59e0b' },
                    { id: '3B', name: 'llama3.2:3b', note: '0 carbon (local)', color: '#8b5cf6' },
                  ].map(m => (
                    <div key={m.id} className="flex items-center gap-2 text-xs">
                      <span className="w-6 h-6 rounded flex items-center justify-center font-bold text-[10px] flex-shrink-0"
                        style={{ background: m.color + '22', color: m.color }}>{m.id}</span>
                      <span className="text-slate-300">{m.name}</span>
                      <span className="text-slate-600 ml-auto">{m.note}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Estimates notice */}
          <div className="text-xs text-slate-600 leading-relaxed bg-[#060f09] border border-slate-800/50 rounded-xl p-3">
            ⚠️ Carbon and energy numbers are <strong className="text-slate-500">estimates</strong>, not direct measurements — the AI responses themselves are always real.
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-950/40 border border-red-800/40 rounded-xl p-4 text-red-300 text-sm">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Plan result */}
      {planResult && <PlanSummaryCard plan={planResult} onViewPlan={onPlan} />}
    </div>
  )
}

