from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .knowledge import Compatible


@dataclass(frozen=True)
class PlanningAction:
    operation_id: str
    machine_id: str
    start_minute: float
    end_minute: float
    ready_minute: float
    preconditions: tuple[str, ...]
    effects: tuple[str, ...]


def _find_gap(machine: dict, ready: float, duration: float, tail: float, blackouts: list[tuple[float, float]]) -> float | None:
    if not machine.get("is_available", True):
        return None
    available_from = float(machine.get("available_from_minute", 0.0))
    start = max(ready, tail, available_from)
    for begin, end in sorted(blackouts):
        if start + duration <= begin + 1e-9:
            break
        if start < end - 1e-9:
            start = end
    until = machine.get("available_until_minute")
    if until is not None and start + duration > float(until) + 1e-9:
        return None
    if start < available_from - 1e-9:
        return None
    return start


def applicable_actions(
    jobs: dict[str, dict],
    machines: dict[str, dict],
    operations: list[dict],
    placements: dict[str, dict],
    predecessor: dict[str, str | None],
    machine_blackouts: dict[str, list[tuple[float, float]]],
    risky_machines: set[str] | None = None,
) -> list[PlanningAction]:
    """Return only actions whose logical preconditions hold in this state."""
    actions: list[PlanningAction] = []
    risky_machines = risky_machines or set()
    placed_ids = set(placements)
    machine_tails = {
        machine_id: max((float(row["end_minute"]) for row in placements.values() if row["machine_id"] == machine_id), default=float(machine.get("available_from_minute", 0.0)))
        for machine_id, machine in machines.items()
    }
    completed = {operation_id: float(row["end_minute"]) for operation_id, row in placements.items()}
    for operation in sorted(operations, key=lambda value: (value["sequence"], value["id"].casefold())):
        operation_id = operation["id"]
        if operation_id in placed_ids:
            continue
        pred_id = predecessor.get(operation_id)
        if pred_id and pred_id not in completed:
            continue
        job = jobs[operation["job_id"]]
        predecessor_end = completed[pred_id] if pred_id is not None and pred_id in completed else float(job["release_minute"])
        ready = max(float(job["release_minute"]), predecessor_end)
        candidates: list[tuple[str, float, float]] = []
        for machine_id in sorted(set(operation["eligible_machine_ids"])):
            machine = machines.get(machine_id)
            if machine is None or not Compatible(operation, machine):
                continue
            duration = float(operation["processing_time_minutes"]) + float(operation.get("setup_time_minutes", 0)) + float(machine.get("setup_time_minutes", 0))
            start = _find_gap(machine, ready, duration, machine_tails[machine_id], machine_blackouts.get(machine_id, []))
            if start is not None:
                candidates.append((machine_id, start, duration))
        if risky_machines and any(machine_id not in risky_machines for machine_id, _, _ in candidates):
            candidates = [candidate for candidate in candidates if candidate[0] not in risky_machines]
        for machine_id, start, duration in candidates:
            end = start + duration
            pred_fact = f"Finished({pred_id}, {completed[pred_id]:.4f})" if pred_id else f"Released({job['id']}, {job['release_minute']:.4f})"
            preconditions = (
                pred_fact,
                f"Compatible({operation_id}, {machine_id})",
                f"Available({machine_id}, {start:.4f})",
                f"NotScheduled({operation_id})",
            )
            effects = (
                f"Finished({operation_id}, {end:.4f})",
                f"Occupied({machine_id}, {start:.4f}, {end:.4f})",
                f"Progress({job['id']}, {operation['sequence']})",
            )
            actions.append(PlanningAction(operation_id, machine_id, start, end, ready, preconditions, effects))
    return sorted(actions, key=lambda action: (action.start_minute, action.operation_id.casefold(), action.machine_id.casefold()))


def apply_action(placements: dict[str, dict[str, Any]], action: PlanningAction) -> dict[str, dict[str, Any]]:
    """Apply an action's effects to the immutable parent state."""
    next_state = dict(placements)
    next_state[action.operation_id] = {
        "machine_id": action.machine_id,
        "start_minute": round(action.start_minute, 6),
        "end_minute": round(action.end_minute, 6),
        "ready_minute": round(action.ready_minute, 6),
    }
    return next_state
