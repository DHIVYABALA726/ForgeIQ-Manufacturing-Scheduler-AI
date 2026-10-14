from __future__ import annotations

from collections import defaultdict
from datetime import timedelta, timezone
from heapq import heappop, heappush
from itertools import count
from time import perf_counter
from typing import Any

from .planning import PlanningAction, applicable_actions, apply_action
from .validation import as_utc


SEARCH_ALGORITHMS = {
    "A* Search": "astar",
    "Uniform Cost Search": "ucs",
    "Greedy Best-First": "greedy",
    "Breadth-First Search": "bfs",
    "Depth-First Search": "dfs",
}
DEFAULT_LIMITS = {"max_expansions": 2500, "max_seconds": 2.0}
DEFAULT_WEIGHTS = {"makespan": 1.0, "total_tardiness": 1.0, "idle_time": 0.0, "setup_time": 0.0, "machine_risk": 0.0}


def _blackout_overlap(start: float, end: float, windows: list[tuple[float, float]]) -> float:
    intervals = []
    for begin, finish in sorted(windows):
        left, right = max(start, begin), min(end, finish)
        if right <= left:
            continue
        if intervals and left <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], right)
        else:
            intervals.append([left, right])
    return sum(right - left for left, right in intervals)


def _state_key(placements: dict[str, dict]) -> tuple[tuple[str, str, int, int], ...]:
    return tuple(sorted((op_id, row["machine_id"], round(float(row["start_minute"]) * 1_000_000), round(float(row["end_minute"]) * 1_000_000)) for op_id, row in placements.items()))


def _cost(
    placements: dict[str, dict], jobs: dict[str, dict], machines: dict[str, dict], operations_by_id: dict[str, dict],
    ops_by_job: dict[str, list[dict]], blackouts: dict[str, list[tuple[float, float]]], risky_machines: set[str], weights: dict[str, float],
) -> float:
    if not placements:
        return 0.0
    makespan = max(float(row["end_minute"]) for row in placements.values())
    completion: dict[str, float] = {}
    for job_id, items in ops_by_job.items():
        if all(operation["id"] in placements for operation in items):
            completion[job_id] = max(float(placements[operation["id"]]["end_minute"]) for operation in items)
    tardiness = sum(max(0.0, completion[job_id] - float(jobs[job_id]["due_minute"])) for job_id in completion)
    setup = sum(
        float(operations_by_id[op_id].get("setup_time_minutes", 0)) + float(machines[row["machine_id"]].get("setup_time_minutes", 0))
        for op_id, row in placements.items()
    )
    risky_count = sum(1 for row in placements.values() if row["machine_id"] in risky_machines)
    idle_gaps = 0.0
    by_machine: dict[str, list[dict]] = defaultdict(list)
    for op_id, row in placements.items():
        by_machine[row["machine_id"]].append({"operation_id": op_id, **row})
    # Search cost idle means avoidable machine gaps before assigned operations,
    # excluding time before availability and known maintenance/breakdown intervals.
    for machine_id, rows in by_machine.items():
        rows.sort(key=lambda row: (row["start_minute"], row["end_minute"], row["operation_id"]))
        cursor = float(machines[machine_id].get("available_from_minute", 0.0))
        for row in rows:
            start = float(row["start_minute"])
            if start > cursor:
                idle_gaps += max(0.0, start - cursor - _blackout_overlap(cursor, start, blackouts.get(machine_id, [])))
            cursor = max(cursor, float(row["end_minute"]))
    return (
        weights["makespan"] * makespan
        + weights["total_tardiness"] * tardiness
        + weights["idle_time"] * idle_gaps
        + weights["setup_time"] * setup
        + weights["machine_risk"] * risky_count
    )


