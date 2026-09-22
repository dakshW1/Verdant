"""
Verdant backend — all Pydantic v2 schemas (Section 5 of AGENTS.md).
Units: time=seconds(int), energy=Wh(float), carbon=gCO2e(float),
       carbon_intensity=gCO2e/kWh(float), cost=USD(float), quality=float[0,1].
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enumerations / type aliases
# ---------------------------------------------------------------------------

StepType = Literal[
    "planning",
    "extraction",
    "summarization",
    "reasoning",
    "verification",
    "formatting",
    "code",
]

SolverType = Literal["greedy", "cpsat", "auto"]
PlanStatus = Literal["optimal", "feasible", "relaxed", "infeasible"]
RunMode = Literal["virtual", "live"]
CarbonSource = Literal["live", "snapshot", "synthetic"]


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------


class Step(BaseModel):
    id: str
    name: str
    step_type: StepType
    prompt_template: str  # may contain {{upstream.<step_id>}} and {{input.<key>}}
    depends_on: list[str] = []
    omega: float = Field(1.0, ge=0)  # importance; normalized so sum=1 at plan time
    min_quality: float = Field(0.0, ge=0.0, le=1.0)  # per-step quality floor
    est_tokens_in: Optional[int] = None  # override; else estimated from step_type prior
    est_tokens_out: Optional[int] = None
    max_tokens_out: int = 800
    release_s: int = 0  # earliest start (seconds from t0)
    deadline_s: Optional[int] = None  # per-step deadline
    cascade_allowed: bool = True
    allowed_sites: Optional[list[str]] = None
    verifier: Optional[Literal["schema", "code_exec", "llm_judge", "none"]] = "llm_judge"
    output_schema: Optional[dict[str, Any]] = None  # for "schema" verifier


class Workflow(BaseModel):
    id: str
    name: str
    inputs: dict[str, str] = {}
    steps: list[Step]


class Constraints(BaseModel):
    deadline_s: int = 600
    carbon_budget_g: Optional[float] = None  # gCO2e
    cost_budget_usd: Optional[float] = None
    quality_floor: float = Field(0.85, ge=0.0, le=1.0)
    robust_z: float = 1.28  # 0=mean carbon; 1.28≈90% confidence
    start_time_iso: Optional[str] = None  # default now (sim)
    allow_deferral: bool = True
    allow_cascade: bool = True
    allowed_sites: Optional[list[str]] = None


class Weights(BaseModel):
    """Optimization objective weights; normalized to sum=1 by planner."""

    latency: float = Field(0.2, ge=0)
    cost: float = Field(0.1, ge=0)
    energy: float = Field(0.1, ge=0)
    carbon: float = Field(0.4, ge=0)
    quality: float = Field(0.2, ge=0)


# ---------------------------------------------------------------------------
# Config options (one row per feasible (model, site, mode) combination per step)
# ---------------------------------------------------------------------------


class ConfigOption(BaseModel):
    step_id: str
    model: str  # registry model alias (e.g. "small", "medium", "large")
    site: str  # registry site id
    mode: Literal["single", "cascade"]
    escalate_model: Optional[str] = None  # used when mode="cascade"
    verifier_model: Optional[str] = None
    dur_expected_s: int  # expected duration (seconds)
    dur_worstcase_s: int  # worst-case duration (seconds)
    energy_wh: float  # expected energy (Wh)
    energy_wh_worst: float  # worst-case energy (Wh)
    cost_usd: float  # expected cost (USD)
    quality: float = Field(..., ge=0.0, le=1.0)  # expected quality [0,1]
    p_accept: Optional[float] = None  # cascade: P(small model accepted)
    tokens_in: int
    tokens_out: int


# ---------------------------------------------------------------------------
# Plan structures
# ---------------------------------------------------------------------------


class StepPlan(BaseModel):
    step_id: str
    option: ConfigOption
    start_s: int  # planned start (seconds from t0)
    slack_s: int  # CPM slack (seconds)
    is_critical: bool
    carbon_g_expected: float  # gCO2e
    carbon_g_robust: float  # gCO2e (chance-constrained at robust_z)
    ci_g_per_kwh: float  # carbon intensity at chosen site/window (gCO2e/kWh)
    rationale: str  # human-readable explanation


class Totals(BaseModel):
    makespan_s: int  # end time of last step (seconds)
    cost_usd: float
    energy_wh: float
    carbon_g: float
    carbon_g_robust: float
    quality: float  # weighted average quality


class PlanResult(BaseModel):
    plan_id: str
    status: PlanStatus
    steps: list[StepPlan]
    totals: Totals
    baselines: dict[str, Totals]  # keys: "naive", "fastest", "smallest"
    relaxations: list[dict[str, Any]] = []  # [{constraint, requested, needed}]
    pareto: list[Totals] = []  # Pareto frontier points
    solver: Literal["greedy", "cpsat"]
    solve_ms: int


# ---------------------------------------------------------------------------
# Execution / run structures
# ---------------------------------------------------------------------------


class StepRunResult(BaseModel):
    step_id: str
    option_used: ConfigOption
    escalated: bool
    start_s: int  # actual start (virtual seconds from t0)
    end_s: int  # actual end
    tokens_in: int
    tokens_out: int
    energy_wh: float
    carbon_g: float
    cost_usd: float
    verifier_score: Optional[float]
    output_text: str
    model_used: str = ""  # exact real API model id that produced the final output (e.g. "gemini-3.5-flash-lite")
    verifier_note: Optional[str] = None  # set when the judge's response couldn't be parsed cleanly


class RunSummary(BaseModel):
    run_id: str
    plan_id: str
    status: Literal["running", "completed", "failed"]
    mode: RunMode
    steps: list[StepRunResult] = []
    totals: Optional[Totals] = None
    final_output: Optional[str] = None



# ---------------------------------------------------------------------------
# Carbon forecast
# ---------------------------------------------------------------------------


class CIForecast(BaseModel):
    zone: str
    window_s: int  # seconds per window
    start_ts: int  # Unix timestamp of first window
    mean: list[float]  # gCO2e/kWh per window
    sigma: list[float]  # uncertainty std dev per window
    source: CarbonSource


# ---------------------------------------------------------------------------
# API request/response wrappers
# ---------------------------------------------------------------------------


class PlanRequest(BaseModel):
    workflow: Workflow
    constraints: Constraints = Constraints()
    weights: Optional[Weights] = None
    preset: Optional[str] = None  # "green" | "fast" | "balanced" | "cheap"
    solver: SolverType = "auto"


class RunRequest(BaseModel):
    plan_id: str
    mode: RunMode = "virtual"


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    topo_levels: list[list[str]] = []  # topological levels for display


class HealthCheck(BaseModel):
    status: str
    mock_llm: bool
    carbon_source: CarbonSource
    llm_reachable: bool
    db_ok: bool
    models_ok: list[str]
    models_missing: list[str]


# ---------------------------------------------------------------------------
# Telemetry / learning
# ---------------------------------------------------------------------------


class TelemetryStats(BaseModel):
    step_type: str
    model: str
    n_runs: int
    latency_mu_s: float
    latency_sigma_s: float
    tokens_out_mu: float
    p_accept_mean: float  # Beta posterior mean
    quality_mean: float  # Beta posterior mean
    source: Literal["prior", "learned"]


# ---------------------------------------------------------------------------
# Receipt / ablation
# ---------------------------------------------------------------------------


class ReceiptEquivalent(BaseModel):
    label: str  # e.g. "km driven"
    value: float
    note: str = "rough equivalent"


class CarbonReceipt(BaseModel):
    run_id: str
    plan_id: str
    actual: Totals
    naive_baseline: Totals
    saved_carbon_g: float
    saved_pct: float
    saved_cost_usd: float
    latency_delta_s: int  # positive = verdant is slower
    quality_delta: float  # positive = verdant is better
    equivalents: list[ReceiptEquivalent]
    ablation_stages: list[dict[str, Any]]  # waterfall data
    estimates_badge: str = (
        "Energy-per-token and grid-intensity values are modeled estimates "
        "from public sources, not direct measurements."
    )
