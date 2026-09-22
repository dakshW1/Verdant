import { useState } from 'react'
import './index.css'
import { HomePage } from './pages/Home'
import { BuilderPage } from './pages/Builder'
import { PlanPage } from './pages/Plan'
import { RunPage } from './pages/Run'
import { ReceiptPage } from './pages/Receipt'
import { ReportPage } from './pages/Report'

export type Page = 'home' | 'builder' | 'plan' | 'run' | 'receipt' | 'report'

export default function App() {
  const [page, setPage] = useState<Page>('home')
  const [currentPlanId, setCurrentPlanId] = useState<string | null>('fixture-market-brief-001')
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)

  const handleNavigate = (targetPage: Page, planId?: string) => {
    if (planId) setCurrentPlanId(planId)
    setPage(targetPage)
  }

  const handlePlan = (planId?: string) => {
    if (planId) setCurrentPlanId(planId)
    setPage('plan')
  }

  const handleRun = (planId: string) => {
    setCurrentPlanId(planId)
    setPage('run')
  }

  const handleReceipt = (runId: string) => {
    setCurrentRunId(runId)
    setPage('receipt')
  }

  return (
    <div className="min-h-screen bg-[#020d07] text-slate-200 font-sans">
      {/* Top nav */}
      <nav className="border-b border-emerald-900/40 bg-[#020d07]/90 backdrop-blur sticky top-0 z-50">
        <div className="max-w-screen-xl mx-auto px-6 h-14 flex items-center justify-between gap-4">
          {/* Logo */}
          <div
            onClick={() => setPage('home')}
            className="flex items-center gap-2 cursor-pointer hover:opacity-90 transition-opacity"
          >
            <span className="text-2xl">🌿</span>
            <span className="font-bold text-lg tracking-tight text-emerald-400">Verdant</span>
            <span className="text-[10px] text-emerald-600 border border-emerald-800/80 rounded px-1.5 py-0.5 ml-1 font-mono">
              v1.0 · carbon-aware
            </span>
          </div>

          {/* Nav links */}
          <div className="flex items-center gap-1 sm:gap-2">
            {(
              [
                ['home', 'Overview', '🏠'],
                ['builder', 'Builder', '🛠️'],
                ['plan', 'Schedule', '📊'],
                ['run', 'Run', '⚡'],
                ['receipt', 'Receipt', '🧾'],
                ['report', 'Report', '📑'],
              ] as [Page, string, string][]
            ).map(([id, label, icon]) => (
              <button
                key={id}
                onClick={() => setPage(id)}
                className={`text-xs sm:text-sm font-medium transition-all px-2.5 py-1 rounded-lg flex items-center gap-1.5 ${
                  page === id
                    ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700/60 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-emerald-950/20'
                }`}
              >
                <span>{icon}</span>
                <span>{label}</span>
                {id === 'plan' && currentPlanId && (
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                )}
                {id === 'run' && currentRunId && page !== 'run' && (
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                )}
              </button>
            ))}
          </div>

          <div className="hidden lg:flex items-center gap-4 text-xs text-slate-500">
            <span className="flex items-center gap-1.5 bg-[#041208] border border-emerald-900/40 px-2.5 py-1 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              Gemini 2.5 + Synthetic CI Active
            </span>
          </div>
        </div>
      </nav>

      {/* Page content */}
      <main className="max-w-screen-xl mx-auto px-6 py-8">
        {page === 'home' && (
          <HomePage onNavigate={handleNavigate} />
        )}
        {page === 'builder' && (
          <BuilderPage onPlan={handlePlan} />
        )}
        {page === 'plan' && (
          <PlanPage onRun={handleRun} initialPlanId={currentPlanId} />
        )}
        {page === 'run' && (
          <RunPage planId={currentPlanId} onReceipt={handleReceipt} onSelectPlan={setCurrentPlanId} />
        )}
        {page === 'receipt' && (
          <ReceiptPage runId={currentRunId} />
        )}
        {page === 'report' && (
          <ReportPage />
        )}
      </main>
    </div>
  )
}