def _heuristic(
    placements: dict[str, dict], jobs: dict[str, dict], machines: dict[str, dict], operations_by_id: dict[str, dict],
    ops_by_job: dict[str, list[dict]], weights: dict[str, float],
) -> float:
    if not placements and not operations_by_id:
        return 0.0
    current_makespan = max((float(row["end_minute"]) for row in placements.values()), default=0.0)
    earliest_completion: dict[str, float] = {}
    minimum_remaining_setup = 0.0
    for job_id, items in ops_by_job.items():
        time = float(jobs[job_id]["release_minute"])
        for operation in items:
            existing = placements.get(operation["id"])
            if existing is not None:
                time = max(time, float(existing["end_minute"]))
                continue
            durations = []
            for machine_id in operation["eligible_machine_ids"]:
                machine = machines.get(machine_id)
                if machine:
                    durations.append(float(operation["processing_time_minutes"]) + float(operation.get("setup_time_minutes", 0)) + float(machine.get("setup_time_minutes", 0)))
            if not durations:
                # Dead-end successors are pruned before expansion; zero keeps this a lower bound.
                minimum_duration = 0.0
                minimum_setup = 0.0
            else:
                minimum_duration = min(durations)
                minimum_setup = min(
                    float(operation.get("setup_time_minutes", 0)) + float(machines[mid].get("setup_time_minutes", 0))
                    for mid in operation["eligible_machine_ids"] if mid in machines
                )
            time = max(time, float(jobs[job_id]["release_minute"])) + minimum_duration
            minimum_remaining_setup += minimum_setup
        earliest_completion[job_id] = time
    makespan_bound = max(current_makespan, max(earliest_completion.values(), default=0.0))
    weighted = weights["makespan"] * max(0.0, makespan_bound - current_makespan)
    for job_id, completion in earliest_completion.items():
        # Fully scheduled job tardiness is already included in g(n).
        if all(operation["id"] in placements for operation in ops_by_job[job_id]):
            continue
        weighted += weights["total_tardiness"] * max(0.0, completion - float(jobs[job_id]["due_minute"]))
    remaining_count = sum(1 for operation_id in operations_by_id if operation_id not in placements)
    if remaining_count:
        weighted += weights["setup_time"] * minimum_remaining_setup
    # Idle and optional risk penalties have an admissible lower bound of zero.
    return weighted


def _scheduled_rows(placements: dict[str, dict], jobs: dict[str, dict], machines: dict[str, dict], operations_by_id: dict[str, dict], predecessor: dict[str, str | None], horizon) -> list[dict]:
    from .engine import _iso

    rows = []
    for operation_id, row in placements.items():
        operation = operations_by_id[operation_id]
        job = jobs[operation["job_id"]]
        machine = machines[row["machine_id"]]
        start, end = float(row["start_minute"]), float(row["end_minute"])
        duration = float(operation["processing_time_minutes"]) + float(operation.get("setup_time_minutes", 0)) + float(machine.get("setup_time_minutes", 0))
        pred_id = predecessor.get(operation_id)
        ready = max(float(job["release_minute"]), float(placements[pred_id]["end_minute"]) if pred_id and pred_id in placements else float(job["release_minute"]))
        rows.append({
            "operation_id": operation_id, "job_id": job["id"], "machine_id": row["machine_id"],
            "operation_name": operation["name"], "sequence": operation["sequence"],
            "start_minute": round(start, 4), "end_minute": round(end, 4),
            "processing_time_minutes": operation["processing_time_minutes"],
            "setup_time_minutes": operation.get("setup_time_minutes", 0) + machine.get("setup_time_minutes", 0),
            "duration_minutes": round(duration, 4), "waiting_time_minutes": round(max(0.0, start - ready), 4),
            "due_minute": job["due_minute"], "due_at": _iso(as_utc(job["due_at"])),
            "start_at": _iso(horizon + timedelta(minutes=start)), "end_at": _iso(horizon + timedelta(minutes=end)),
        })
    return sorted(rows, key=lambda row: (row["start_minute"], row["machine_id"], row["operation_id"]))


