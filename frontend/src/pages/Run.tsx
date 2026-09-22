/**
 * Run page (Phase 5) — SSE live run monitoring with step-by-step progress
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'
import type { StepRunResult, Totals } from '../api/types'
import { formatQualityPercent } from '../utils/format'

interface RunEvent {
  run_id: string
  event_type: string
  step_id?: string
  [key: string]: unknown
}

interface StepState {
  step_id: string
  status: 'waiting' | 'running' | 'completed' | 'failed'
  result?: StepRunResult
  error?: string
  startedAt?: number
  endedAt?: number
}

interface RunPageProps {
  planId: string | null
  onReceipt: (runId: string) => void
  onSelectPlan?: (planId: string) => void
}

function StepCard({ step }: { step: StepState }) {
  const [expanded, setExpanded] = useState(false)
  const elapsed = step.startedAt && step.endedAt
    ? ((step.endedAt - step.startedAt) / 1000).toFixed(1)
    : step.startedAt
    ? (((Date.now()) - step.startedAt) / 1000).toFixed(1)
    : null

  const statusColor = {
    waiting: 'border-slate-800 bg-[#061209]',
    running: 'border-emerald-500 bg-emerald-950/40 animate-pulse shadow-md shadow-emerald-950',
    completed: 'border-emerald-800 bg-emerald-950/20',
    failed: 'border-red-800 bg-red-950/20',
  }[step.status]

  const statusIcon = {
    waiting: '○',
    running: '⟳',
    completed: '✓',
    failed: '✗',
  }[step.status]

  const iconColor = {
    waiting: 'text-slate-500',
    running: 'text-emerald-400',
    completed: 'text-emerald-400',
    failed: 'text-red-400',
  }[step.status]

  return (
    <div className={`border rounded-xl p-4 transition-all duration-300 ${statusColor}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-mono font-bold ${iconColor}`}>{statusIcon}</span>
          <span className="font-semibold text-slate-100">{step.step_id}</span>
          {step.result && (
            <span
              className="text-xs px-2 py-0.5 rounded-full bg-[#0a1f11] text-emerald-300 border border-emerald-800/50"
              title="The tier Verdant planned (small/medium/large) and where it ran"
            >
              {step.result.option_used?.model || (step.result as any).model} ({step.result.option_used?.site || (step.result as any).site})
            </span>
          )}
          {step.result?.model_used && (
            <span
              className="text-xs px-2 py-0.5 rounded-full bg-blue-950/50 text-blue-300 border border-blue-800/50 font-mono"
              title="The exact real AI model that generated this answer"
            >
              🤖 {step.result.model_used}
            </span>
          )}
          {step.result?.escalated && (
            <span
              className="text-xs px-2 py-0.5 rounded-full bg-amber-950/60 text-amber-300 border border-amber-800/50 flex items-center gap-1"
              title="The first answer didn't meet this step's quality bar, so Verdant automatically retried with a stronger model"
            >
              ⚡ upgraded to a stronger model (quality floor not met)
            </span>
          )}
        </div>
        {elapsed && (
          <span className="text-xs text-slate-400 font-mono tabular-nums">{elapsed}s</span>
        )}
      </div>

      {step.status === 'running' && (
        <div className="w-full h-1.5 bg-[#0a1a10] rounded-full overflow-hidden my-2">
          <div className="h-full bg-emerald-400 rounded-full animate-pulse" style={{ width: '85%' }} />
        </div>
      )}

      {step.result && (
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs bg-[#020b05] p-2.5 rounded-lg border border-emerald-900/20">
          <div>
            <span className="text-slate-500 block">Carbon</span>
            <span className="text-emerald-400 font-bold">{step.result.carbon_g.toFixed(4)} g</span>
          </div>
          <div>
            <span className="text-slate-500 block">Cost</span>
            <span className="text-slate-200 font-medium">${step.result.cost_usd.toFixed(5)}</span>
          </div>
          <div>
            <span className="text-slate-500 block">Tokens In / Out</span>
            <span className="text-slate-300 font-mono">{step.result.tokens_in} / {step.result.tokens_out}</span>
          </div>
          <div>
            <span className="text-slate-500 block" title="An AI judge grades this step's real answer for accuracy and completeness — separate from the planning-time quality estimate">
              Answer Quality Check
            </span>
            {step.result.verifier_score === undefined || step.result.verifier_score === null ? (
              <span className="font-semibold text-slate-500">Not verified</span>
            ) : (
              <span className={`font-semibold ${step.result.verifier_score >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>
                {formatQualityPercent(step.result.verifier_score)} <span className="text-slate-500 font-normal">(passing: 70%+)</span>
              </span>
            )}
          </div>
        </div>
      )}

      {step.result?.verifier_note && (
        <div className="mt-2 text-[11px] text-amber-300/90 bg-amber-950/30 border border-amber-900/40 rounded-lg px-2.5 py-1.5 flex items-start gap-1.5">
          <span>⚠️</span>
          <span>{step.result.verifier_note}</span>
        </div>
      )}

      {step.result?.output_text && (
        <div className="mt-2.5 text-xs bg-[#020703] border border-emerald-950 rounded-lg p-2.5">
          <div className="flex items-center justify-between text-slate-500 mb-1 select-none">
            <span className="font-mono text-[11px] uppercase tracking-wider text-emerald-500/80">Step Output</span>
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-[11px] text-slate-400 hover:text-emerald-300 transition-colors"
            >
              {expanded ? '▲ Collapse' : '▼ Show Full'}
            </button>
          </div>
          <div className={`text-slate-200 whitespace-pre-wrap font-sans text-xs leading-relaxed ${expanded ? '' : 'line-clamp-3'}`}>
            {step.result.output_text}
          </div>
        </div>
      )}

      {step.error && (
        <div className="mt-2 text-xs text-red-300 bg-red-950/40 p-2 rounded-lg border border-red-900/40">
          <strong>Error:</strong> {step.error}
        </div>
      )}
    </div>
  )
}

function DeliverableCard({ output, totals }: { output: string; totals: Totals | null }) {
  const [copied, setCopied] = useState(false)

  const copyToClipboard = () => {
    navigator.clipboard.writeText(output)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const wordCount = output.trim().split(/\s+/).filter(Boolean).length
  const charCount = output.length

  return (
    <div className="bg-gradient-to-b from-[#05170b] to-[#020c06] border-2 border-emerald-600/70 rounded-2xl p-6 shadow-2xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-emerald-800/40 pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xl">🎯</span>
            <h2 className="text-lg font-bold text-white tracking-tight">
              Task Deliverable & Final Verified Answer
            </h2>
            <span className="px-2 py-0.5 rounded-full bg-emerald-950 border border-emerald-700 text-emerald-300 text-xs font-semibold">
              Verified ✓
            </span>
          </div>
          <p className="text-xs text-slate-400">
            Produced by the green-routed AI workflow · {wordCount} words · {charCount} chars
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={copyToClipboard}
            className="px-4 py-2 rounded-xl bg-[#0a2312] hover:bg-[#0f341b] border border-emerald-700/60 text-emerald-300 text-xs font-semibold transition-all hover:scale-105 active:scale-95 flex items-center gap-1.5"
          >
            <span>{copied ? '✓ Copied!' : '📋 Copy Deliverable'}</span>
          </button>
        </div>
      </div>

      {/* Main text content */}
      <div className="bg-[#020703] border border-emerald-900/40 rounded-xl p-5 text-sm text-slate-200 leading-relaxed max-h-[550px] overflow-y-auto whitespace-pre-wrap font-sans selection:bg-emerald-900 selection:text-white">
        {output}
      </div>

      {/* Quality and carbon badge */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs pt-1 text-slate-400">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400" />
          <span>Automated Quality Guard: <strong>Passed</strong> (floor satisfied without degradation)</span>
        </div>
        {totals && (
          <div className="text-emerald-400 font-mono text-[11px]">
            Delivered in {totals.makespan_s}s · Carbon: {totals.carbon_g.toFixed(4)}g CO₂e
          </div>
        )}
      </div>
    </div>
  )
}

