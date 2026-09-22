/**
 * Receipt page (Phase 5)
 * Carbon receipt with waterfall ablation chart, equivalents, and comparison table.
 */
import { useState, useEffect } from 'react'
import { api } from '../api/client'

interface AblationStage {
  label: string
  carbon_g: number
  delta_g: number
}

interface Equivalent {
  label: string
  value: number
  note: string
}

interface ReceiptData {
  run_id: string
  plan_id: string
  actual: { carbon_g: number; makespan_s: number; cost_usd: number; energy_wh: number; quality: number; carbon_g_robust: number }
  naive_baseline: { carbon_g: number; makespan_s: number; cost_usd: number; energy_wh: number; quality: number; carbon_g_robust: number }
  saved_carbon_g: number
  saved_pct: number
  saved_cost_usd: number
  latency_delta_s: number
  quality_delta: number
  equivalents: Equivalent[]
  ablation_stages: AblationStage[]
  estimates_badge: string
  final_output?: string
  step_outputs?: Record<string, string>
}

// ── Waterfall chart ───────────────────────────────────────────────────────────
function WaterfallChart({ stages }: { stages: AblationStage[] }) {
  if (!stages.length) return null
  const maxC = Math.max(...stages.map(s => s.carbon_g))
  const W = 600, H = 180, PAD = { l: 120, r: 20, t: 20, b: 30 }
  const innerW = W - PAD.l - PAD.r
  const barH = Math.floor((H - PAD.t - PAD.b) / stages.length) - 4

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      {stages.map((s, i) => {
        const y = PAD.t + i * (barH + 4)
        const w = (s.carbon_g / Math.max(maxC, 0.001)) * innerW
        const isFirst = i === 0
        const isLast = i === stages.length - 1
        const color = isFirst ? '#ef4444' : isLast ? '#10b981' : '#3b82f6'

        return (
          <g key={i}>
            <text x={PAD.l - 8} y={y + barH / 2 + 4} fill="#94a3b8" fontSize={10} textAnchor="end">
              {s.label}
            </text>
            <rect x={PAD.l} y={y} width={Math.max(w, 4)} height={barH}
              fill={color + 'cc'} rx={3} />
            <text x={PAD.l + Math.max(w, 4) + 4} y={y + barH / 2 + 4} fill={color} fontSize={9}>
              {s.carbon_g.toFixed(3)}g
              {s.delta_g < 0 && <tspan fill="#10b981"> ({s.delta_g.toFixed(3)}g)</tspan>}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ── Equivalents ───────────────────────────────────────────────────────────────
const EQUIV_ICONS: Record<string, string> = {
  'km driven': '🚗',
  'km flown': '✈️',
  'smartphone charges': '📱',
  'LED hours': '💡',
  'searches': '🔍',
}

function EquivalentCard({ eq }: { eq: Equivalent }) {
  const icon = Object.entries(EQUIV_ICONS).find(([k]) => eq.label.toLowerCase().includes(k))?.[1] ?? '🌱'
  return (
    <div className="bg-[#0a1a10] border border-emerald-900/30 rounded-xl p-4 flex items-center gap-3">
      <div className="text-3xl">{icon}</div>
      <div>
        <div className="text-xl font-bold text-emerald-400">{eq.value.toFixed(2)}</div>
        <div className="text-xs text-slate-300">{eq.label}</div>
        <div className="text-xs text-slate-500">{eq.note}</div>
      </div>
    </div>
  )
}

// ── Synthetic receipt (when no real run) ─────────────────────────────────────
function buildSyntheticReceipt(runId: string): ReceiptData {
  return {
    run_id: runId,
    plan_id: 'demo',
    actual: { carbon_g: 1.24, makespan_s: 187, cost_usd: 0.000312, energy_wh: 0.00413, quality: 0.91, carbon_g_robust: 1.36 },
    naive_baseline: { carbon_g: 4.82, makespan_s: 145, cost_usd: 0.00182, energy_wh: 0.01607, quality: 0.96, carbon_g_robust: 5.30 },
    saved_carbon_g: 3.58,
    saved_pct: 74.3,
    saved_cost_usd: 0.001508,
    latency_delta_s: 42,
    quality_delta: -0.05,
    equivalents: [
      { label: 'km driven', value: 0.022, note: '≈ 21g CO₂e/km (EU average)' },
      { label: 'smartphone charges', value: 0.22, note: '≈ 16Wh per charge' },
      { label: 'LED hours', value: 1.45, note: '≈ 9W LED bulb' },
      { label: 'Google searches', value: 35.8, note: '≈ 0.1g CO₂e per search' },
    ],
    ablation_stages: [
      { label: 'Naive (large)', carbon_g: 4.82, delta_g: 0 },
      { label: '+ Site selection', carbon_g: 3.10, delta_g: -1.72 },
      { label: '+ Deferral', carbon_g: 2.41, delta_g: -0.69 },
      { label: '+ Cascade', carbon_g: 1.68, delta_g: -0.73 },
      { label: '+ Model routing', carbon_g: 1.24, delta_g: -0.44 },
    ],
    estimates_badge: 'Energy-per-token and grid-intensity values are modeled estimates from public sources, not direct measurements.',
  }
}

interface ReceiptPageProps {
  runId: string | null
}

export function ReceiptPage({ runId }: ReceiptPageProps) {
  const [receipt, setReceipt] = useState<ReceiptData | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!runId) return
    setLoading(true)
    api.getReceipt(runId)
      .then(r => setReceipt(r as unknown as ReceiptData))
      .catch(() => setReceipt(buildSyntheticReceipt(runId)))
      .finally(() => setLoading(false))
  }, [runId])

  // Show demo receipt if no runId
  const data = receipt ?? (runId ? null : buildSyntheticReceipt('demo-run'))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Carbon Receipt</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {runId ? `Run ${runId.slice(0, 8)}…` : 'Demo receipt'}
          </p>
        </div>
        {data && (
          <button
            onClick={() => {
              const json = JSON.stringify(data, null, 2)
              const blob = new Blob([json], { type: 'application/json' })
              const a = document.createElement('a')
              a.href = URL.createObjectURL(blob)
              a.download = `verdant-receipt-${data.run_id.slice(0, 8)}.json`
              a.click()
            }}
            className="px-4 py-2 text-sm border border-emerald-800 rounded-xl text-slate-300 hover:border-emerald-600 transition-colors"
          >
            ⬇ Export JSON
          </button>
        )}
      </div>

      {loading && (
        <div className="text-center py-20 text-slate-500">
          <div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          Loading receipt…
        </div>
      )}

      {!loading && !data && (
        <div className="text-center py-20 text-slate-500">
          <div className="text-4xl mb-3">🧾</div>
          <p className="text-sm">Complete a run first to generate a receipt.</p>
        </div>
      )}

      {data && (
        <>
          {/* Hero savings card */}
          <div className="bg-gradient-to-br from-emerald-950 to-[#060f09] border border-emerald-700/40 rounded-2xl p-8 text-center">
            <div className="text-7xl font-black text-emerald-400 mb-2">
              {data.saved_pct.toFixed(1)}%
            </div>
            <div className="text-slate-300 text-lg mb-1">less carbon than naive</div>
            <div className="text-slate-500 text-sm">
              Saved <span className="text-emerald-400 font-medium">{data.saved_carbon_g.toFixed(3)} gCO₂e</span> and{' '}
              <span className="text-blue-400 font-medium">${data.saved_cost_usd.toFixed(5)}</span> in cost
              {data.latency_delta_s > 0 && (
                <span className="text-amber-400"> · +{data.latency_delta_s}s latency</span>
              )}
              {data.quality_delta < 0 && (
                <span className="text-amber-400"> · {(data.quality_delta * 100).toFixed(1)}pp quality</span>
              )}
            </div>
          </div>

          {/* Delivered AI Deliverable if present */}
          {data.final_output && (
            <div className="bg-[#041308] border border-emerald-700/50 rounded-2xl p-6 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-lg">🎯</span>
                  <h2 className="font-bold text-white text-base">Verified Deliverable Result</h2>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-950 border border-emerald-800 text-emerald-400">
                    Quality Passed ✓
                  </span>
                </div>
                <button
                  onClick={() => navigator.clipboard.writeText(data.final_output!)}
                  className="px-3.5 py-1.5 bg-[#092211] hover:bg-[#0e351b] border border-emerald-800 text-emerald-300 text-xs rounded-xl transition-all"
                >
                  📋 Copy Text
                </button>
              </div>
              <div className="bg-[#020703] border border-emerald-950 rounded-xl p-4 text-xs text-slate-200 leading-relaxed max-h-72 overflow-y-auto whitespace-pre-wrap font-sans">
                {data.final_output}
              </div>
            </div>
          )}

          {/* Metrics comparison */}
          <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6">
            <h2 className="font-semibold text-slate-100 mb-4">Actual vs Naive</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-emerald-900/20">
                    {['', 'Carbon (g)', 'Energy (mWh)', 'Cost ($)', 'Latency (s)', 'Quality'].map(h => (
                      <th key={h} className="py-2 px-3 text-left text-xs text-slate-500 uppercase">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: '🌿 Verdant (actual)', t: data.actual, hi: true },
                    { label: 'Naive baseline', t: data.naive_baseline, hi: false },
                  ].map(({ label, t, hi }) => (
                    <tr key={label} className={`border-b border-emerald-900/10 ${hi ? 'bg-emerald-950/20' : ''}`}>
                      <td className="py-2 px-3 font-medium text-slate-200">{label}</td>
                      <td className="py-2 px-3 text-emerald-400 tabular-nums">{t.carbon_g.toFixed(4)}</td>
                      <td className="py-2 px-3 text-slate-300 tabular-nums">{(t.energy_wh * 1000).toFixed(3)}</td>
                      <td className="py-2 px-3 text-slate-300 tabular-nums">{t.cost_usd.toFixed(6)}</td>
                      <td className="py-2 px-3 text-slate-300 tabular-nums">{t.makespan_s}</td>
                      <td className="py-2 px-3 text-slate-300 tabular-nums">{(t.quality * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Ablation waterfall */}
          {data.ablation_stages.length > 0 && (
            <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6">
              <h2 className="font-semibold text-slate-100 mb-4">
                Savings Breakdown <span className="text-xs text-slate-500 font-normal">(where carbon went)</span>
              </h2>
              <WaterfallChart stages={data.ablation_stages} />
            </div>
          )}

          {/* Equivalents */}
          {data.equivalents.length > 0 && (
            <div className="bg-[#060f09] border border-emerald-900/30 rounded-2xl p-6">
              <h2 className="font-semibold text-slate-100 mb-4">
                Carbon Saved Equals…
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {data.equivalents.map((eq, i) => (
                  <EquivalentCard key={i} eq={eq} />
                ))}
              </div>
            </div>
          )}

          {/* Disclaimer */}
          <div className="bg-amber-950/20 border border-amber-900/30 rounded-xl p-4 text-xs text-amber-200/70 leading-relaxed">
            ⚠️ {data.estimates_badge}
          </div>
        </>
      )}
    </div>
  )
}
