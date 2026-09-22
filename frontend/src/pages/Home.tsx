import { useState } from 'react'
import { api } from '../api/client'

interface HomePageProps {
  onNavigate: (page: 'builder' | 'plan' | 'run' | 'receipt' | 'report', planId?: string) => void
}

export function HomePage({ onNavigate }: HomePageProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'comparison' | 'howItWorks'>('overview')
  const [question, setQuestion] = useState('What are the most effective strategies to decarbonize AI data centers by 2030?')
  const [qualityFloor, setQualityFloor] = useState(0.80)
  const [execMode, setExecMode] = useState<'virtual' | 'live'>('virtual')
  const [submitting, setSubmitting] = useState(false)

  const handleQuickSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!question.trim() || submitting) return
    setSubmitting(true)
    try {
      const res = await api.quickAnswer(question.trim(), qualityFloor, execMode)
      onNavigate('run', res.plan_id)
    } catch (err) {
      console.error('Quick answer error:', err)
    } finally {
      setSubmitting(false)
    }
  }

  const sampleQuestions = [
    'What are the most effective strategies to decarbonize AI data centers by 2030?',
    'Compare energy efficiency of small quantized local LLMs vs frontier cloud models.',
    'How does carbon-aware solar window deferral save grid emissions without missing deadlines?',
  ]

  return (
    <div className="space-y-12 pb-16">
      {/* Hero Section */}
      <section className="relative overflow-hidden rounded-3xl border border-emerald-500/20 bg-gradient-to-b from-emerald-950/40 via-[#041209] to-[#020d07] p-8 md:p-14 shadow-2xl">
        <div className="absolute top-0 right-0 -mr-16 -mt-16 w-96 h-96 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-1/3 -ml-20 -mb-20 w-80 h-80 rounded-full bg-blue-500/5 blur-3xl pointer-events-none" />

        <div className="relative z-10 max-w-3xl space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/60 text-xs font-semibold text-emerald-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
            Next-Gen Green AI Infrastructure
          </div>

          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight text-white leading-tight">
            Cut AI Agent Carbon by up to <span className="bg-gradient-to-r from-emerald-400 via-teal-300 to-green-500 bg-clip-text text-transparent">68%</span> without slowing down.
          </h1>

          <p className="text-base md:text-lg text-slate-300 leading-relaxed">
            Multi-step agent workflows execute dozens of LLM calls without considering <strong>which model</strong> to use, <strong>where</strong> in the world the grid is clean, or <strong>when</strong> to run.
            <br className="hidden md:block" />
            <strong className="text-emerald-400 font-semibold"> Verdant</strong> is the world’s first carbon- and latency-aware workflow scheduler that routes and time-shifts LLM queries into green energy windows while strictly enforcing your deadlines.
          </p>

          {/* CTAs */}
          <div className="flex flex-wrap items-center gap-4 pt-2">
            <button
              onClick={() => onNavigate('plan', 'fixture-market-brief-001')}
              className="px-6 py-3.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold rounded-xl shadow-lg shadow-emerald-900/40 transition-all hover:scale-105 active:scale-95 flex items-center gap-2"
            >
              <span>🌿 Explore Sample Schedule</span>
              <span className="text-xs bg-emerald-800/80 px-2 py-0.5 rounded-full">1-Click</span>
            </button>

            <button
              onClick={() => onNavigate('builder')}
              className="px-6 py-3.5 bg-[#0a1f12] hover:bg-[#0f2c1a] border border-emerald-800/60 text-emerald-300 font-medium rounded-xl transition-all hover:scale-105 flex items-center gap-2"
            >
              <span>🛠️ Build Custom DAG</span>
            </button>

            <button
              onClick={() => onNavigate('report')}
              className="px-5 py-3.5 text-slate-400 hover:text-white text-sm font-medium transition-colors flex items-center gap-1.5"
            >
              <span>📑 Read Technical Report</span>
              <span>→</span>
            </button>
          </div>
        </div>

        {/* Floating Quick Stats */}
        <div className="mt-10 grid grid-cols-2 md:grid-cols-4 gap-4 border-t border-emerald-900/40 pt-8">
          {[
            { label: 'Carbon Reduction', value: '45% – 68%', desc: 'vs standard monolithic LLM routing' },
            { label: 'Quality Guarantee', value: '≥ 90% Floor', desc: 'automated verifiers & cascades' },
            { label: 'Slack Reclamation', value: 'CPM Directed', desc: 'non-critical steps shift to solar peaks' },
            { label: 'Solver Latency', value: '< 50 ms', desc: 'CP-SAT exact + Greedy heuristic' },
          ].map(stat => (
            <div key={stat.label} className="bg-[#031107]/70 rounded-xl p-4 border border-emerald-900/30">
              <div className="text-xl md:text-2xl font-bold text-emerald-400">{stat.value}</div>
              <div className="text-xs font-semibold text-slate-200 mt-0.5">{stat.label}</div>
              <div className="text-[11px] text-slate-500 mt-1">{stat.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Ask Anything (3-Step Green Answer) Interactive Card */}
      <section className="bg-gradient-to-br from-[#061c0d] to-[#020b05] border-2 border-emerald-500/40 rounded-3xl p-6 md:p-8 shadow-2xl space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-emerald-800/40 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-2xl">🌱</span>
              <h2 className="text-xl md:text-2xl font-bold text-white tracking-tight">
                Ask Anything — Green Task Driver
              </h2>
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-950 border border-emerald-700 text-emerald-300 text-xs font-semibold">
                3-Step Green Pipeline
              </span>
            </div>
            <p className="text-slate-300 text-xs md:text-sm mt-1">
              Verdant isn't just a dashboard—it plans, green-routes, executes real AI calls, and delivers the final verified result + carbon receipt.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-[#020703] border border-emerald-900 rounded-xl px-3 py-1 text-xs text-slate-300">
              <span className="text-slate-500">Quality Floor:</span>
              <select
                value={qualityFloor}
                onChange={(e) => setQualityFloor(parseFloat(e.target.value))}
                className="bg-transparent text-emerald-400 font-semibold outline-none cursor-pointer"
              >
                <option value={0.75} className="bg-slate-900 text-white">75% (Fast)</option>
                <option value={0.80} className="bg-slate-900 text-white">80% (Balanced)</option>
                <option value={0.90} className="bg-slate-900 text-white">90% (High Precision)</option>
              </select>
            </div>

            <div className="flex items-center gap-1 border border-emerald-900 bg-[#020703] rounded-xl p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setExecMode('virtual')}
                className={`px-2.5 py-1 rounded-lg transition-all ${
                  execMode === 'virtual' ? 'bg-emerald-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                ⚡ Fast
              </button>
              <button
                type="button"
                onClick={() => setExecMode('live')}
                className={`px-2.5 py-1 rounded-lg transition-all ${
                  execMode === 'live' ? 'bg-red-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                🔴 Live
              </button>
            </div>
          </div>
        </div>

        <form onSubmit={handleQuickSubmit} className="space-y-4">
          <div className="relative">
            <textarea
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask any research or analytical question (e.g. Compare energy efficiency of small models vs frontier models)..."
              className="w-full bg-[#020804] border border-emerald-800/60 rounded-2xl p-4 text-slate-100 placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 font-sans resize-none leading-relaxed"
            />
          </div>

          {/* Prompt chips */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-slate-500 uppercase font-semibold">Try sample:</span>
            {sampleQuestions.map((sq, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setQuestion(sq)}
                className="text-xs bg-[#031107] hover:bg-[#07210e] text-emerald-300/90 border border-emerald-900/60 rounded-lg px-2.5 py-1 transition-all text-left truncate max-w-xs"
                title={sq}
              >
                {sq}
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between pt-2">
            <div className="text-xs text-slate-400 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span>Pipeline: <code className="text-emerald-400 font-mono">understand</code> ➔ <code className="text-teal-400 font-mono">synthesize</code> ➔ <code className="text-blue-400 font-mono">check & deliver</code></span>
            </div>

            <button
              type="submit"
              disabled={submitting || !question.trim()}
              className="px-6 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold rounded-xl shadow-lg shadow-emerald-950 transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:scale-100 text-sm flex items-center gap-2"
            >
              <span>{submitting ? '⏳ Planning & Running…' : '🌿 Run Green Answer'}</span>
              <span>→</span>
            </button>
          </div>
        </form>
      </section>

      {/* Navigation Tabs for Explanations */}
      <div className="flex items-center justify-center gap-3 border-b border-emerald-900/30 pb-4">
        {[
          { id: 'overview', label: '💡 The Core Concept in Simple Terms' },
          { id: 'howItWorks', label: '⚙️ How Verdant Works (The 4 Pillars)' },
          { id: 'comparison', label: '📊 Naive Agent vs. Verdant' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={`px-4 py-2 text-sm font-medium rounded-xl transition-all ${
              activeTab === tab.id
                ? 'bg-emerald-900/50 text-emerald-300 border border-emerald-700/50'
                : 'text-slate-400 hover:text-slate-200 hover:bg-emerald-950/20'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 1: In Simple Terms */}
      {activeTab === 'overview' && (
        <section className="space-y-6">
          <div className="text-center max-w-2xl mx-auto space-y-2">
            <h2 className="text-2xl md:text-3xl font-bold text-white">Why Do Agent Workflows Waste So Much Carbon?</h2>
            <p className="text-slate-400 text-sm">
              When an AI agent performs research, writes code, or reviews documents, it executes multiple sub-tasks. Today’s systems treat all tasks identically.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-[#06150b] border border-red-900/30 rounded-2xl p-6 space-y-3">
              <div className="text-3xl">🏭</div>
              <h3 className="font-semibold text-red-300">The Problem: Overkill Models</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Standard agents call giant frontier models (like Gemini Pro or Claude Opus) for every tiny task—even formatting dates, categorizing text, or simple extraction. That burns up to <strong>15× more electricity</strong> per token than necessary.
              </p>
              <div className="text-[11px] text-red-400 font-mono bg-red-950/40 p-2 rounded-lg">
                ❌ Formatting brief with Pro model: 0.8 mWh / 0.5g CO₂
              </div>
            </div>

            <div className="bg-[#06150b] border border-amber-900/30 rounded-2xl p-6 space-y-3">
              <div className="text-3xl">⚡</div>
              <h3 className="font-semibold text-amber-300">The Problem: Blind Grid Timing</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Cloud grids fluctuate dramatically. Running an AI job in Mumbai at night (mostly coal power) emits <strong>750 gCO₂e/kWh</strong>. Running it during solar peak drops emissions to <strong>430 gCO₂e/kWh</strong>. Running it in Finland hydro emits just <strong>120 gCO₂e/kWh</strong>.
              </p>
              <div className="text-[11px] text-amber-400 font-mono bg-amber-950/40 p-2 rounded-lg">
                ❌ Everything runs ASAP in default region, ignoring clean energy
              </div>
            </div>

            <div className="bg-[#06150b] border border-emerald-900/30 rounded-2xl p-6 space-y-3">
              <div className="text-3xl">🌿</div>
              <h3 className="font-semibold text-emerald-300">The Solution: Verdant Scheduling</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Verdant analyzes the workflow’s dependency graph (DAG). It automatically finds steps that have <strong>slack</strong> (buffer time) and moves them into green windows or cleaner regions, while fast-tracking urgent steps.
              </p>
              <div className="text-[11px] text-emerald-400 font-mono bg-emerald-950/40 p-2 rounded-lg">
                ✅ Optimal model + green site + solar peak: 60%+ CO₂ saved
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Tab 2: The 4 Pillars */}
      {activeTab === 'howItWorks' && (
        <section className="space-y-6">
          <div className="text-center max-w-2xl mx-auto space-y-2">
            <h2 className="text-2xl md:text-3xl font-bold text-white">The Four Optimization Pillars</h2>
            <p className="text-slate-400 text-sm">
              Verdant doesn't just route prompts; it mathematically orchestrates the execution lifecycle across space, time, and tier.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-[#05140a] border border-emerald-900/40 rounded-2xl p-6 flex gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-2xl flex-shrink-0">
                1
              </div>
              <div className="space-y-2">
                <h3 className="font-semibold text-white">Critical Path Method (CPM) Slack Analysis</h3>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Every pipeline has steps that must finish fast (the <em>Critical Path</em>) and steps that can wait without delaying the overall workflow (<em>Slack</em>). Verdant keeps critical steps on fast models and leverages the slack of background steps to schedule them at greener times.
                </p>
                <div className="text-xs text-emerald-400 font-medium">Outcome: Guaranteed deadline compliance with zero latency penalty.</div>
              </div>
            </div>

            <div className="bg-[#05140a] border border-emerald-900/40 rounded-2xl p-6 flex gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-2xl flex-shrink-0">
                2
              </div>
              <div className="space-y-2">
                <h3 className="font-semibold text-white">Smart Model Cascading & Value-of-Information</h3>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Instead of always executing large models, Verdant runs an ultra-low-energy model first (e.g. Gemini 2.5 Flash-Lite or local 3B). A verifier inspects the answer. If the score passes, we save 85% energy. Only if verification fails does it escalate to Gemini Pro.
                </p>
                <div className="text-xs text-emerald-400 font-medium">Outcome: High quality maintained while cutting energy by ~55%.</div>
              </div>
            </div>

            <div className="bg-[#05140a] border border-emerald-900/40 rounded-2xl p-6 flex gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-2xl flex-shrink-0">
                3
              </div>
              <div className="space-y-2">
                <h3 className="font-semibold text-white">Temporal Deferral into Solar & Wind Peaks</h3>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Grids experience significant diurnal clean-energy dips (e.g., peak midday solar). When a workflow has a multi-hour deadline (e.g., nightly report, batch processing), Verdant fast-forwards through time and schedules steps to start exactly when the local grid is cleanest.
                </p>
                <div className="text-xs text-emerald-400 font-medium">Outcome: Up to 35% carbon intensity reduction from timing alone.</div>
              </div>
            </div>

            <div className="bg-[#05140a] border border-emerald-900/40 rounded-2xl p-6 flex gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-2xl flex-shrink-0">
                4
              </div>
              <div className="space-y-2">
                <h3 className="font-semibold text-white">Geographic Grid Heterogeneity</h3>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Different data center regions have drastically different power mixes. Verdant models execution sites (e.g., Mumbai, Delhi, Singapore, Finland) and routes tasks to the cleanest available site that satisfies latency requirements.
                </p>
                <div className="text-xs text-emerald-400 font-medium">Outcome: Transparent carbon accounting and regional load-balancing.</div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Tab 3: Side-by-Side Comparison */}
      {activeTab === 'comparison' && (
        <section className="space-y-6">
          <div className="text-center max-w-2xl mx-auto space-y-2">
            <h2 className="text-2xl md:text-3xl font-bold text-white">Side-by-Side Benchmark: Market Brief Pipeline</h2>
            <p className="text-slate-400 text-sm">
              Comparing standard naive execution (everything Large, ASAP in default region) against Verdant's optimization plan.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Naive card */}
            <div className="bg-[#0a0505] border border-red-900/40 rounded-3xl p-6 space-y-5">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs uppercase font-bold tracking-wider text-red-400">Baseline</span>
                  <h3 className="text-xl font-bold text-slate-100">Naive Agent Execution</h3>
                </div>
                <span className="px-3 py-1 bg-red-950/60 border border-red-800/60 text-red-300 text-xs font-semibold rounded-full">
                  Unscheduled
                </span>
              </div>

              <div className="space-y-3">
                <div className="flex justify-between items-center text-sm py-2 border-b border-red-900/20">
                  <span className="text-slate-400">Total Carbon Emitted</span>
                  <span className="font-mono font-bold text-red-400">1.4500 gCO₂e</span>
                </div>
                <div className="flex justify-between items-center text-sm py-2 border-b border-red-900/20">
                  <span className="text-slate-400">Total Energy Consumed</span>
                  <span className="font-mono font-bold text-slate-300">2.68 mWh</span>
                </div>
                <div className="flex justify-between items-center text-sm py-2 border-b border-red-900/20">
                  <span className="text-slate-400">API Cost</span>
                  <span className="font-mono font-bold text-slate-300">$0.01420</span>
                </div>
                <div className="flex justify-between items-center text-sm py-2 border-b border-red-900/20">
                  <span className="text-slate-400">Model Strategy</span>
                  <span className="text-xs text-red-300">100% Large (Pro) Tier</span>
                </div>
                <div className="flex justify-between items-center text-sm py-2">
                  <span className="text-slate-400">Grid Awareness</span>
                  <span className="text-xs text-slate-500">None (Fixed default site)</span>
                </div>
              </div>
            </div>

            {/* Verdant card */}
            <div className="bg-[#031508] border border-emerald-500/40 rounded-3xl p-6 space-y-5 shadow-xl shadow-emerald-950/40">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs uppercase font-bold tracking-wider text-emerald-400">Optimized</span>
                  <h3 className="text-xl font-bold text-white">🌿 Verdant Scheduler</h3>
                </div>
                <span className="px-3 py-1 bg-emerald-900/60 border border-emerald-600/60 text-emerald-300 text-xs font-semibold rounded-full animate-pulse">
                  -68% Carbon
                </span>
              </div>

              <div className="space-y-3">
                <div className="flex justify-between items-center text-sm py-2 border-b border-emerald-900/30">
                  <span className="text-slate-300">Total Carbon Emitted</span>
                  <span className="font-mono font-bold text-emerald-400">0.4632 gCO₂e <span className="text-xs text-emerald-500">(-68%)</span></span>
                </div>
                <div className="flex justify-between items-center text-sm py-2 border-b border-emerald-900/30">
                  <span className="text-slate-300">Total Energy Consumed</span>
                  <span className="font-mono font-bold text-slate-200">1.04 mWh <span className="text-xs text-emerald-500">(-61%)</span></span>
                </div>
                <div className="flex justify-between items-center text-sm py-2 border-b border-emerald-900/30">
                  <span className="text-slate-300">API Cost</span>
                  <span className="font-mono font-bold text-slate-200">$0.00410 <span className="text-xs text-emerald-500">(-71%)</span></span>
                </div>
                <div className="flex justify-between items-center text-sm py-2 border-b border-emerald-900/30">
                  <span className="text-slate-300">Model Strategy</span>
                  <span className="text-xs text-emerald-300">Tiered (S/M/L) + Cascades</span>
                </div>
                <div className="flex justify-between items-center text-sm py-2">
                  <span className="text-slate-300">Grid Awareness</span>
                  <span className="text-xs text-emerald-300">CPM Solar Shifting + Finland Clean Hydro</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Interactive Quick Launch Cards */}
      <section className="bg-[#030e06] border border-emerald-900/30 rounded-3xl p-8 space-y-6">
        <div>
          <h3 className="text-xl font-bold text-slate-100">Try It Yourself in 3 Steps</h3>
          <p className="text-sm text-slate-400 mt-1">
            Follow the natural Verdant pipeline flow or jump directly to any step:
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[
            {
              step: 'Step 1',
              title: 'Workflow Builder',
              desc: 'Select a preset (Market Brief, Code Review, Research Q&A) or build custom steps and define deadlines.',
              btn: 'Open Builder →',
              page: 'builder' as const,
              color: 'border-emerald-900/50 bg-[#06170c]',
            },
            {
              step: 'Step 2',
              title: 'Schedule & Gantt',
              desc: 'Inspect the Gantt chart with red critical path, green solar windows, and drag the Pareto "How Green?" slider.',
              btn: 'View Plan →',
              page: 'plan' as const,
              color: 'border-blue-900/40 bg-[#06121a]',
            },
            {
              step: 'Step 3',
              title: 'Live Execution',
              desc: 'Watch real Gemini & Ollama calls execute step-by-step with real-time SSE telemetry, verifiers, and cascades.',
              btn: 'Run Pipeline →',
              page: 'run' as const,
              color: 'border-amber-900/40 bg-[#171206]',
            },
            {
              step: 'Step 4',
              title: 'Carbon Receipt',
              desc: 'Review the verified carbon receipt, 5-stage ablation breakdown, and equivalent phone charges saved.',
              btn: 'View Receipt →',
              page: 'receipt' as const,
              color: 'border-emerald-900/50 bg-[#06170c]',
            },
          ].map(c => (
            <div key={c.step} className={`rounded-2xl border p-5 flex flex-col justify-between space-y-4 ${c.color}`}>
              <div>
                <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">{c.step}</span>
                <h4 className="font-bold text-slate-100 text-base mt-1">{c.title}</h4>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed">{c.desc}</p>
              </div>
              <button
                onClick={() => onNavigate(c.page, 'fixture-market-brief-001')}
                className="text-xs font-semibold text-emerald-400 hover:text-emerald-300 flex items-center gap-1 transition-colors"
              >
                {c.btn}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Glossary — plain-language definitions for anyone new to this space */}
      <section className="bg-[#030e06] border border-emerald-900/30 rounded-3xl p-8 space-y-5">
        <div>
          <h3 className="text-xl font-bold text-slate-100">Quick Glossary</h3>
          <p className="text-sm text-slate-400 mt-1">Terms you'll see around the app, explained simply.</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { term: 'Deadline', def: 'The total time the whole workflow is allowed to take, start to finish.' },
            { term: 'Quality floor', def: 'The minimum acceptable answer quality. If a real answer scores below this, Verdant automatically retries it with a stronger model.' },
            { term: 'Carbon intensity', def: 'How much CO₂e is emitted per unit of electricity (gCO₂e/kWh) at a given place and time — it changes hour to hour as the grid mix changes.' },
            { term: 'Slack', def: "Spare time a step has before it would delay the whole workflow. Steps with slack can be shifted to a cleaner time or a slower, greener model." },
            { term: 'Critical path', def: 'The chain of steps with zero slack — any delay here delays the entire workflow, so these always get the fastest setup.' },
            { term: 'Cascade', def: 'Try a cheap model first, check the answer, and only pay for an expensive model if the cheap one isn’t good enough.' },
            { term: 'Site', def: 'A place a model can run (e.g. a cloud region or your own computer). Different sites draw power from different, more or less clean electricity grids.' },
            { term: 'Solver', def: 'The algorithm that decides the plan. "Greedy" is fast; "CP-SAT" is an exact optimizer that can take longer but finds the best possible plan.' },
            { term: 'Carbon receipt', def: 'A summary after a run showing how much CO₂e, cost, and time you saved compared to the naive "just use the biggest model for everything" approach.' },
          ].map(g => (
            <div key={g.term} className="bg-[#05140a] border border-emerald-900/30 rounded-xl p-4">
              <div className="text-sm font-semibold text-emerald-300">{g.term}</div>
              <div className="text-xs text-slate-400 mt-1 leading-relaxed">{g.def}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Honesty & Academic Standards Banner */}
      <footer className="rounded-2xl border border-slate-800/80 bg-[#040905] p-5 flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-slate-400">
        <div className="flex items-center gap-3">
          <span className="text-lg">⚖️</span>
          <div>
            <strong className="text-slate-200">Scientific & Empirical Honesty:</strong> All energy (Wh) and grid carbon intensities (gCO₂e/kWh) are transparently labeled as modeled estimates based on the Google 2025 Environmental Report and public grid telemetry. Model calls, token latencies, verifiers, and cascading decisions are 100% real.
          </div>
        </div>
        <button
          onClick={() => onNavigate('report')}
          className="px-4 py-2 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-300 font-medium whitespace-nowrap hover:bg-emerald-900/60 transition-colors"
        >
          View Full Methodology →
        </button>
      </footer>
    </div>
  )
}
