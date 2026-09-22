"""
DAG validation stub — Phase 2 will flesh this out fully.
For Phase 0: basic structure check so /api/workflows/validate works.
"""
from __future__ import annotations

from app.schemas import ValidationResult, Workflow


def validate_dag(workflow: Workflow) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    step_ids = {s.id for s in workflow.steps}
    if not step_ids:
        errors.append("Workflow must have at least one step.")

    for step in workflow.steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                errors.append(f"Step '{step.id}' depends on unknown step '{dep}'.")

    # Basic cycle detection (Kahn's algorithm)
    from collections import deque

    in_degree = {s.id: 0 for s in workflow.steps}
    adj: dict[str, list[str]] = {s.id: [] for s in workflow.steps}
    for step in workflow.steps:
        for dep in step.depends_on:
            if dep in adj:
                adj[dep].append(step.id)
                in_degree[step.id] += 1

    queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
    topo_levels: list[list[str]] = []
    visited = 0

    while queue:
        level = list(queue)
        topo_levels.append(level)
        next_queue: list[str] = []
        for node in level:
            queue.popleft()
            visited += 1
            for succ in adj.get(node, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    next_queue.append(succ)
        queue = deque(next_queue)

    if visited < len(workflow.steps):
        errors.append("Workflow contains a cycle — DAG must be acyclic.")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        topo_levels=topo_levels,
    )
