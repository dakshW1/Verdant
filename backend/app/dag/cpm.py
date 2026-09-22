"""
Critical Path Method (Phase 2).

Computes ES (Earliest Start), EF (Earliest Finish),
LS (Latest Start), LF (Latest Finish), and Slack for each step.
Uses the worst-case durations for deadline safety analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CPMNode:
    step_id: str
    dur: int          # duration in seconds (worst-case)
    preds: list[str]  # predecessor step IDs
    es: int = 0       # Earliest Start
    ef: int = 0       # Earliest Finish
    ls: int = 0       # Latest Start
    lf: int = 0       # Latest Finish
    slack: int = 0    # Total float = LS - ES
    is_critical: bool = False


def compute_cpm(
    topo_order: list[str],
    durations: dict[str, int],          # step_id → duration_s (worst-case)
    predecessors: dict[str, list[str]], # step_id → [pred_step_ids]
    deadline_s: int,
) -> dict[str, CPMNode]:
    """
    Run the forward+backward pass of CPM.

    Args:
        topo_order: Topologically sorted step IDs (sources first).
        durations: Mapping of step_id → expected duration in seconds.
        predecessors: Mapping of step_id → list of predecessor step IDs.
        deadline_s: Project deadline (seconds from t0).

    Returns:
        Dict of step_id → CPMNode with ES/EF/LS/LF/slack populated.
    """
    nodes: dict[str, CPMNode] = {
        sid: CPMNode(
            step_id=sid,
            dur=durations.get(sid, 1),
            preds=predecessors.get(sid, []),
        )
        for sid in topo_order
    }

    # ── Forward pass (compute ES, EF) ────────────────────────────────────
    for sid in topo_order:
        node = nodes[sid]
        if not node.preds:
            node.es = 0
        else:
            node.es = max(nodes[p].ef for p in node.preds if p in nodes)
        node.ef = node.es + node.dur

    # ── Backward pass (compute LS, LF, slack) ────────────────────────────
    # LF of the last step(s) = deadline_s (or their EF if over deadline)
    project_end = max((n.ef for n in nodes.values()), default=0)
    lf_horizon = max(deadline_s, project_end)

    successors: dict[str, list[str]] = {sid: [] for sid in topo_order}
    for sid in topo_order:
        for pred in nodes[sid].preds:
            if pred in successors:
                successors[pred].append(sid)

    for sid in reversed(topo_order):
        node = nodes[sid]
        succs = successors.get(sid, [])
        if not succs:
            node.lf = lf_horizon
        else:
            node.lf = min(nodes[s].ls for s in succs if s in nodes)
        node.ls = node.lf - node.dur
        node.slack = node.ls - node.es
        node.is_critical = node.slack <= 0

    return nodes
