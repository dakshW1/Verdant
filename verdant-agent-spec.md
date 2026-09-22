# VERDANT — Carbon- & Latency-Aware Agent Workflow Scheduler
**Master spec for the coding agent.** Read this whole file before writing any code. Build phase by phase (Section 14). Do not skip ahead. Do not invent requirements that contradict this file; if something is ambiguous, pick the simplest option, leave a `# DECISION:` comment, and continue.

---

## 0. One-paragraph summary

Verdant takes an agentic workflow (a DAG of LLM steps such as plan → retrieve → summarize → reason → verify → format) plus user constraints (deadline, carbon budget, quality floor, cost cap). For every step it decides **which model** (small/medium/large, cloud or local), **where** it runs (execution site with its own grid carbon intensity), **when** it starts (now, or deferred into a greener time window if the step has slack), and **whether to cascade** (try a cheap model, verify, escalate only if needed). It then executes the plan for real (real LLM calls), re-plans online when reality deviates, learns from telemetry, and prints a **Carbon Receipt** comparing the result with naive baselines.

### What makes it different from a "router + dashboard"
1. **Critical-path-aware scheduling.** DAG + CPM slack. Critical steps go fast; slack steps get slower/greener configs and are time-shifted into low-carbon windows.
2. **Cascades with a value-of-information escalation rule** (not a fixed threshold).
3. **Exact optimizer (OR-Tools CP-SAT) + fast greedy heuristic**, compared in an ablation.
4. **Pareto frontier + slider** across latency / carbon / cost / quality.
5. **Chance-constrained carbon budget** using forecast uncertainty (plan holds with ~90% confidence).
6. **Infeasibility explanations** ("5 g is impossible in 10 min; you need 22 min or accept quality 0.88").
7. **Receding-horizon re-planning** (MPC) after each step using actuals.
8. **Learning loop** (EWMA for latency/tokens, Beta posteriors for acceptance/quality).
9. **Carbon Receipt + savings ablation** ("where the savings came from").
10. **Learned quality predictor** (yes/no traits of each step's input → per-model pass probability, break-even cascade skipping, fuzzy Pareto pruning), adapted from BRANE (arXiv:2605.27361).

---

## 1. Ground rules (non-negotiable)

- **Honesty.** Energy-per-token numbers and grid intensities are **estimates**. Every number in `registry/*.yaml` has a `source` or `note` field. UI shows an "Estimates" badge with a tooltip. Never present modeled numbers as measured.
- **Execution sites are simulated, model calls are real.** The Gemini API is not region-selectable, so "sites" are accounting abstractions (each with its own grid carbon intensity, PUE, RTT). The model calls, token counts, latencies, verifier scores, and cascade decisions are real. If real regional endpoints (e.g. Vertex AI regions) are added later, they plug into the same `Site` interface. State this in the pitch.
- **Virtual clock for deferral.** Deferring a step by 3 hours must not take 3 hours in a demo. The executor uses an event-driven virtual clock (Section 9). Decisions are real; waiting is fast-forwarded. Say so in the UI ("simulated time").
- **Mock mode is mandatory.** `MOCK_LLM=1` makes all LLM clients return deterministic canned outputs with plausible token counts and latencies. All tests and offline dev use it. Demo fallback too.
- **All tunable constants live in YAML**, never hardcoded in Python.
- **Units everywhere:** time = integer seconds; energy = Wh; carbon = gCO2e; carbon intensity = gCO2e/kWh; cost = USD; quality = float in [0,1]. Put units in variable names (`energy_wh`, `carbon_g`, `dur_s`).
- **Type everything.** Pydantic v2 on backend, TypeScript strict on frontend. Generate TS types from the OpenAPI schema (`openapi-typescript`).
- **Deterministic tests.** Seed all randomness (`SEED=42`).

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn, Pydantic v2, `httpx` (async), `numpy`, `scipy`, `ortools` (CP-SAT), `pyyaml`, `sqlite3`/SQLModel, `pytest`, `sse-starlette` |
| LLM (real) | `google-genai` SDK → three Gemini tiers (small/medium/large); optional local model via Ollama HTTP API |
| Carbon data | Electricity Maps API (optional token) → cached JSON snapshot → synthetic diurnal model (always available) ; UK National Grid Carbon Intensity API (free, no key) as extra real forecast shape |
| Storage | SQLite (telemetry, runs, plans) |
| Frontend | Vite + React + TypeScript + Tailwind, `@xyflow/react` (DAG builder), Recharts (Pareto, CI curves), custom SVG Gantt |
| Realtime | Server-Sent Events (SSE) for live run events |
| Packaging | `docker-compose` optional; primary path is `make dev` |

`.env.example`
```
GEMINI_API_KEY=
ELECTRICITYMAPS_TOKEN=          # optional
OLLAMA_HOST=http://localhost:11434   # optional
MOCK_LLM=1                       # 1 = no real LLM calls
USE_SYNTHETIC_CARBON=1           # 1 = skip live carbon APIs
SEED=42
```
**Model IDs:** do NOT hardcode from memory. In `registry/models.yaml` use the currently available Gemini model IDs from the official docs (a small/"flash-lite" tier, a "flash" tier, a "pro" tier). Add a startup check that lists available models and warns if a configured ID is missing.

---

## 3. Repo layout

```
verdant/
  AGENTS.md                      # copy of this spec
  Makefile  docker-compose.yml  .env.example  README.md
  backend/
    pyproject.toml
    app/
      main.py                    # FastAPI app, routers, CORS, SSE
      config.py                  # loads env + registries
      schemas.py                 # ALL Pydantic models (Section 5)
      db.py                      # sqlite engine, tables
      registry/
        models.yaml  sites.yaml  step_types.yaml  equivalents.yaml  presets.yaml
      carbon/
        provider.py              # CarbonProvider interface + factory
        electricitymaps.py  ukgrid.py  synthetic.py  cache.py
        forecast.py              # CIForecast object: mean, sigma per window
      profiles/
        latency.py  energy.py  cost.py  quality.py   # per-config estimators
        options.py               # builds ConfigOption list per step
      dag/
        graph.py                 # validation, topo sort, preds/succs
        cpm.py                   # ES/EF/LS/LF/slack
      scheduler/
        greedy.py  cpsat.py  pareto.py  relax.py  explain.py
        planner.py               # facade: plan(problem) -> PlanResult
        objective.py             # normalization + weights
      executor/
        clock.py                 # VirtualClock
        runner.py                # async DAG executor
        llm_clients.py           # GeminiClient, OllamaClient, MockClient
        cascade.py  verifier.py  voi.py
        events.py                # event bus + SSE
        replan.py
      learning/
        telemetry.py  estimators.py  calibration.py
      receipt/
        baselines.py  receipt.py  ablation.py
    scripts/
      calibrate.py               # benchmark models -> fills profiles (Section 8.9)
      seed_telemetry.py          # fake history so learning has data
      snapshot_carbon.py         # cache real CI data to JSON for offline demo
    tests/                       # Section 13
  frontend/
    src/
      api/  (generated types + client)
      pages/ Builder.tsx  Plan.tsx  Run.tsx  Receipt.tsx
      components/ DagCanvas, ConstraintPanel, Gantt, CarbonStrip,
                  ParetoChart, StepInspector, ReceiptCard, AblationBar, LiveLog
  workflows/
    market_brief.json  code_review.json  nightly_report.json
    data/  (small text corpora used by retrieval steps)
```

---

## 4. Core concepts

- **Workflow**: DAG of **Steps**.
- **Step**: has a `step_type` (planning, extraction, summarization, reasoning, verification, formatting, code), a prompt template, importance weight `omega`, optional `min_quality`, optional per-step release/deadline, and estimated input size.
- **Site**: where a model runs (`local`, `gcp-mumbai`, `gcp-delhi`, `gcp-singapore`, `gcp-finland`, ...). Has grid zone, PUE, RTT, optional queue delay, and which models it hosts.
- **Config option** `c = (model, site, mode)` where `mode ∈ {single, cascade(small→large, verifier)}`.
- **Plan**: for each step: chosen config, planned start time (seconds from t0), expected + worst-case metrics, human-readable rationale.
- **Time windows**: carbon intensity is looked up per window of width `W` (default 1800 s). Horizon `H` = deadline (max 24 h).

---

## 5. Schemas (`schemas.py`) — implement exactly

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

StepType = Literal["planning","extraction","summarization","reasoning","verification","formatting","code"]

class Step(BaseModel):
    id: str
    name: str
    step_type: StepType
    prompt_template: str                 # may contain {{upstream.<step_id>}} and {{input.<key>}}
    depends_on: list[str] = []
    omega: float = Field(1.0, ge=0)      # importance; normalized so sum = 1 at plan time
    min_quality: float = 0.0             # per-step floor
    est_tokens_in: Optional[int] = None  # override; else estimated
    est_tokens_out: Optional[int] = None
    max_tokens_out: int = 800
    release_s: int = 0                   # earliest start
    deadline_s: Optional[int] = None     # per-step deadline
    cascade_allowed: bool = True
    allowed_sites: Optional[list[str]] = None
    verifier: Optional[Literal["schema","code_exec","llm_judge","none"]] = "llm_judge"
    output_schema: Optional[dict] = None # for "schema" verifier

class Workflow(BaseModel):
    id: str
    name: str
    inputs: dict[str,str] = {}
    steps: list[Step]

class Constraints(BaseModel):
    deadline_s: int = 600
    carbon_budget_g: Optional[float] = None
    cost_budget_usd: Optional[float] = None
    quality_floor: float = 0.85
    robust_z: float = 1.28               # 0 = mean carbon; 1.28 ≈ 90% conf
    start_time_iso: Optional[str] = None # default now (sim)
    allow_deferral: bool = True
    allow_cascade: bool = True
    allowed_sites: Optional[list[str]] = None

class Weights(BaseModel):                 # normalized to sum 1 by planner
    latency: float = 0.2
    cost: float = 0.1
    energy: float = 0.1
    carbon: float = 0.4
    quality: float = 0.2

class ConfigOption(BaseModel):
    step_id: str
    model: str
    site: str
    mode: Literal["single","cascade"]
    escalate_model: Optional[str] = None
    verifier_model: Optional[str] = None
    dur_expected_s: int
    dur_worstcase_s: int
    energy_wh: float                     # expected
    energy_wh_worst: float
    cost_usd: float
    quality: float                       # expected
    p_accept: Optional[float] = None     # cascade only
    tokens_in: int
    tokens_out: int

class StepPlan(BaseModel):
    step_id: str
    option: ConfigOption
    start_s: int
    slack_s: int
    is_critical: bool
    carbon_g_expected: float
    carbon_g_robust: float
    ci_g_per_kwh: float
    rationale: str

class Totals(BaseModel):
    makespan_s: int; cost_usd: float; energy_wh: float
    carbon_g: float; carbon_g_robust: float; quality: float

class PlanResult(BaseModel):
    plan_id: str
    status: Literal["optimal","feasible","relaxed","infeasible"]
    steps: list[StepPlan]
    totals: Totals
    baselines: dict[str, Totals]         # naive, fastest, smallest
    relaxations: list[dict] = []         # [{constraint, requested, needed}]
    pareto: list[Totals] = []
    solver: Literal["greedy","cpsat"]
    solve_ms: int

class StepRunResult(BaseModel):
    step_id: str; option_used: ConfigOption; escalated: bool
    start_s: int; end_s: int; tokens_in: int; tokens_out: int
    energy_wh: float; carbon_g: float; cost_usd: float
    verifier_score: Optional[float]; output_text: str
```

---

## 6. Registries (YAML) — seed values

All numbers below are **placeholders/estimates**. Keep `source`/`note`. The `calibrate.py` script overwrites latency fields with measured values.

`registry/models.yaml`
```yaml
models:
  - id: small            # alias used by the scheduler
    provider: gemini
    api_id: "<current flash-lite tier ID>"
    tier: S
    price_in_per_mtok_usd:  "<look up>"   # fill from official pricing page
    price_out_per_mtok_usd: "<look up>"
    energy_wh_per_tok_in:  0.00002
    energy_wh_per_tok_out: 0.00005
    ttft_s: 0.4
    tokens_per_s: 180
    ctx: 1000000
    note: "energy per token = estimate scaled from public per-prompt figures"
  - id: medium
    provider: gemini
    api_id: "<current flash tier ID>"
    tier: M
    energy_wh_per_tok_in:  0.00001
    energy_wh_per_tok_out: 0.00015
    ttft_s: 0.6
    tokens_per_s: 120
  - id: large
    provider: gemini
    api_id: "<current pro tier ID>"
    tier: L
    energy_wh_per_tok_in:  0.00005
    energy_wh_per_tok_out: 0.0007
    ttft_s: 1.5
    tokens_per_s: 60
  - id: local-3b          # optional
    provider: ollama
    api_id: "llama3.2:3b"     # or qwen2.5:3b
    tier: S
    device_power_w: 35        # avg draw during inference (estimate; measure if possible)
    prefill_tps: 400
    tokens_per_s: 25
    ttft_s: 0.3
    price_in_per_mtok_usd: 0
    price_out_per_mtok_usd: 0
```
Reference points to cite in the deck (verify wording before citing): Google's 2025 report on Gemini text-prompt energy (median ≈ 0.24 Wh/prompt), Luccioni et al. "Power Hungry Processing" (2023), ML.ENERGY leaderboard, Epoch AI per-query estimate.

`registry/sites.yaml`
```yaml
sites:
  - id: local
    label: "On-device (Bangalore)"
    zone: IN-SO
    pue: 1.0
    rtt_s: 0.0
    models: [local-3b]
    device: true
  - id: gcp-mumbai
    label: "Cloud – Mumbai"
    zone: IN-WE
    pue: 1.10
    rtt_s: 0.05
    models: [small, medium, large]
  - id: gcp-delhi
    label: "Cloud – Delhi"
    zone: IN-NO
    pue: 1.10
    rtt_s: 0.06
    models: [small, medium, large]
  - id: gcp-singapore
    label: "Cloud – Singapore"
    zone: SG
    pue: 1.10
    rtt_s: 0.09
    models: [small, medium, large]
  - id: gcp-finland
    label: "Cloud – Finland"
    zone: FI
    pue: 1.10
    rtt_s: 0.20
    models: [small, medium, large]
# Synthetic CI parameters (illustrative; replaced by live/snapshot data when available)
synthetic_ci:
  IN-SO: {base: 600, solar_dip: 0.35, wind_night_dip: 0.10, sigma0: 15, kappa_per_h: 4, utc_offset_h: 5.5}
  IN-WE: {base: 750, solar_dip: 0.30, wind_night_dip: 0.05, sigma0: 20, kappa_per_h: 5, utc_offset_h: 5.5}
  IN-NO: {base: 700, solar_dip: 0.25, wind_night_dip: 0.03, sigma0: 20, kappa_per_h: 5, utc_offset_h: 5.5}
  SG:    {base: 470, solar_dip: 0.05, wind_night_dip: 0.00, sigma0: 10, kappa_per_h: 2, utc_offset_h: 8}
  FI:    {base: 120, solar_dip: 0.05, wind_night_dip: 0.30, sigma0: 25, kappa_per_h: 6, utc_offset_h: 2}
```

`registry/step_types.yaml` — priors per step type
```yaml
step_types:
  planning:      {tok_in: 400,  tok_out: 250, q: {S: 0.80, M: 0.90, L: 0.95}, p_accept_S: 0.70}
  extraction:    {tok_in: 1500, tok_out: 300, q: {S: 0.88, M: 0.93, L: 0.95}, p_accept_S: 0.85}
  summarization: {tok_in: 1200, tok_out: 300, q: {S: 0.86, M: 0.92, L: 0.95}, p_accept_S: 0.80}
  reasoning:     {tok_in: 1500, tok_out: 700, q: {S: 0.65, M: 0.85, L: 0.95}, p_accept_S: 0.35}
  verification:  {tok_in: 1500, tok_out: 200, q: {S: 0.75, M: 0.88, L: 0.95}, p_accept_S: 0.55}
  formatting:    {tok_in: 800,  tok_out: 500, q: {S: 0.95, M: 0.97, L: 0.98}, p_accept_S: 0.95}
  code:          {tok_in: 1000, tok_out: 600, q: {S: 0.60, M: 0.82, L: 0.94}, p_accept_S: 0.30}
prior_strength: 10        # pseudo-count for Beta priors
```
`presets.yaml`: weight presets — `green {G:.55,E:.15,L:.10,C:.05,Q:.15}`, `fast {L:.55,G:.10,E:.05,C:.10,Q:.20}`, `balanced {L:.2,C:.1,E:.1,G:.4,Q:.2}`, `cheap {C:.5,...}`.

`equivalents.yaml` (approximate, flagged in UI): `km_driven_per_g: 1/120`, `phone_charges_per_g: 1/8` — mark as "rough equivalents".

---

## 7. The math (single source of truth — implement exactly)

### 7.1 Notation
Step set V, edges E ⊂ V×V. Config set C_i per step i. Time windows w = 0..N−1 of width W seconds; CI_s[w] mean carbon intensity (gCO2e/kWh) at site s in window w with std σ_s[w]. Decision: config c_i ∈ C_i and start S_i (integer seconds).

### 7.2 Token estimates
- `tin_i` = tokens(prompt template rendered with upstream outputs). Before execution use `est_tokens_in`, else step_type prior, else learned regression (7.9). Rough token count fallback: `len(text)/4`.
- `tout_i` = min(max_tokens_out, learned mean for (step_type, model)); prior from `step_types.yaml`.

### 7.3 Latency (per single-model config)
```
d_single = rtt_s + queue_s + ttft_m + tout / tokens_per_s_m        (cloud)
d_single = ttft_m + tin/prefill_tps + tout / tokens_per_s_m        (local)
d_wc     = rtt_s + queue_s + (ttft_m + tout_max/tokens_per_s_m) * 1.3 (worst-case multiplier configurable; better: mu + 1.28*sigma from telemetry)
```
### 7.4 Energy
```
Cloud:  E_wh = PUE_s * (tin * e_in_m + tout * e_out_m)
Local:  E_wh = device_power_w * d_single / 3600
Carbon: g = (E_wh / 1000) * CI_s[w(S)]         # gCO2e
Robust: g_rob = (E_wh / 1000) * (CI_s[w] + z * sigma_s[w])     # z = robust_z
```
Assumption: step duration ≪ W so CI at start window is representative. If d > W, average CI over covered windows.

### 7.5 Cost
```
cost = tin*price_in_m/1e6 + tout*price_out_m/1e6        (local: 0; optionally + electricity cost)
```
### 7.6 Quality
- Single: `q = q_prior[step_type][tier]` blended with learned Beta mean (7.9).
- Workflow quality: `Q = Σ_i ω_i q_i`, with ω normalized (Σω=1). Also enforce per-step floors `q_i ≥ min_quality_i` and global `Q ≥ quality_floor`.
- (Optional stretch) error-propagation form: `log Q = Σ ω_i log q_i`.

### 7.7 Cascade (mode = cascade: small S → verify V → escalate to large L)
Let p = P(verifier accepts S output at threshold τ), ρ = precision of accepted small outputs (fraction judged equal-or-better than teacher), q_L large-model quality.
```
E[cost]    = cost_S + cost_V + (1-p) * cost_L
E[energy]  = e_S + e_V + (1-p) * e_L
E[latency] = d_S + d_V + (1-p) * d_L
d_wc       = d_S + d_V + d_L                     # used for deadline safety
E[quality] = p * ρ + (1-p) * q_L
```
Defaults: ρ = 0.93, τ = 0.7. `p` = Beta posterior mean for (step_type, small_model) — 7.9. The verifier is cheap (small model with a rubric, or programmatic).

**Runtime escalation rule (value of information).** After the verifier returns score s, calibrated probability that the small output is good: `π(s) = P(good | s)` (Platt scaling or isotonic regression fit on calibration data; prior π(s)=s).
Escalate iff
```
w_Q * (q_L - π(s)) / QLOSS_UNIT  >  w_C * ΔC/C0 + w_E * ΔE/E0 + w_G * ΔG/G0 + w_L * ΔL/M0
```
where Δ are the extra cost/energy/carbon/latency of running L now and normalizers are the baseline totals (7.8); `QLOSS_UNIT = 0.10`. **Override:** if `now + d_L > LF_i` (would break the step's latest finish), do not escalate; accept the small output and flag `low_confidence=true` (or escalate at a faster site if that fits).

### 7.8 Objective (unitless, baseline-normalized)
Baselines (Section 8.10) give C0, E0, G0, M0, Q0 (from the naive baseline). Weights w normalized to sum 1.
```
J = w_L * M/M0 + w_C * C/C0 + w_E * E/E0 + w_G * G/G0 + w_Q * (1 - Q)/QLOSS_UNIT
```
(with QLOSS_UNIT = 0.10, ten points of quality loss = 1 unit.) Minimize J subject to:
```
S_j ≥ S_i + d_wc,i          for (i,j) ∈ E
S_i ≥ release_i ;  S_i + d_wc,i ≤ deadline_i (if set)
M = max_i (S_i + d_wc,i) ≤ T_max            (constraints.deadline_s)
Σ g_rob,i ≤ G_max          (if set)   [robust carbon]
Σ cost_i ≤ C_max           (if set)
Q ≥ Q_min ;  q_i ≥ min_quality_i
```
### 7.9 Learning updates
- **Latency & tokens (EWMA + variance):** `μ ← α x + (1-α) μ`, `v ← (1-α)(v + α (x-μ_old)²)`, α = 0.3. Used quantile: `μ + 1.28 sqrt(v)` for worst-case.
- **Token regression:** once n ≥ 8 per (step_type, model): `log tout = a + b log tin` via `numpy.polyfit`; else prior.
- **Acceptance & quality (Beta–Bernoulli):** prior `Beta(α0, β0)` with `α0 = q_prior * K`, `β0 = (1-q_prior) * K`, K = `prior_strength`. On each verified outcome: `α += 1` if pass, else `β += 1`. Posterior mean `α/(α+β)`. Use one Beta for p_accept per (step_type, small_model) and one for quality per (step_type, model).
- **Optional Thompson sampling** for exploration: sample from the posterior when choosing among near-tied configs at plan time (flag `explore=true`; off by default so demos are deterministic).
- **Verifier calibration:** fit isotonic regression `π(s)` from (score, teacher_agreement) pairs collected in `calibrate.py`.

### 7.10 CI forecast model (synthetic fallback)
Local hour `h = ((t/3600) + utc_offset) mod 24`.
```
solar(h)  = max(0, sin(pi * (h - 6) / 12))              # 0 at 06:00 and 18:00, peak at 12:00
night(h)  = 1 if (h >= 22 or h < 5) else 0
CI(t)     = base * (1 - solar_dip*solar(h) - wind_night_dip*night(h)) + noise(t)
sigma(t)  = sigma0 + kappa_per_h * hours_ahead
```
noise: AR(1), `n_t = 0.8 n_{t-1} + N(0, (0.3*sigma)^2)`, seeded. Clip CI ≥ 20.
When real data exists (Electricity Maps forecast / snapshot), use it for `mean` and keep `sigma` from the model above unless the API returns intervals.

### 7.11 Critical Path Method (CPM)
With durations `d_i` and horizon `T` (= deadline, so slack includes deadline headroom):
```
ES_i = max_{p ∈ pred(i)} EF_p  (0 if none);   EF_i = ES_i + d_i
LF_i = min_{s ∈ succ(i)} LS_s  (T if none);   LS_i = LF_i - d_i
slack_i = LS_i - ES_i;   critical ⇔ slack_i ≤ ε (ε = 1 s)
```
### 7.12 Pareto frontier (ε-constraint)
Objectives to minimize: latency M, carbon G, cost C; maximize Q. Method: for each grid point `(T_k, Q_j)` in `deadline ∈ linspace(M_min, M_max, 8)` × `quality_floor ∈ {0.80, 0.85, 0.90, 0.95}`, solve `min G` (secondary: min C) subject to those constraints. Collect solutions and filter to non-dominated (a point is dominated if another is ≤ in G, M, C and ≥ in Q with at least one strict). Return ≤ 30 points. Cache aggressively (each solve ≤ 2 s).

### 7.13 Infeasibility relaxation (elastic constraints)
If the problem is infeasible, re-solve with slack variables: `M ≤ T_max + s_T`, `G ≤ G_max + s_G`, `Q ≥ Q_min - s_Q`, each with big-M penalty (`1e3` per normalized unit), minimizing total slack first. Report the smallest relaxations needed as `relaxations=[{constraint:"deadline_s", requested:600, needed:1320}, ...]`. Also report single-axis relaxations (relax only one constraint at a time) so the UI can say "either extend deadline to X **or** accept quality Y".

### 7.14 Learned quality predictor (step-level, Query2Conf-style)
Motivation: the static priors `q[step_type][tier]` and `p_accept_S` ignore that difficulty varies per step input. Learn `P(model output is good | traits of this step's input)`. Inspired by BRANE (Pan et al., 2026, arXiv:2605.27361): an LLM turns each input into a short vector of yes/no traits; one lightweight classifier per configuration predicts correctness; selection is `argmax p̂ − λ·cost`. We adapt it to workflow steps and keep our own scheduling (deadline, slack, carbon, DAG), which that paper does not model.

**Traits.** `x(s) = [F(s), g(s)]`.
- `F(s) ∈ {0,1}^d`: d yes/no questions (default d = 10) answered by a cheap LLM from the step input alone (e.g. "requires combining 3 or more sources?", "contains numbers or calculations?", "must output strict JSON?", "multiple simultaneous constraints?").
- `g(s)`: free deterministic features: `log(tokens_in)`, has_digits, regex count of constraint words, step_type one-hot, DAG depth.
- Preprocessing: drop constant traits; drop one of any pair with |corr| > 0.99 on the training sample.

**Model.** For each model m and each head h ∈ {accept, good}: `p̂_{m,h}(s) = sigmoid(w·x(s) + b)` fit with L2 logistic regression (C = 0.5).
- `label_accept = 1` if the verifier score ≥ τ.
- `label_good = 1` if verifier accepted AND the large-model judge agrees with the teacher (large model output). For the large model itself `label_good = verifier accepted`.
- `accept` head is trained for small-tier models (feeds cascade `p`); `good` head for all tiers (feeds `q`). `ρ = mean(label_good | accepted)` per small model.

**Use-gate (5-fold stratified CV).** Use the learned model only if `n ≥ 30` and `CV_logloss_LR ≤ CV_logloss_baserate − 0.01`. Otherwise fall back to the Beta posterior mean (7.9).

**Blend.** `p_used = n/(n+K) * p̂ + K/(n+K) * p_prior`, with `K = prior_strength` (10).

**Cascade break-even.** Let `J_x(s)` = the step's normalized weighted resource score of running config x (the latency, cost, energy and carbon terms of 7.8, excluding quality). Trying the small model first pays off iff
```
p̂ * J_L  >  J_S + J_V      ⇔      p̂ > p* = (J_S + J_V) / J_L
```
If `p̂ < p*` the executor skips the small model and runs large directly. The planner already reflects this because cascade option metrics (7.7) use `p̂(s)`, so greedy/CP-SAT stop picking cascades for hard steps.

**Fuzzy Pareto pruning (replaces the pruning rule in 8.2 step 3).** Per step, project each option to `(R, q)` with
`R = w_L d/d0 + w_C c/c0 + w_E e/e0 + w_G e·CI_min/g0` (`CI_min` = minimum CI over allowed sites/windows). Strict frontier = non-dominated on (min R, max q). Keep option c' iff some frontier vertex c* satisfies
```
q(c*) - q(c') <= tau_acc (0.02)   and   R(c') <= (1 + tau_cost) * R(c*)  (tau_cost = 0.10)
```
Cap at 12 options per step. The fuzziness guards against noisy quality estimates.

**Characterization overhead.** One small-model call per step (~300 tokens in, ≤ 60 out) returns all d bits as JSON. When the predictor is enabled, add its energy/cost/duration to the option as `overhead_*` and show "characterization overhead" in the receipt. Cache by prompt hash.

**Plan-time vs run-time features.** At plan time, for steps whose prompt depends on upstream outputs, compute traits on the template with placeholders replaced by typical-length dummy text (`features_estimated = true`). At run time, once upstream outputs exist, recompute traits on the rendered prompt; if `|p̂_new - p̂_plan| > 0.15` emit a replan trigger (8.12 trigger (e)).

**Honesty.** With ~50 labeled samples per model the predictor is noisy. Always show CV log-loss/AUC and a reliability diagram; keep the use-gate; label the feature as "learned from N samples".

---

## 8. Modules — behavior and pseudocode

### 8.1 `carbon/` providers
```python
class CarbonProvider(Protocol):
    async def forecast(self, zone: str, start_ts: int, horizon_s: int, window_s: int) -> CIForecast: ...
class CIForecast(BaseModel):
    zone: str; window_s: int; start_ts: int
    mean: list[float]; sigma: list[float]; source: Literal["live","snapshot","synthetic"]
```
- Factory order: if `USE_SYNTHETIC_CARBON=1` → synthetic. Else try Electricity Maps (`GET https://api.electricitymap.org/v3/carbon-intensity/latest?zone=<Z>` and `/forecast?zone=<Z>`, header `auth-token`; forecast availability depends on plan — on 4xx/timeout fall back), then `data/carbon_snapshot.json`, then synthetic.
- UK grid API (`https://api.carbonintensity.org.uk/intensity/<from>/fw48h`, no key) can back a "Europe" site with a real 48 h forecast; resample to `window_s`.
- Always resample to windows of `window_s` (default 1800). Cache 15 min in memory + on disk.
- `scripts/snapshot_carbon.py` writes the last-fetched real curves to `data/carbon_snapshot.json` for offline demo. UI shows source badge (`live` / `snapshot` / `synthetic`) per site.

### 8.2 `profiles/options.py` — build `ConfigOption`s
For each step and each allowed (model, site) hosted pair:
1. Single option using 7.2–7.6.
2. If `cascade_allowed` and `constraints.allow_cascade`: for each ordered pair (small-tier model, large-tier model) at the same site (cross-site cascades are a stretch), build a cascade option per 7.7. Verifier = small model unless verifier type is `schema`/`code_exec` (cost ≈ 0).
3. **Prune dominated options**: drop option A if some B has ≤ dur_wc, ≤ energy_wh, ≤ cost, ≥ quality and CI at B's site is ≤ A's site CI for every window (or simply: keep the top-K = 12 per step by non-dominated rank on (dur_wc, energy_wh×min_CI, cost, −quality)).
4. Drop options with `quality < step.min_quality`.

### 8.3 `dag/graph.py`
Validate: unique ids, all `depends_on` exist, acyclic (Kahn). Provide `topo_order`, `preds`, `succs`, `sources`, `sinks`, `longest_path`.

### 8.4 `dag/cpm.py`
```python
def cpm(order, preds, succs, dur: dict[str,int], horizon: int, eps: int = 1):
    ES, EF, LS, LF = {}, {}, {}, {}
    for i in order:
        ES[i] = max((EF[p] for p in preds[i]), default=0)
        EF[i] = ES[i] + dur[i]
    for i in reversed(order):
        LF[i] = min((LS[s] for s in succs[i]), default=horizon)
        LS[i] = LF[i] - dur[i]
    slack = {i: LS[i] - ES[i] for i in order}
    return ES, EF, LS, LF, slack, {i for i in order if slack[i] <= eps}
```
Return `feasible=False` if any slack < 0.

### 8.5 `scheduler/greedy.py` — slack-reclamation heuristic (fast, always available)
```
def greedy_plan(problem, W, constraints):
    cfg = {i: fastest option with quality >= min_quality_i}          # start all-fast
    loop:
        dur = {i: cfg[i].dur_worstcase_s}
        ES, EF, LS, LF, slack, crit = cpm(..., horizon=T_max)
        if any(slack < 0): return infeasible
        changed = False
        for i in steps sorted by slack DESC:                           # most slack first
            best_c, best_score = cfg[i], local_J(i, cfg[i], greenest_start(i, cfg[i], ES[i], LS[i]))
            for c in options[i]:
                extra = c.dur_worstcase_s - dur[i]
                if extra > slack[i]: continue                          # would push critical path
                lo, hi = ES[i], LS[i] - max(extra, 0)
                start = greenest_start(i, c, lo, hi)                   # argmin over windows in [lo,hi] of CI_site[w]*energy
                sc = local_J(i, c, start)
                if sc < best_score - 1e-9: best_c, best_score = c, sc
            if best_c is not cfg[i]:
                cfg[i] = best_c; changed = True; break                 # recompute CPM after each change
        if not changed: break
    assign starts: for i in topo order: start_i = max(EF of preds, greenest feasible within [ES_i, LS_i])
    check global constraints (G_max robust, C_max, Q_min). If violated: increase w_G (x1.5) and w_Q as needed and rerun (max 5 rounds); else status="feasible"
```
`local_J` is `J` (7.8) restricted to the step's own contribution (latency term uses the step's delta to the critical path). `greenest_start` scans windows, honoring `allow_deferral`; if false, returns `lo`.

### 8.6 `scheduler/cpsat.py` — exact model (OR-Tools CP-SAT)
Time in integer seconds; windows of width W. Joint boolean `b[i,c,w]` = "step i uses config c and starts in window w".
```python
from ortools.sat.python import cp_model
SC = 10_000   # scaling for float -> int coefficients

def solve_cpsat(P, cons, wts, base, time_limit_s=10, elastic=False):
    m = cp_model.CpModel()
    T = cons.deadline_s
    S, D, b = {}, {}, {}
    for i in P.steps:
        S[i] = m.NewIntVar(P.release[i], T, f"S_{i}")
        D[i] = m.NewIntVar(1, T, f"D_{i}")
        lits = []
        for ci, c in enumerate(P.opts[i]):
            for w in P.allowed_windows(i, c, T):                # windows where start can occur and finish <= T
                v = m.NewBoolVar(f"b_{i}_{ci}_{w}")
                b[i, ci, w] = v; lits.append(v)
        m.AddExactlyOne(lits)
        m.Add(D[i] == sum(P.opts[i][ci].dur_worstcase_s * v for (ii, ci, w), v in b.items() if ii == i))
        # start lies in chosen window
        m.Add(S[i] >= sum(w * P.W * v for (ii, ci, w), v in b.items() if ii == i))
        m.Add(S[i] <= sum(((w + 1) * P.W - 1) * v for (ii, ci, w), v in b.items() if ii == i))
    for (p, i) in P.edges:
        m.Add(S[i] >= S[p] + D[p])
    makespan = m.NewIntVar(0, T, "M")
    for i in P.steps: m.Add(makespan >= S[i] + D[i])

    def total(f):  # f(i,c,w) -> float ; returns int linear expr
        return sum(int(round(SC * f(i, ci, w))) * v for (i, ci, w), v in b.items())
    G   = total(lambda i,ci,w: P.carbon_mean(i,ci,w))
    Grb = total(lambda i,ci,w: P.carbon_robust(i,ci,w, cons.robust_z))
    E   = total(lambda i,ci,w: P.opts[i][ci].energy_wh)
    C   = total(lambda i,ci,w: P.opts[i][ci].cost_usd)
    Qs  = total(lambda i,ci,w: P.omega[i] * P.opts[i][ci].quality)     # Σ ω q  (× SC)

    if cons.carbon_budget_g: m.Add(Grb <= int(SC * cons.carbon_budget_g))
    if cons.cost_budget_usd: m.Add(C   <= int(SC * cons.cost_budget_usd))
    m.Add(Qs >= int(SC * cons.quality_floor))
    # per-step quality floors already enforced by option filtering

    # objective: baseline-normalized J (7.8), integer-scaled
    obj = (wts.latency * SC * makespan / base.M
         + wts.carbon  * G   / base.G
         + wts.energy  * E   / base.E
         + wts.cost    * C   / base.C
         + wts.quality * (SC - Qs) / 0.10)
    m.Minimize(obj)   # NOTE: scale/round terms so all coefficients are ints; do this via helper
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = 8
    status = solver.Solve(m)
    # extract: chosen (ci, w) per step; S[i] value; totals; status OPTIMAL/FEASIBLE/INFEASIBLE
```
Implementation notes:
- Multiply weights/normalizers into integer coefficients per `(i,ci,w)` up front (build a dict `coef[i,ci,w]`), not by dividing IntVars. Makespan term coefficient is `int(SC * w_L / M0)`.
- With `elastic=True` add slack IntVars for deadline (`M ≤ T + sT` → but keep IntVar domain wide), carbon, quality, cost; add `BIG * slack` to objective; report nonzero slacks (7.13).
- Add symmetry breaking is unnecessary at this size (≤ 20 steps × ≤ 12 configs × ≤ 48 windows ≈ 11k booleans).
- Use `AddHint` with the greedy solution to speed convergence.
- **Do not** add a NoOverlap between steps (parallelism allowed). Optional stretch: per-site or per-model concurrency via `AddCumulative` with intervals `NewIntervalVar(S_i, D_i, S_i+D_i)` and demand 1, capacity = rate-limit slots.

### 8.7 `scheduler/planner.py`
```
plan(workflow, constraints, weights, solver="auto"):
  1. normalize omega; build options (8.2) using current profiles (learning-adjusted)
  2. fetch CI forecasts for all sites (8.1), horizon = deadline
  3. compute baselines (8.10) -> normalizers
  4. greedy plan (always, <50 ms). If solver in {auto,cpsat}: CP-SAT with greedy hint, 10 s limit.
  5. if infeasible: elastic solve -> status="relaxed" + relaxations list
  6. attach rationale strings (8.11), per-step slack/critical flags, totals, baselines, savings
  7. persist plan to SQLite
```
### 8.8 `scheduler/pareto.py`
Implements 7.12, running solves in a threadpool, streaming partial frontier results if requested. Each point stores its full `PlanResult` id so clicking a point on the chart loads that plan.

### 8.9 `learning/` and `scripts/calibrate.py`
- `telemetry.py`: table `step_runs(id, run_id, step_type, model, site, tokens_in, tokens_out, dur_s, verifier_score, accepted, escalated, teacher_agree, ts)`.
- `estimators.py`: implements 7.9 with `get_latency(step_type, model) -> (mu, sigma)`, `get_tokens_out(...)`, `get_accept(...)`, `get_quality(...)`. Falls back to registry priors. `profiles/*` must call these.
- `calibrate.py` (run once, ~10 min): for each step_type, run 10 sample prompts through each model; measure `ttft` and `tokens_per_s` (real); compute quality proxy = LLM-judge (large model, rubric 0–1) agreement of each model's output vs the large model's output; fit verifier calibration `π(s)`; write results into `registry/models.yaml` overrides file `registry/calibrated.yaml`. This makes the profiles **measured**, which is a big credibility win.
- `seed_telemetry.py`: inserts ~200 plausible rows so the learning loop chart has content even before real runs.

### 8.10 `receipt/baselines.py`
Compute totals for three counterfactual plans on the same workflow, using the same estimators:
- **naive** — every step: `large` model, default site (`gcp-mumbai`), start ASAP, no cascade. (Carbon receipt reference.)
- **fastest** — fastest config per step, ASAP.
- **smallest** — `small` model everywhere, no verification (shows carbon savings but quality collapse).
Receipt fields: `saved_carbon_g`, `saved_pct`, `saved_cost`, `latency_delta_s`, `quality_delta`, plus "equivalents" (km driven etc.) from `equivalents.yaml`. **Actual** numbers from the executed run (`StepRunResult`) vs **estimated** baseline; label them "actual vs modeled baseline".

### 8.11 `scheduler/explain.py` — rationale generator
Rule-based string per step, e.g.
- Critical: "On the critical path (0 s slack) → fastest config: large @ Mumbai, start now."
- Slack + shift: "412 s slack. Deferred 3 h to the 13:00 solar window in Mumbai (CI 610 → 430 g/kWh), saving 0.21 g."
- Downgrade: "Slack allowed medium instead of large: −0.6 Wh, −$0.002, quality 0.92 vs 0.95."
- Cascade: "Cascade small→large: 80% expected accept; expected energy −55% vs large."
Also produce a plan-level summary paragraph (3 lines) for the UI header.

### 8.12 `executor/replan.py` — receding horizon (MPC)
Triggers after each step completes: (a) |actual duration − predicted| / predicted > 0.25, (b) cascade escalated, (c) CI forecast refreshed and mean shifted > 15% for a site used by pending steps, (d) user pressed "Re-plan". Procedure: freeze finished steps; build sub-problem with remaining steps, `now`, remaining deadline `T_max − now`, remaining carbon budget `G_max − actual_carbon_so_far`; run `plan()` (greedy first, CP-SAT with 3 s limit); diff old vs new; emit `replanned` event with the diff so the UI can animate changed bars.

### 8.14 Learned quality predictor — `learning/features.py`, `learning/predictor.py`, `scheduler/prune.py`, `scripts/calibrate_predictor.py`
Implements 7.14. Flag: `USE_PREDICTOR=1` (default off until trained; the planner must work identically to before when off).

**Files**
- `registry/traits.yaml`: trait questions per step_type. Hand-written defaults (below) plus optional LLM-proposed extras. Human-editable.
- `registry/predictors/{model}.json`: trained artifacts as plain JSON (not pickle): `{model, head, feature_names, mean, scale, coef, intercept, n, cv_logloss, cv_baseline_logloss, cv_auc, trained_at, rho}`. Inference is pure numpy (`sigmoid(dot)`), no sklearn needed at runtime.
- `learning/features.py`: `featurize(step, rendered_prompt, client) -> FeatureVec` (LLM call for F, code for g, hash cache in SQLite). Also `MockFeaturizer` (deterministic bits from a hash of the text).
- `learning/predictor.py`: `train(model, head, rows) -> Artifact`, `predict(model, head, x) -> p`, `gate(artifact) -> bool`, `blend(p_hat, p_prior, n, K)`, `reliability_bins(rows, artifact, bins=10)`.
- `scheduler/prune.py`: fuzzy Pareto pruning (7.14); `profiles/options.py` calls it.
- `profiles/quality.py`: `get_quality(step, model)` and `get_p_accept(step, small_model)` use the predictor when `USE_PREDICTOR=1` and the gate passes, else priors/Beta.
- `executor/cascade.py`: computes `p̂` on the rendered prompt and applies the break-even skip rule.

**Default trait questions (registry/traits.yaml, ~10 per step_type; generic ones shared)**
1. Is the input longer than about 1000 tokens?
2. Does it contain numbers or require a calculation?
3. Does it require combining 3 or more separate sources or facts?
4. Does it have multiple simultaneous constraints or requirements?
5. Must the output follow a strict format (JSON, table, fixed template)?
6. Does it require multi-step reasoning rather than lookup or rewriting?
7. Does it need knowledge that is not present in the input?
8. Is the input ambiguous, contradictory, or noisy?
9. Does it use specialized or domain-specific terminology?
10. Does it require exact quotes or citations from the input?
Add 2–3 step_type-specific ones (e.g. for `code`: "touches more than one file?").

**`scripts/calibrate_predictor.py` (run once; ~15 to 30 min; cheap)**
1. Build `N = 40..60` varied inputs per step_type into `data/predictor_samples/{step_type}.jsonl`: reuse workflow prompts with different inputs/corpus chunks, plus LLM-generated variants (large model, "vary difficulty, length, number of constraints").
2. Optional: ask the large model to propose 10 extra traits from 10 sample inputs; append to `traits.yaml` for human review.
3. Label traits with the small model (one JSON call per input, cached).
4. Run each input through small, medium, large; compute verifier score and teacher agreement (large judge compares each output with the large output).
5. Train per (model, head), write artifacts, print a table: n, positive rate, CV log-loss vs base-rate, CV AUC, gate pass/fail.
6. `MOCK_LLM=1`: generate synthetic labels from a hidden ground-truth logistic model over the mock traits so tests and offline demos exercise the full pipeline.

**API**
- `GET /api/predictor` → per-model artifact summaries (n, cv metrics, gate status).
- `GET /api/predictor/{model}/calibration` → reliability bins + coefficients (for the UI).
- `POST /api/predictor/train` → runs training from stored telemetry/calibration rows.
- `POST /api/predictor/score` → body `{step, rendered_prompt?}` → traits + `p̂_accept`, `p̂_good` per model + break-even `p*`.

**UI ("Predictor" tab)**: coefficient bar chart (which traits make a step hard), reliability diagram, CV metrics with the gate badge, a "Use learned predictor" toggle in the constraint panel, and a live scoring box (paste a step prompt → traits + predicted pass chance per model). Add "+ learned predictor" as the last bar in the ablation waterfall (8.13): compare cascade cost with priors vs with predictor on the same held-out inputs.

**Tests**
1. Synthetic recovery: sample traits, labels from a known logistic ground truth, fit, and check the coefficient signs match and AUC > 0.7.
2. Gate: with n < 30 or random labels the artifact fails the gate and `get_p_accept` returns the prior.
3. Blend math and break-even: `p*` formula, skip-small when `p̂ < p*`, cascade chosen when `p̂ > p*`.
4. No leakage: CV metrics computed on held-out folds only.
5. Planner with `USE_PREDICTOR=0` returns exactly the same plan as before this feature (regression test).
6. Overhead accounting: characterization energy/cost appears in totals and receipt.

---

## 9. Executor (`executor/`)

### 9.1 Virtual clock
```python
class VirtualClock:
    def __init__(self, t0): self.t = t0
    def now(self): return self.t
    def advance_to(self, t): self.t = max(self.t, t)   # never goes backward
```
Event-driven: the runner keeps a priority queue of ready steps keyed by planned start time. Loop: pop the earliest; `clock.advance_to(max(planned_start, max(end of deps)))`; launch the step as an asyncio task; when it finishes, `end_s = start_s + real_duration_s` (real measured LLM latency, plus simulated RTT). Parallel steps launch together and their virtual end times are computed independently (`start + own duration`); the clock advances to the earliest finishing event next. Waiting for a green window costs zero real time.
Optional `mode=live` flag: really `asyncio.sleep` for waits ≤ 30 s (for a live "it's actually waiting" demo).

### 9.2 Runner
```
async def run(plan, workflow, on_event):
    outputs = {}; results = []
    while pending:
        ready = [s for s in pending if deps_done(s)]
        for s in sorted(ready, key=planned_start): schedule_task(s)
        ... await next completion, update clock, emit events, maybe replan
```
Rendering a step prompt: replace `{{upstream.<id>}}` with the upstream output text (truncate to model context) and `{{input.<key>}}` with workflow inputs.

### 9.3 `llm_clients.py`
```python
class LLMResult(BaseModel):
    text: str; tokens_in: int; tokens_out: int; latency_s: float
class LLMClient(Protocol):
    async def generate(self, prompt: str, max_tokens: int, system: str|None=None) -> LLMResult: ...
```
- `GeminiClient`: `from google import genai`; `client = genai.Client(api_key=...)`; `resp = await client.aio.models.generate_content(model=api_id, contents=prompt, config={"max_output_tokens": max_tokens, "temperature": 0.2})`; tokens from `resp.usage_metadata.prompt_token_count` / `candidates_token_count`. Wrap with timeout (30 s), retries with exponential backoff on 429/5xx, and a global `asyncio.Semaphore(4)` to respect free-tier limits.
- `OllamaClient`: `POST {OLLAMA_HOST}/api/generate {"model":..., "prompt":..., "stream":false, "options":{"num_predict":max_tokens}}`; tokens from `prompt_eval_count` / `eval_count`; latency from `total_duration` (ns).
- `MockClient`: deterministic text (hash of prompt), token counts = `len/4`, latency sampled from the model profile with seeded noise.
- Energy/carbon of an executed step are computed from **actual tokens and actual duration** with the same formulas (7.4) and the CI at the actual (virtual) start window.

### 9.4 `verifier.py`
- `schema`: validate JSON against `output_schema` → score 1.0/0.0.
- `code_exec`: run generated code/tests in a subprocess with 5 s timeout and no network → 1.0 / 0.0 (stretch).
- `llm_judge`: small model gets a rubric prompt ("Score 0–1 for factual grounding in the provided context, completeness, and format; reply with JSON {score, reason}") → parse; on parse failure score = 0.5.
- Heuristic add-ons: length within [0.3×, 3×] of expected; no refusal phrases; contains required keys.
- Final score = mean of applicable checks; `accepted = score ≥ τ`.

### 9.5 `cascade.py` + `voi.py`
```
async def run_cascade(step, option, ctx):
    small = await client(option.model).generate(...)
    v = await verify(step, small)
    if v.score >= tau_hi:  accept
    else:
        pi = calibrated_prob(v.score)
        if should_escalate(pi, q_L, deltas, weights, norms, now, LF_i): 
            large = await client(option.escalate_model).generate(...); return large, escalated=True
        else: return small, low_confidence=True
```
Log telemetry (score, accepted, escalated) for the learning loop.

### 9.6 Events (SSE)
`run_started, step_scheduled, step_started{step_id, option, sim_time}, step_finished{result}, verifier_result, escalated, replanned{diff}, budget_warning, run_finished{receipt}`. All events carry `sim_time_s` and `wall_time_ms`.

---

## 10. HTTP API (FastAPI) — all JSON, OpenAPI auto-generated

| Method & path | Purpose |
|---|---|
| `GET /api/models` , `GET /api/sites` | registries (with source notes) |
| `GET /api/carbon/forecast?zones=IN-SO,FI&horizon_s=86400&window_s=1800` | CI curves (mean, sigma, source) |
| `POST /api/workflows/validate` | body `Workflow` → validation errors/warnings, topological levels |
| `POST /api/plan` | body `{workflow, constraints, weights|preset, solver}` → `PlanResult` |
| `POST /api/pareto` | same body → `{points: PlanResult[]}` (or SSE stream) |
| `GET /api/plan/{id}` | fetch stored plan |
| `POST /api/runs` | body `{plan_id, mode: "virtual"|"live"}` → `{run_id}` |
| `GET /api/runs/{id}/events` | **SSE** stream of events (9.6) |
| `GET /api/runs/{id}` | run summary + `StepRunResult[]` |
| `POST /api/runs/{id}/replan` | manual re-plan |
| `GET /api/runs/{id}/receipt` | Carbon Receipt + ablation data |
| `GET /api/telemetry/stats?step_type=&model=` | learned estimates vs priors (for learning chart) |
| `POST /api/calibrate` | kicks off calibration job (dev only) |
| `GET /api/health` | key checks: LLM reachable? carbon source? mock mode? |

CORS open for `localhost:5173`. Return RFC-7807-style errors `{title, detail}`. Request-size limit 1 MB.

---

## 11. Frontend spec

**Design language:** clean, dark-mode-friendly, green accent; big numbers; every chart labeled with units and an "Estimates" badge.

**Page 1 — Builder**
- Left: `DagCanvas` (React Flow). Node = step (name, type chip, importance). Add/delete node, connect edges, edit prompt in a side drawer. Toggle "JSON" tab to edit raw workflow JSON (two-way sync).
- Buttons: "Load example" (dropdown of `/workflows/*.json`).
- Right: `ConstraintPanel`: deadline (slider + human units), carbon budget (g, optional), cost cap, quality floor slider, toggles (deferral, cascade), site multiselect, weight preset chips (Green / Fast / Balanced / Cheap) + advanced sliders.
- CTA: **Plan it**.

**Page 2 — Plan**
1. Header summary (3 lines from `explain.py`) + status badge (`optimal / feasible / relaxed`) + solver + solve time.
2. **Gantt**: rows = steps (critical ones outlined red), x = simulated time; bar color = site; bar pattern = cascade; hatched ghost = worst-case tail; a **CarbonStrip** heatmap under the axis per site (green→red by CI) with a vertical marker at solar peak; dashed line = original ASAP position for deferred steps (shows shift).
3. **Totals table**: Plan vs Naive vs Fastest vs Smallest for latency, cost, energy, carbon, quality; delta chips.
4. **Pareto chart** (Recharts scatter): x = latency, y = carbon, point size = cost, color = quality; slider "How green?" snaps to nearest frontier point and re-renders Gantt; hover tooltip shows the plan summary; current constraint box drawn on chart.
5. If `relaxed`: red panel "Can't meet all constraints" with the single-axis fixes ("Extend deadline to 22 min" **or** "Accept quality 0.88").
6. `StepInspector` drawer: options considered (table of top options with J score), slack, chosen rationale, CI curve for chosen site with the chosen window highlighted.

**Page 3 — Run (live)**
- Same Gantt filling in with actual bars; live log (`LiveLog`) from SSE; step cards show tokens, verifier score, escalation badge, actual vs predicted duration; "replanned" flash with diff; running totals vs budget gauges; simulated clock display.

**Page 4 — Receipt**
- `ReceiptCard`: big "You saved X g CO₂e (Y%)" vs naive, cost saved, latency delta, quality delta, equivalents line (from `equivalents.yaml`, labeled approximate). Shareable PNG button (html-to-image).
- `AblationBar`: stacked/waterfall bars "Naive → +model routing → +cascade → +site choice → +time-shift → +re-plan" (each computed by re-planning with that feature enabled cumulatively; see 8.13).
- Learning chart: predicted vs actual latency over runs (from telemetry).

### 8.13 Ablation computation (`receipt/ablation.py`)
Plan the same workflow five times with feature flags cumulatively enabled: (1) naive; (2) + model tiering only (single sites, no cascade, no deferral); (3) + cascade; (4) + site selection; (5) + deferral. Re-planning gain is measured on a run with injected latency noise (compare with/without replan). Return carbon for each stage → waterfall.

---

## 12. Sample workflows (put in `/workflows`)

`market_brief.json` (main demo)
```json
{
  "id": "market_brief", "name": "Market research brief",
  "inputs": {"topic": "Electric two-wheelers in India"},
  "steps": [
    {"id":"plan","name":"Plan research","step_type":"planning","omega":0.10,
     "prompt_template":"Break down a market brief on {{input.topic}} into 3 focused research questions. Return JSON list.","depends_on":[]},
    {"id":"r1","name":"Extract: market size","step_type":"extraction","omega":0.10,
     "prompt_template":"From the corpus below answer: question 1 of {{upstream.plan}}.\n\n<corpus>{{corpus.market}}</corpus>","depends_on":["plan"]},
    {"id":"r2","name":"Extract: competitors","step_type":"extraction","omega":0.10,
     "prompt_template":"From the corpus below answer: question 2 of {{upstream.plan}}.\n\n<corpus>{{corpus.competitors}}</corpus>","depends_on":["plan"]},
    {"id":"r3","name":"Extract: policy","step_type":"extraction","omega":0.10,
     "prompt_template":"From the corpus below answer: question 3 of {{upstream.plan}}.\n\n<corpus>{{corpus.policy}}</corpus>","depends_on":["plan"]},
    {"id":"s1","name":"Summarize market","step_type":"summarization","omega":0.05,"prompt_template":"Summarize: {{upstream.r1}}","depends_on":["r1"]},
    {"id":"s2","name":"Summarize competitors","step_type":"summarization","omega":0.05,"prompt_template":"Summarize: {{upstream.r2}}","depends_on":["r2"]},
    {"id":"s3","name":"Summarize policy","step_type":"summarization","omega":0.05,"prompt_template":"Summarize: {{upstream.r3}}","depends_on":["r3"]},
    {"id":"syn","name":"Synthesize insights","step_type":"reasoning","omega":0.25,"min_quality":0.85,
     "prompt_template":"Using {{upstream.s1}} {{upstream.s2}} {{upstream.s3}} write 5 non-obvious strategic insights with evidence.","depends_on":["s1","s2","s3"]},
    {"id":"chk","name":"Fact-check","step_type":"verification","omega":0.10,
     "prompt_template":"Check each insight in {{upstream.syn}} against the summaries; flag unsupported claims.","depends_on":["syn"]},
    {"id":"fmt","name":"Format brief","step_type":"formatting","omega":0.10,
     "prompt_template":"Format {{upstream.syn}} and {{upstream.chk}} as a 1-page brief in markdown.","depends_on":["chk"]}
  ]
}
```
(`{{corpus.*}}` = files in `workflows/data/` loaded by the runner; add small realistic text files.)

`nightly_report.json`: same DAG shape with `deadline` ≈ 8 h to demo **deferral** (plan shifts slack steps into midday solar window / cleaner site).
`code_review.json`: parse diff → 3 parallel file reviewers → merge → severity rank (uses `code`/`reasoning` types).

Demo scenarios to script (Section 15): (A) 10-min deadline → almost no deferral, carbon savings mainly from tiering + cascade; (B) 6-h deadline → deferral kicks in, big carbon drop; (C) 5 g budget with 2-min deadline → infeasible → relaxation suggestions.

---

## 13. Tests (`backend/tests/`, all with `MOCK_LLM=1`, seeded)

1. `test_graph.py`: cycle detection, missing dependency, topo order.
2. `test_cpm.py`: known 6-node DAG with hand-computed ES/EF/LS/LF/slack; critical path correct; negative slack → infeasible.
3. `test_models.py`: energy/cost/latency formulas vs hand calculations (write expected values inline); cascade expectations (7.7) for p ∈ {0, 0.5, 1}.
4. `test_carbon_synthetic.py`: solar dip → CI at 12:00 local < CI at 03:00 local for IN-SO; sigma grows with horizon; deterministic with seed.
5. `test_greedy.py`: critical steps never get slower options than fastest; plan never violates precedence or deadline; deferral picks a lower-CI window when slack allows.
6. `test_cpsat.py`: never worse (J) than greedy on 20 random DAGs; respects all constraints; infeasible case returns relaxations; single-step trivial case chooses argmin.
7. `test_pareto.py`: returned set is non-dominated; monotone tradeoff (more deadline → carbon non-increasing).
8. `test_voi.py`: escalate when quality gain is large and slack allows; refuse when it would break `LF`.
9. `test_learning.py`: EWMA converges; Beta posterior moves toward observed acceptance; regression fallback when n<8.
10. `test_receipt.py`: savings math; baselines computed identically to plan estimators.
11. `test_api.py`: `POST /api/plan` on `market_brief.json` returns valid `PlanResult` in < 15 s; SSE stream emits events in order and ends with `run_finished`.
12. **Property test (hypothesis):** for random valid workflows/constraints, if status ≠ infeasible then every hard constraint holds in the returned totals.

Frontend: Playwright smoke test (load example → plan → see Gantt → run → see receipt).

---

## 14. Build plan (phases, acceptance criteria, agent prompts)

Assume ~30 hours of wall-clock; scale down by cutting stretch items (marked ★). Each phase ends with passing tests and a commit. **Contract-first:** Phase 0 freezes `schemas.py` and a fixture `PlanResult` JSON so frontend can start immediately.

### Phase 0 — Scaffold & contracts (1.5 h)
Build: repo layout, `pyproject`, FastAPI hello + `/api/health`, `schemas.py` (Section 5), registry YAML loaders, `MOCK_LLM`, Makefile, Vite app, OpenAPI → TS type generation, `fixtures/plan_market_brief.json` (hand-written plausible `PlanResult`).
Done when: `make dev` serves both apps; frontend renders fixture JSON as a table; `pytest` runs (even with 1 test).
> Prompt: "Read AGENTS.md fully. Execute Phase 0 only. Create the layout in Section 3, implement Section 5 schemas exactly, YAML loaders for Section 6, and a hand-written fixture PlanResult. Do not implement scheduling yet. Report what you created and any DECISION comments."

### Phase 1 — Profiles + carbon (3 h)
Build: `carbon/synthetic.py` (7.10), `provider.py`, `electricitymaps.py`, `ukgrid.py`, cache, snapshot script; `profiles/latency|energy|cost|quality|options.py`; `GET /api/carbon/forecast`, `/api/models`, `/api/sites`.
Done when: tests 3–4 pass; forecast endpoint returns curves for 5 zones; option builder yields ≤12 pruned options per step for `market_brief`.
> Prompt: "Execute Phase 1 per AGENTS.md Sections 6, 7.2–7.7, 7.10, 8.1–8.2. Write tests test_models.py and test_carbon_synthetic.py first, then implementation."

### Phase 2 — DAG, CPM, greedy, baselines, receipt (3 h)
Build: `dag/graph.py`, `dag/cpm.py`, `scheduler/objective.py`, `greedy.py`, `explain.py` (basic), `receipt/baselines.py`, `planner.py` (greedy only), `POST /api/plan`.
Done when: tests 1, 2, 5, 10 pass; `POST /api/plan` returns a valid `PlanResult` with baselines and rationales for `market_brief`.
> Prompt: "Execute Phase 2 per AGENTS.md Sections 7.8, 7.11, 8.3–8.5, 8.10–8.11. TDD. The planner facade must already accept solver='greedy'."

### Phase 3 — Executor, LLMs, cascade (4 h)
Build: `clock.py`, `runner.py`, `llm_clients.py` (Gemini, Ollama ★, Mock), `verifier.py`, `cascade.py`, `voi.py`, `events.py`, telemetry table, `POST /api/runs`, SSE, `GET /api/runs/{id}`.
Done when: with `MOCK_LLM=1` a full `market_brief` run completes, emits ordered events, results persisted; with a real key one real run works end-to-end; tests 8, 11 pass.
> Prompt: "Execute Phase 3 per AGENTS.md Sections 7.7, 9.1–9.6. Virtual clock semantics are essential: no real sleeping unless mode=live. Provide MockClient first, then GeminiClient."

### Phase 4 — CP-SAT, Pareto, relaxations (4 h)
Build: `cpsat.py`, `relax.py`, `pareto.py`, planner `solver=auto`, `POST /api/pareto`.
Done when: tests 6, 7, 12 pass; CP-SAT ≤ greedy on J for all random cases; scenario C returns relaxations.
> Prompt: "Execute Phase 4 per AGENTS.md Sections 7.12, 7.13, 8.6–8.8. Implement the joint boolean b[i,c,w] model exactly as specified; pass the greedy plan as a hint."

### Phase 5 — Frontend (6 h, parallel with 3–4 using the fixture; switch to live API when ready)
Build: Section 11 pages/components. Order: ConstraintPanel → Gantt+CarbonStrip → Totals table → Pareto+slider → DagCanvas → Run page (SSE) → Receipt.
Done when: Playwright smoke test passes; the demo flow works with real backend in mock mode.
> Prompt: "Execute Phase 5 per AGENTS.md Section 11 using the generated TS types. Start from fixtures/plan_market_brief.json; wire to the live API afterwards. Gantt must be custom SVG."

### Phase 6 — Learning loop, replanning, calibration (3 h)
Build: `estimators.py`, `calibrate.py`, `seed_telemetry.py`, `replan.py`, learning chart, ablation.
Done when: test 9 passes; after N runs predicted latency error shrinks (chart); replan event appears when noise injected; ablation waterfall renders.
> Prompt: "Execute Phase 6 per AGENTS.md Sections 7.9, 8.9, 8.12, 8.13."

### Phase 6b — Learned quality predictor (3 h, after Phase 6; skip if short on time)
Build: `learning/features.py`, `learning/predictor.py`, `scheduler/prune.py`, `scripts/calibrate_predictor.py`, `registry/traits.yaml`, predictor API, UI tab, ablation bar (Sections 7.14, 8.14).
Done when: the 6 predictor tests pass; `USE_PREDICTOR=0` gives identical plans to before; with the predictor on (mock), cascade skips hard steps and cost drops on the held-out set; UI shows coefficients and a reliability diagram.
> Prompt: "Execute Phase 6b per AGENTS.md Sections 7.14 and 8.14. Keep USE_PREDICTOR off by default and prove with a regression test that behavior is unchanged when off."

### Phase 7 — Polish & demo (3 h)
Build: rationale text polish, empty/error states, "Estimates" tooltips, receipt PNG export, README with architecture diagram (Mermaid), record fallback demo video, snapshot of carbon data, seed DB.
Done when: three demo scenarios run reliably 5× in a row in mock mode and once on live keys.

### ★ Stretch (only if ahead)
- SDK: `@verdant.step(...)` decorator / LangGraph adapter so any existing agent can be scheduled ("drop-in").
- Concurrency/rate-limit constraints via CP-SAT `AddCumulative`.
- Cross-site cascades + data-transfer cost between sites.
- Thompson-sampling exploration mode.
- Real Vertex AI regional endpoints behind the `Site` interface.
- Water-use metric alongside carbon.

### Team split (4 people)
A — backend core (Phases 1, 2, 4) · B — executor/LLM/learning (Phases 3, 6) · C — frontend (Phase 5) · D — data, calibration, pitch, demo, tests (carbon snapshot, calibrate, Phase 7).

---

## 15. Demo script (3 minutes) & pitch

1. **Hook (20 s):** "Agents make dozens of LLM calls per task. Nobody decides *where, when, and with which model* each one runs. We built the scheduler that does."
2. **Builder (20 s):** load Market Brief DAG, set constraints (10 min, quality ≥ 0.9), click Plan.
3. **Plan (50 s):** Gantt with critical path red; explain 2 rationales; show Totals vs Naive; drag the Pareto slider from "fast" to "green" and watch the plan change.
4. **Deferral wow (30 s):** extend deadline to 6 h → steps slide into the solar window/cleaner site; carbon drops sharply.
5. **Run (40 s):** live execution with real Gemini calls; a cascade escalates; a re-plan triggers; budget gauges stay green.
6. **Receipt (20 s):** "Saved X g (Y%) vs naive at +Z s latency and the same quality," plus the ablation waterfall.
7. **Honesty (10 s):** "Energy per token and grid intensity are modeled estimates from public data; model calls are real. The scheduler is model-agnostic — swap in measured numbers and it improves."

Judging map: **Innovation** (CPM slack + VoI cascade + MPC + chance constraints), **Technical depth** (CP-SAT vs greedy ablation, Pareto), **Impact** (India grid heterogeneity; agents at scale), **Feasibility** (real calls, mock fallback, tests), **UX** (receipt, slider, explanations).

---

## 16. Risks & fallbacks

| Risk | Fallback |
|---|---|
| Gemini rate limits / outage | semaphore + backoff; `MOCK_LLM=1`; cached outputs for the demo workflow |
| Electricity Maps quota/forecast unavailable | `carbon_snapshot.json`, then synthetic (badge shows source) |
| CP-SAT too slow | greedy plan is always returned first; CP-SAT time limit 10 s; prune options to top-8 |
| Ollama not available on demo machine | drop `local` site (it's optional); everything else works |
| Verifier noisy | combine programmatic checks + judge; calibration in `calibrate.py`; VoI rule uses calibrated `π(s)` |
| Judges question realism of "sites" | Explain it's accounting over real model calls; interface ready for regional endpoints; show calibration data as measured |

---

## 17. Definition of done (whole project)
- `make dev` starts everything; `make test` passes.
- All three demo scenarios work in mock mode and with live keys.
- Plan for `market_brief` returns in < 3 s (greedy) / < 12 s (CP-SAT).
- Every displayed metric has units and an estimate/measured label.
- README includes architecture diagram, setup, env vars, and the honesty note.