def _iso(value) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def run_search(
    algorithm: str, jobs_input: list[dict], machines_input: list[dict], operations_input: list[dict], scenario: str,
    *, machine_blackouts: dict[str, list[tuple[float, float]]] | None = None, risk_machines: set[str] | None = None,
    frozen_operations: list[dict] | None = None, search_options: dict | None = None, hard_due_dates: bool = False, trace_collector=None,
) -> dict[str, Any]:
    """Run one bounded best-first search. Success always contains a full verified schedule."""
    from .engine import SchedulingError, _calendar_blackouts, _prepare
    from .metrics import calculate_metrics
    from .validation import validate_dataset
    from .knowledge import validate_complete_schedule

    started = perf_counter()
    options = search_options or {}
    max_expansions = int(options.get("max_expansions", DEFAULT_LIMITS["max_expansions"]))
    max_seconds = float(options.get("max_seconds", DEFAULT_LIMITS["max_seconds"]))
    supplied_weights = options.get("weights") or {}
    weights = {key: float(supplied_weights.get(key, value)) for key, value in DEFAULT_WEIGHTS.items()}
    mode = SEARCH_ALGORITHMS.get(algorithm)
    expanded = generated = duplicates = 0
    search_stats = {"states_expanded": 0, "states_generated": 0, "duplicate_states": 0, "termination_status": "not_started", "optimality_proven": False, "max_expansions": max_expansions, "max_seconds": max_seconds, "search_cost": None, "weights": weights}
    try:
        if not mode:
            raise SchedulingError(f"Unknown search algorithm {algorithm}.")
        if max_expansions < 1 or max_seconds <= 0:
            raise SchedulingError("Search limits must allow at least one state and a positive time limit.")
        if any(value < 0 for value in weights.values()) or not any(value > 0 for value in weights.values()):
            raise SchedulingError("Search cost weights must be non-negative and at least one must be greater than zero.")
        validate_dataset(jobs_input, machines_input, operations_input, scenario)
        jobs, machines, operations, predecessor, horizon = _prepare(jobs_input, machines_input, operations_input)
        operations_by_id = {operation["id"]: operation for operation in operations}
        jobs_by_id = jobs
        machines_by_id = machines
        ops_by_job: dict[str, list[dict]] = defaultdict(list)
        for operation in operations:
            ops_by_job[operation["job_id"]].append(operation)
        for values in ops_by_job.values():
            values.sort(key=lambda operation: operation["sequence"])
        blackouts = _calendar_blackouts(machines, horizon, machine_blackouts)
        risky = risk_machines or set()
        placements: dict[str, dict] = {}
        for row in frozen_operations or []:
            operation_id = row["operation_id"]
            if operation_id not in operations_by_id or operation_id in placements:
                raise SchedulingError(f"Frozen operation {operation_id} is missing or duplicated.")
            if row["machine_id"] not in machines_by_id:
                raise SchedulingError(f"Frozen operation {operation_id} uses an unknown machine.")
            placements[operation_id] = {"machine_id": row["machine_id"], "start_minute": float(row["start_minute"]), "end_minute": float(row["end_minute"]), "frozen": True}
        if len(placements) > len(operations_by_id):
            raise SchedulingError("Frozen operation set exceeds the required operation set.")
        root_key = _state_key(placements)
        root_g = _cost(placements, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, blackouts, risky, weights)
        root_h = _heuristic(placements, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights)
        sequence = count()
        if mode == "dfs":
            frontier: list[tuple[float, int, dict, float, int]] = [(0.0, next(sequence), placements, root_g, 0)]
        else:
            priority = {"astar": root_g + root_h, "ucs": root_g, "greedy": root_h, "bfs": 0.0}[mode]
            frontier = [(priority, next(sequence), placements, root_g, 0)]
        best_g = {root_key: root_g}
        generated = 1
        trace_ids = {}
        if trace_collector is not None:
            root_h_value = root_h
            trace_ids[root_key] = trace_collector.record("root", placements, depth=0, g=root_g, h=root_h_value, f=root_g + root_h_value)
        best_goal: dict | None = None
        best_goal_cost: float | None = None
        limit_hit = False
        while frontier:
            if expanded >= max_expansions or perf_counter() - started >= max_seconds:
                limit_hit = True
                break
            priority, _, state, state_g, depth = heappop(frontier) if mode != "dfs" else frontier.pop()
            key = _state_key(state)
            if state_g > best_g.get(key, float("inf")) + 1e-8:
                if trace_collector is not None:
                    trace_collector.record("stale", state, parent_id=trace_ids.get(key), depth=depth, g=state_g, h=_heuristic(state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights), f=state_g + _heuristic(state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights), reason="A lower-cost path to this state was already found.")
                continue
            if len(state) == len(operations_by_id):
                rows = _scheduled_rows(state, jobs_by_id, machines_by_id, operations_by_id, predecessor, horizon)
                metrics = calculate_metrics(list(jobs_by_id.values()), list(machines_by_id.values()), rows, 0.0, blackouts)
                if hard_due_dates and any(value > 1e-7 for value in metrics.get("job_lateness_minutes", {}).values()):
                    if trace_collector is not None:
                        trace_collector.record("infeasible", state, parent_id=trace_ids.get(key), depth=depth, g=state_g, h=0.0, f=state_g, reason="Hard due-date constraint violated.")
                    continue
                if trace_collector is not None:
                    trace_collector.record("goal", state, parent_id=trace_ids.get(key), depth=depth, g=state_g, h=0.0, f=state_g)
                violations = validate_complete_schedule(list(jobs_by_id.values()), list(machines_by_id.values()), operations_input, rows, machine_blackouts=blackouts, preserved_operations=frozen_operations)
                if violations:
                    raise SchedulingError("Search reached a goal that failed knowledge-rule validation: " + " ".join(violations))
                if best_goal_cost is None or state_g < best_goal_cost:
                    best_goal = state
                    best_goal_cost = state_g
                # With idle-gap cost disabled, all edge costs are non-negative
                # and the remaining-work estimate is a lower bound. The first
                # A*/UCS goal can then be certified; otherwise exhaust the
                # bounded frontier or report a feasible but unproven plan.
                if mode in {"astar", "ucs"} and weights["idle_time"] == 0:
                    termination = "optimal"
                    search_stats.update({"states_expanded": expanded, "states_generated": generated, "duplicate_states": duplicates, "termination_status": termination, "optimality_proven": True, "search_cost": round(state_g, 6)})
                    metrics["search_cost"] = round(state_g, 6)
                    return {"algorithm_name": algorithm, "scenario": scenario, "feasible": True, "scheduled_operations": rows, "metrics": metrics, "risk_fallback_operation_ids": [], "search_stats": search_stats, "computation_time_ms": round((perf_counter() - started) * 1000, 4), "error_message": None}
                else:
                    continue

            expanded += 1
            if trace_collector is not None:
                trace_ids[key] = trace_collector.record("expanded", state, parent_id=trace_ids.get(key), depth=depth, g=state_g, h=_heuristic(state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights), f=state_g + _heuristic(state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights))
            actions = applicable_actions(jobs_by_id, machines_by_id, operations, state, predecessor, blackouts, risky)
            if not actions and trace_collector is not None:
                dead_end_h = _heuristic(state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights)
                trace_collector.record("infeasible", state, parent_id=trace_ids.get(key), depth=depth, g=state_g, h=dead_end_h, f=state_g + dead_end_h, reason="No applicable planning actions remain before reaching a complete schedule.")
            for action in actions:
                next_state = apply_action(state, action)
                next_key = _state_key(next_state)
                candidate_g = _cost(next_state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, blackouts, risky, weights)
                action_payload = {"operation_id": action.operation_id, "machine_id": action.machine_id, "start_minute": action.start_minute, "end_minute": action.end_minute, "preconditions": list(action.preconditions), "effects": list(action.effects)}
                h = _heuristic(next_state, jobs_by_id, machines_by_id, operations_by_id, ops_by_job, weights)
                if candidate_g >= best_g.get(next_key, float("inf")) - 1e-9:
                    duplicates += 1
                    if trace_collector is not None:
                        trace_collector.record("duplicate", next_state, parent_id=trace_ids.get(key), action=action_payload, depth=depth + 1, g=candidate_g, h=h, f=candidate_g + h, reason="State was already reached at equal or lower cost.")
                    continue
                best_g[next_key] = candidate_g
                if trace_collector is not None:
                    trace_ids[next_key] = trace_collector.record("generated", next_state, parent_id=trace_ids.get(key), action=action_payload, depth=depth + 1, g=candidate_g, h=h, f=candidate_g + h)
                next_depth = depth + 1
                state_priority = {"astar": candidate_g + h, "ucs": candidate_g, "greedy": h, "bfs": float(next_depth), "dfs": -float(next_depth)}[mode]
                heappush(frontier, (state_priority, next(sequence), next_state, candidate_g, next_depth))
                generated += 1
        exhausted = not frontier
        if limit_hit:
            termination = "feasible_limit" if best_goal is not None else "limit_without_solution"
            message = (f"Search reached the configured limit ({expanded} states, {max_seconds:g} seconds) without proving optimality; a complete feasible schedule is available." if best_goal is not None else f"Search stopped at its configured limit ({expanded} states or {max_seconds:g} seconds) before finding a complete feasible schedule. Increase the limits or try a dispatch baseline. No partial schedule was returned.")
        elif exhausted and best_goal is None:
            termination = "exhausted_no_solution"
            message = "The search exhausted its reachable states without finding a complete schedule satisfying the hard constraints. No partial schedule was returned."
        elif best_goal is not None:
            termination = "optimal" if mode in {"astar", "ucs"} else "search_complete_feasible"
            message = None
        else:
            termination = "exhausted_no_solution"
            message = "No complete feasible schedule was found. No partial schedule was returned."
        proven = termination == "optimal" and mode in {"astar", "ucs"}
        search_stats.update({"states_expanded": expanded, "states_generated": generated, "duplicate_states": duplicates, "termination_status": termination, "optimality_proven": proven, "search_cost": round(best_goal_cost, 6) if best_goal_cost is not None else None})
        elapsed = round((perf_counter() - started) * 1000, 4)
        if best_goal is not None:
            rows = _scheduled_rows(best_goal, jobs_by_id, machines_by_id, operations_by_id, predecessor, horizon)
            metrics = calculate_metrics(list(jobs_by_id.values()), list(machines_by_id.values()), rows, 0.0, blackouts)
            metrics["search_cost"] = round(best_goal_cost or 0.0, 6)
            return {"algorithm_name": algorithm, "scenario": scenario, "feasible": True, "scheduled_operations": rows, "metrics": metrics, "risk_fallback_operation_ids": [], "search_stats": search_stats, "computation_time_ms": elapsed, "error_message": message}
        return {"algorithm_name": algorithm, "scenario": scenario, "feasible": False, "scheduled_operations": [], "metrics": {}, "risk_fallback_operation_ids": [], "search_stats": search_stats, "computation_time_ms": elapsed, "error_message": message}
    except (ValueError, KeyError, TypeError) as exc:
        search_stats.update({"states_expanded": expanded, "states_generated": generated, "duplicate_states": duplicates, "termination_status": "invalid_input", "optimality_proven": False})
        return {"algorithm_name": algorithm, "scenario": scenario, "feasible": False, "scheduled_operations": [], "metrics": {}, "risk_fallback_operation_ids": [], "search_stats": search_stats, "computation_time_ms": round((perf_counter() - started) * 1000, 4), "error_message": str(exc)}