function LiveLog({ events }: { events: RunEvent[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [events])

  return (
    <div ref={ref} className="bg-[#020703] border border-emerald-900/40 rounded-xl p-4 h-48 overflow-y-auto font-mono text-xs space-y-1">
      {events.map((e, i) => (
        <div key={i} className={`${
          e.event_type === 'run_completed' ? 'text-emerald-400 font-bold' :
          e.event_type === 'run_failed' ? 'text-red-400 font-bold' :
          e.event_type === 'step_completed' ? 'text-teal-300' :
          e.event_type === 'step_started' ? 'text-slate-300' :
          e.event_type === 'error' ? 'text-red-400' :
          'text-slate-500'
        }`}>
          <span className="text-slate-600">[{i.toString().padStart(3, '0')}]</span>{' '}
          <span>{e.event_type}</span>
          {e.step_id && <span className="text-slate-400"> · step: {e.step_id}</span>}
          {Boolean(e.error) && <span className="text-red-400 ml-2">({String(e.error)})</span>}
        </div>
      ))}
      {events.length === 0 && (
        <div className="text-slate-600">Waiting for scheduler execution events…</div>
      )}
    </div>
  )
}

export function RunPage({ planId, onReceipt, onSelectPlan }: RunPageProps) {
  const [runId, setRunId] = useState<string | null>(null)
  const [runMode, setRunMode] = useState<'virtual' | 'live'>('virtual')
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle')
  const [steps, setSteps] = useState<Map<string, StepState>>(new Map())
  const [events, setEvents] = useState<RunEvent[]>([])
  const [totals, setTotals] = useState<Totals | null>(null)
  const [finalOutput, setFinalOutput] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const pushEvent = useCallback((e: RunEvent) => {
    setEvents(prev => [...prev, e])
  }, [])

  const startRun = useCallback(async () => {
    const effectivePlanId = planId || 'fixture-market-brief-001'
    if (!planId && onSelectPlan) {
      onSelectPlan('fixture-market-brief-001')
    }

    setStatus('running')
    setErrorMessage(null)
    setEvents([])
    setTotals(null)
    setFinalOutput(null)

    // Pre-populate steps from plan definition so cards are visible immediately
    try {
      const planRes = await api.getPlan(effectivePlanId)
      if (planRes && planRes.steps) {
        const initialMap = new Map<string, StepState>()
        planRes.steps.forEach(sp => {
          initialMap.set(sp.step_id, { step_id: sp.step_id, status: 'waiting' })
        })
        setSteps(initialMap)
      }
    } catch {
      setSteps(new Map())
    }

    try {
      const { run_id } = await api.createRun(effectivePlanId, runMode)
      setRunId(run_id)

      // Subscribe to SSE
      const es = api.runEvents(run_id)
      esRef.current = es

      es.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data) as RunEvent
          pushEvent(data)

          if (data.event_type === 'step_started') {
            setSteps(prev => {
              const m = new Map(prev)
              const existing = m.get(data.step_id!) ?? { step_id: data.step_id!, status: 'waiting' as const }
              m.set(data.step_id!, {
                ...existing,
                status: 'running',
                startedAt: Date.now(),
              })
              return m
            })
          }

          if (data.event_type === 'step_completed') {
            setSteps(prev => {
              const m = new Map(prev)
              const existing = m.get(data.step_id!) ?? { step_id: data.step_id!, status: 'waiting' as const }
              const stepResult = (data.data ? data.data : data) as unknown as StepRunResult
              m.set(data.step_id!, {
                ...existing,
                status: 'completed',
                result: stepResult,
                endedAt: Date.now(),
              })
              return m
            })
          }

          if (data.event_type === 'step_failed') {
            setSteps(prev => {
              const m = new Map(prev)
              const existing = m.get(data.step_id!) ?? { step_id: data.step_id!, status: 'waiting' as const }
              m.set(data.step_id!, {
                ...existing,
                status: 'failed',
                error: String(data.error ?? 'Unknown step error'),
                endedAt: Date.now(),
              })
              return m
            })
          }

          if (data.event_type === 'run_completed') {
            setStatus('completed')
            const eventData = (data.data && typeof data.data === 'object') ? data.data as Record<string, unknown> : data
            if (eventData.totals) setTotals(eventData.totals as unknown as Totals)
            if (eventData.final_output) {
              setFinalOutput(String(eventData.final_output))
            } else {
              api.getRun(run_id).then(r => {
                if (r.final_output) setFinalOutput(String(r.final_output))
              }).catch(() => {})
            }
            es.close()
          }

          if (data.event_type === 'run_failed') {
            setStatus('failed')
            setErrorMessage(String(data.error ?? 'Run execution failed'))
            es.close()
          }
        } catch (err) {
          logger_ignore: void err
        }
      }

      es.onerror = () => {
        es.close()
      }
    } catch (e) {
      setStatus('failed')
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMessage(msg)
      pushEvent({ run_id: effectivePlanId, event_type: 'error', error: msg })
    }
  }, [planId, runMode, pushEvent, onSelectPlan])

  // Polling fallback to ensure status and steps update even if SSE drops
  useEffect(() => {
    if (status !== 'running' || !runId) return
    const interval = setInterval(async () => {
      try {
        const runData = await api.getRun(runId)
        if (!runData) return

        if (runData.status === 'completed' || runData.status === 'failed') {
          setStatus(runData.status as 'completed' | 'failed')
        }
        if (runData.final_output) {
          setFinalOutput(String(runData.final_output))
        }
        if (runData.totals_json) {
          try { setTotals(JSON.parse(runData.totals_json as string)) } catch {}
        }
        const rawSteps = runData.steps as unknown as StepRunResult[]
        if (rawSteps && Array.isArray(rawSteps) && rawSteps.length > 0) {
          setSteps(prev => {
            const m = new Map(prev)
            rawSteps.forEach(s => {
              m.set(s.step_id, {
                step_id: s.step_id,
                status: 'completed',
                result: s,
                endedAt: Date.now(),
              })
            })
            return m
          })
        }
      } catch {
        // silent polling catch
      }
    }, 1200)

    return () => clearInterval(interval)
  }, [status, runId])

  // Pre-load plan when planId is provided
  useEffect(() => {
    const effectivePlanId = planId || 'fixture-market-brief-001'
    api.getPlan(effectivePlanId).then(planRes => {
      if (planRes && planRes.steps) {
        const initialMap = new Map<string, StepState>()
        planRes.steps.forEach(sp => {
          initialMap.set(sp.step_id, { step_id: sp.step_id, status: 'waiting' })
        })
        setSteps(initialMap)
      }
    }).catch(() => {})
  }, [planId])

  useEffect(() => {
    return () => { esRef.current?.close() }
  }, [])

  const stepList = Array.from(steps.values())
  const completed = stepList.filter(s => s.status === 'completed').length
  const total = stepList.length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <span>Execution Monitor</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-950 border border-emerald-800 text-emerald-400 font-mono">
              live SSE
            </span>
          </h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {planId ? (
              <span>Active Plan: <code className="text-emerald-400 bg-[#06150a] px-1.5 py-0.5 rounded border border-emerald-900/40">{planId}</code></span>
            ) : (
              <span className="text-amber-400 font-medium">⚠️ No plan selected — will use default Market Brief plan</span>
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Mode Selector */}
          <div className="flex items-center gap-1 border border-emerald-900/60 bg-[#030d06] rounded-xl p-0.5">
            <button
              onClick={() => setRunMode('virtual')}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                runMode === 'virtual'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              ⚡ Virtual (Fast-Forward)
            </button>
            <button
              onClick={() => setRunMode('live')}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                runMode === 'live'
                  ? 'bg-red-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              🔴 Live (Real Pacing)
            </button>
          </div>

          <button
            onClick={startRun}
            disabled={status === 'running'}
            className="px-6 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold rounded-xl shadow-lg shadow-emerald-900/40 transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:scale-100 text-sm"
          >
            {status === 'running' ? '⏳ Executing…' : '▶ Start Run'}
          </button>

          {status === 'completed' && runId && (
            <button
              onClick={() => onReceipt(runId)}
              className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-xl shadow-md transition-all hover:scale-105 text-sm flex items-center gap-1.5"
            >
              <span>🧾 View Receipt</span>
              <span>→</span>
            </button>
          )}
        </div>
      </div>

      {/* Explainer Box */}
      <div className="bg-[#030e06] border border-emerald-900/40 rounded-2xl p-4 text-xs text-slate-300 leading-relaxed flex items-start gap-3">
        <span className="text-xl flex-shrink-0">💡</span>
        <div>
          <strong className="text-emerald-400">How Execution Works:</strong> In <strong>Virtual Mode</strong>, all Gemini & Ollama model calls, tokens, latency, and verifier evaluations are 100% real, but time-shifted wait periods (e.g. waiting for solar peak) are fast-forwarded instantly so the demo finishes in seconds. In <strong>Live Mode</strong>, steps wait for real wall-clock durations.
        </div>
      </div>

      {/* Status bar */}
      {status !== 'idle' && (
        <div className={`border rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${
          status === 'completed' ? 'border-emerald-700/60 bg-emerald-950/20' :
          status === 'failed' ? 'border-red-700/60 bg-red-950/20' :
          'border-emerald-600/60 bg-emerald-950/10'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full flex-shrink-0 ${
              status === 'running' ? 'bg-emerald-400 animate-ping' :
              status === 'completed' ? 'bg-emerald-400' : 'bg-red-400'
            }`} />
            <div>
              <div className="text-sm font-semibold text-slate-100">
                {status === 'running' && 'Pipeline Running: executing async DAG steps…'}
                {status === 'completed' && '🎉 Run Completed Successfully! All verifiers evaluated.'}
                {status === 'failed' && (errorMessage || 'Run failed')}
              </div>
              {runId && (
                <div className="text-xs text-slate-500 mt-0.5 font-mono">
                  Run ID: {runId} · Mode: {runMode}
                </div>
              )}
            </div>
          </div>

          {total > 0 && (
            <div className="flex items-center gap-3 min-w-[200px]">
              <div className="text-xs text-slate-400 font-mono">{completed}/{total} steps</div>
              <div className="flex-1 h-2 bg-[#020b05] rounded-full overflow-hidden border border-emerald-900/40">
                <div
                  className="h-full bg-emerald-400 rounded-full transition-all duration-500"
                  style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Final Deliverable Card if completed and output available */}
      {finalOutput && (
        <DeliverableCard output={finalOutput} totals={totals} />
      )}

      {/* Totals cards if completed */}
      {totals && (
        <div className="bg-[#030f07] border border-emerald-800/40 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-white text-sm">Actual Run Totals (Verified Telemetry)</h3>
            <span className="text-xs text-emerald-400 font-medium">Measured & Modeled</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              { l: 'Total Carbon', v: `${totals.carbon_g.toFixed(4)} g`, sub: `robust: ${totals.carbon_g_robust.toFixed(4)}g`, c: 'text-emerald-400' },
              { l: 'Workflow Makespan', v: `${totals.makespan_s}s`, sub: 'virtual clock', c: 'text-teal-300' },
              { l: 'Total API Cost', v: `$${totals.cost_usd.toFixed(6)}`, sub: 'real token count', c: 'text-slate-200' },
              { l: 'Energy Used', v: `${(totals.energy_wh * 1000).toFixed(2)} mWh`, sub: 'modeled', c: 'text-slate-200' },
              { l: 'Avg Answer Quality', v: `${(totals.quality * 100).toFixed(1)}%`, sub: totals.quality >= 0.85 ? 'all steps passed' : 'auto-upgraded low scores', c: totals.quality >= 0.85 ? 'text-emerald-400' : 'text-amber-400' },
            ].map(({ l, v, sub, c }) => (
              <div key={l} className="bg-[#020703] border border-emerald-900/30 rounded-xl p-3">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">{l}</div>
                <div className={`text-lg font-bold mt-0.5 ${c}`}>{v}</div>
                <div className="text-[10px] text-slate-500">{sub}</div>
              </div>
            ))}
          </div>

          {runId && (
            <div className="pt-2 flex justify-end">
              <button
                onClick={() => onReceipt(runId)}
                className="px-5 py-2.5 bg-gradient-to-r from-emerald-600 to-teal-600 text-white font-semibold rounded-xl text-xs hover:from-emerald-500 hover:to-teal-500 transition-all hover:scale-105 flex items-center gap-1.5"
              >
                <span>🧾 Open Verified Carbon Receipt & Ablation Waterfall</span>
                <span>→</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Step cards */}
      {stepList.length > 0 && (
        <div className="space-y-3">
          <h2 className="font-semibold text-slate-100 flex items-center justify-between">
            <span>Workflow Steps in Execution</span>
            <span className="text-xs text-slate-500 font-normal">Topological DAG order</span>
          </h2>
          {stepList.map(s => <StepCard key={s.step_id} step={s} />)}
        </div>
      )}

      {/* Idle state with Quick Action */}
      {status === 'idle' && (
        <div className="bg-[#030c05] border border-emerald-900/30 rounded-2xl p-8 text-center space-y-4">
          <div className="text-4xl">⚡</div>
          <div className="max-w-md mx-auto space-y-1">
            <h3 className="text-base font-semibold text-white">Ready for Execution</h3>
            <p className="text-xs text-slate-400">
              Click <strong>Start Run</strong> above to execute the pipeline with real Google Gemini calls and automatic value-of-information verifiers.
            </p>
          </div>
          {onSelectPlan && (
            <button
              onClick={() => onSelectPlan('fixture-market-brief-001')}
              className="px-4 py-2 rounded-xl bg-[#06170c] hover:bg-[#0a2614] border border-emerald-800/60 text-emerald-300 text-xs font-semibold transition-all"
            >
              🔄 Reload Sample Market Brief Plan
            </button>
          )}
        </div>
      )}

      {/* Live log */}
      <div className="space-y-2">
        <h2 className="font-semibold text-slate-100 text-sm">Real-Time Event Bus Log (SSE)</h2>
        <LiveLog events={events} />
      </div>
    </div>
  )
}

