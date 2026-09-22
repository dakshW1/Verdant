 # 🌿 Verdant — Carbon & Latency-Aware Agent Workflow Scheduler

     -> Verdant takes a multi-step AI agent workflow (a DAG of LLM calls — plan → retrieve → summarize → reason → verify → format) and automatically decides, for **every step**: which model tier to use, which site/region to run it in, when to start it, and whether to try a cheap model first before escalating. It then executes the plan with **real Gemini API calls**, verifies output quality live, and produces a Carbon Receipt comparing the result against a naive "just use the biggest model for everything" baseline.

## 🚀 Quickstart 

```bash
# 1. Install everything
make install

# 2. Run the backend test suite (131 backend + 9 frontend tests, all passing)
make test

# 3. Start both servers
make dev
# Backend:  http://localhost:8000
# Frontend: http://localhost:5173

On first load you'll be asked to sign in via email OTP (a 6-digit code emailed to you) — this is a demo auth gate, not core to the scheduling logic.

Environment flags that matter for testing

In backend/.env:
- MOCK_LLM=1 — use this for safe, free, deterministic testing. All LLM calls return canned responses instantly, no API key or quota needed.
- MOCK_LLM=0 — uses real Gemini API calls (a key is already configured, but free-tier quota is limited — expect occasional rate-limit fallbacks, which the app handles gracefully).
- USE_SYNTHETIC_CARBON=1 — uses a deterministic, seeded synthetic grid carbon-intensity model (always on by default; no external API needed).

🎬 3 Demo Scenarios (2–3 min script)

1. Short deadline (10 min) → Builder → load "Market Brief" preset → set deadline to 10 min → Plan. Watch it pick smaller/cheaper models where quality allows, with minimal deferral. Run it and check the Carbon Receipt for savings vs. naive.
2. Long deadline (6+ hrs) → same workflow, stretch the deadline. Watch non-critical steps get deferred into low-carbon time windows (visible on the Schedule/Gantt page as a carbon-intensity strip) — this is the core "when" decision most schedulers ignore.
3. Impossible constraint → set an unreasonably tight carbon budget with a short deadline. The planner returns an infeasibility explanation ("extend deadline to X, or accept quality Y") instead of silently failing.


 🧠 What makes this different from "a router + a dashboard"

      ┌─────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────┐
      │             Feature             │                                            Why it matters                                             │
      ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
      │ Critical-Path-Method (CPM)      │ Critical steps get the fastest config; steps with spare time get shifted into greener windows or      │
      │ slack analysis                  │ slower/cheaper models — automatically, per step.                                                      │
      ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
      │ Cascade escalation with a real  │ Tries a cheap model first; if a live LLM-judge scores the output below the required floor, it         │
      │ quality floor                   │ automatically retries with a stronger model — verified end-to-end, not just at planning time.         │
      ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
      │ Exact optimizer (CP-SAT) + fast │ Solves for the true optimum when possible; falls back to a heuristic if the exact solver is           │
      │  greedy fallback                │ slow/unavailable — auto-detected.                                                                     │
      ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
      │ Hard carbon invariant           │ The optimizer is mathematically guaranteed to never report higher carbon than the naive baseline      │
      │                                 │ (unless naive itself is infeasible) — enforced and regression-tested.                                 │
      ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
      │ Live "why this model" reasoning │ Streamed in real time as each step runs — not a post-hoc summary — showing which config was picked    │
      │                                 │ and why (cost/carbon/quality/deadline tradeoffs), with escalations shown as a visible transition.     │
      ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
      │ Carbon Receipt                  │ Real, measured token counts and durations vs. naive baseline, with clearly labeled estimates vs.      │
      │                                 │ measurements.                                                                                         │
      └─────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────┘

      ---




 ✅ Test Coverage

      Backend:  131 tests passing (pytest) — includes regression tests for two
                fixed bugs: an optimizer-carbon-invariant violation, and a
                quality-verifier parsing bug (JSON/plain-text judge responses).
      Frontend: 9 tests passing (vitest) — percentage formatting, duration
                formatting, edge cases (unknown vs. zero score, clamping).
      Run make test to reproduce.

      ---

      🏗️ Architecture

      Frontend (React + Vite + TypeScript)
         │  Builder → Schedule/Gantt → Run (live SSE) → Receipt
         ▼
      Backend (FastAPI, Python)
         │  DAG validation → CPM (critical path) → Scheduler (CP-SAT / Greedy)
         │  → Executor (real Gemini calls, live verifier, cascade escalation)
         │  → Carbon Receipt (naive baseline comparison)
         ▼
      SQLite (plans, runs, telemetry)  +  Synthetic carbon-intensity model

      Auth: email OTP via EmailJS (browser-side, free tier) — a demo login gate wrapping the app, separate from the scheduling logic above.




Honesty & Methodology

- Model calls are real. Every LLM call, token count, latency, and verifier score in a run is a genuine Gemini API response (or explicitly mocked when MOCK_LLM=1).
- Energy and carbon-intensity numbers are modeled estimates, not direct hardware measurements — sourced from public data and a synthetic diurnal grid model. This is clearly labeled in the UI wherever shown.
- Execution "sites" are accounting abstractions (Gemini's API isn't region-selectable) — they represent what a real regional deployment would cost, ready to plug into real regional endpoints later.

---

Known Limitations (time-boxed for hackathon)

- The Carbon Receipt's ablation waterfall (savings breakdown by feature) is currently illustrative proportional splitting rather than a full re-plan-per-stage computation.
- Live per-step reasoning streaming is implemented backend-first; frontend timeline UI is functional but minimal.
- Free-tier Gemini API quota is limited (~20 req/day per model tier) — MOCK_LLM=1 is recommended for repeated demo runs.
