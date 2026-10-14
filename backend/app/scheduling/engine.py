from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from time import perf_counter

from .knowledge import validate_complete_schedule
from .metrics import calculate_metrics
from .validation import as_utc, validate_dataset

ALGORITHMS = [
    "FCFS", "SPT", "EDD", "Priority-Based", "LPT", "NEH", "A* Search",
    "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search",
]
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
DISPATCH_ALGORITHMS = {"FCFS", "SPT", "EDD", "Priority-Based", "LPT"}
SEARCH_ALGORITHMS = {"A* Search", "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search"}


class SchedulingError(ValueError):
    pass


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _prepare(jobs: list[dict], machines: list[dict], operations: list[dict]):
    releases = [as_utc(job["release_at"]) for job in jobs]
    horizon = min(releases)

    def minute(value):
        return (as_utc(value) - horizon).total_seconds() / 60

    job_data = {job["id"]: {**job, "release_minute": minute(job["release_at"]), "due_minute": minute(job["due_at"])} for job in jobs}
    machine_data = {
        machine["id"]: {
            **machine,
            "available_from_minute": minute(machine["available_from"]),
            "available_until_minute": minute(machine["available_until"]) if machine.get("available_until") else None,
            "processing_capabilities": machine.get("processing_capabilities") or [],
            "maintenance_schedule": machine.get("maintenance_schedule") or [],
        }
        for machine in machines
    }
    op_data = [dict(operation) for operation in operations]
    by_job = defaultdict(list)
    for operation in op_data:
        by_job[operation["job_id"]].append(operation)
    predecessor = {}
    for job_id, items in by_job.items():
        items.sort(key=lambda operation: operation["sequence"])
        previous = None
        for operation in items:
            predecessor[operation["id"]] = operation.get("predecessor_id") or previous
            previous = operation["id"]
    return job_data, machine_data, op_data, predecessor, horizon


def _calendar_blackouts(machines: dict[str, dict], horizon: datetime, extra: dict[str, list[tuple[float, float]]] | None = None) -> dict[str, list[tuple[float, float]]]:
    calendars: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for machine_id, intervals in (extra or {}).items():
        calendars[machine_id].extend((float(start), float(end)) for start, end in intervals if end > start)
    for machine_id, machine in machines.items():
        for window in machine.get("maintenance_schedule", []) or []:
            start_at = as_utc(window["starts_at"])
            end_at = as_utc(window["ends_at"])
            start = (start_at - horizon).total_seconds() / 60
            end = (end_at - horizon).total_seconds() / 60
            if end > start:
                calendars[machine_id].append((start, end))
    merged: dict[str, list[tuple[float, float]]] = {}
    for machine_id, values in calendars.items():
        combined: list[list[float]] = []
        for start, end in sorted(values):
            if combined and start <= combined[-1][1] + 1e-9:
                combined[-1][1] = max(combined[-1][1], end)
            else:
                combined.append([start, end])
        merged[machine_id] = [(start, end) for start, end in combined]
    return merged


def _rank(op: dict, job: dict, algorithm: str):
    base = (job["release_minute"], job["due_minute"], PRIORITY_ORDER.get(job["priority"], 9), op["sequence"], op["id"].casefold())
    duration = op["processing_time_minutes"] + op.get("setup_time_minutes", 0)
    if algorithm == "SPT":
        return (duration, *base)
    if algorithm == "LPT":
        return (-duration, *base)
    if algorithm == "EDD":
        return (job["due_minute"], *base)
    if algorithm == "Priority-Based":
        return (PRIORITY_ORDER.get(job["priority"], 9), *base)
    return base


def _find_machine_start(machine: dict, ready: float, duration: float, intervals: dict[str, list[tuple[float, float]]]):
    if not machine["is_available"]:
        return None
    start = max(ready, machine["available_from_minute"])
    limit = machine.get("available_until_minute")
    for begin, end in sorted(intervals.get(machine["id"], [])):
        if start + duration <= begin + 1e-9:
            break
        if start < end - 1e-9:
            start = end
    if limit is not None and start + duration > limit + 1e-9:
        return None
    return start


def _flowshop_permutation(order: list[dict], jobs: dict, machines: dict, ops_by_job: dict[str, list[dict]], horizon: datetime, blackouts: dict[str, list[tuple[float, float]]] | None = None):
    machine_tail = {machine_id: machines[machine_id]["available_from_minute"] for machine_id in machines}
    intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for machine_id, values in (blackouts or {}).items():
        intervals[machine_id].extend(values)
    scheduled = []
    for job in order:
        previous_end = jobs[job["id"]]["release_minute"]
        for operation in ops_by_job[job["id"]]:
            machine_id = operation["eligible_machine_ids"][0]
            machine = machines[machine_id]
            duration = operation["processing_time_minutes"] + operation.get("setup_time_minutes", 0) + machine.get("setup_time_minutes", 0)
            start = _find_machine_start(machine, max(previous_end, machine_tail[machine_id]), duration, intervals)
            if start is None:
                raise SchedulingError(f"Operation {operation['id']} cannot fit in machine {machine_id}'s availability / maintenance calendar.")
            end = start + duration
            due = jobs[job["id"]]["due_minute"]
            scheduled.append({"operation_id": operation["id"], "job_id": job["id"], "machine_id": machine_id, "operation_name": operation["name"], "sequence": operation["sequence"], "start_minute": round(start, 4), "end_minute": round(end, 4), "processing_time_minutes": operation["processing_time_minutes"], "setup_time_minutes": operation.get("setup_time_minutes", 0) + machine.get("setup_time_minutes", 0), "duration_minutes": duration, "waiting_time_minutes": round(max(0, start - previous_end), 4), "due_minute": due, "due_at": _iso(as_utc(jobs[job["id"]]["due_at"])), "start_at": _iso(horizon + timedelta(minutes=start)), "end_at": _iso(horizon + timedelta(minutes=end))})
            machine_tail[machine_id] = end
            intervals[machine_id].append((start, end))
            previous_end = end
    return scheduled


def _neh(jobs: dict, machines: dict, operations: list[dict], horizon: datetime, blackouts: dict[str, list[tuple[float, float]]] | None = None):
    ops_by_job = defaultdict(list)
    for operation in operations:
        ops_by_job[operation["job_id"]].append(operation)
    for items in ops_by_job.values():
        items.sort(key=lambda operation: operation["sequence"])
    priority = sorted(jobs.values(), key=lambda job: (-sum(operation["processing_time_minutes"] + operation.get("setup_time_minutes", 0) for operation in ops_by_job[job["id"]]), job["release_minute"], job["due_minute"], job["id"].casefold()))
    sequence: list[dict] = []
    for job in priority:
        best = None
        for position in range(len(sequence) + 1):
            candidate = [*sequence[:position], job, *sequence[position:]]
            result = _flowshop_permutation(candidate, jobs, machines, ops_by_job, horizon, blackouts)
            makespan = max((item["end_minute"] for item in result), default=0)
            key = (makespan, tuple(item["id"].casefold() for item in candidate))
            if best is None or key < best[0]:
                best = (key, candidate)
        if best is None:
            raise RuntimeError("NEH failed to evaluate an insertion position.")
        sequence = best[1]
    return _flowshop_permutation(sequence, jobs, machines, ops_by_job, horizon, blackouts)


def _dispatch(algorithm: str, jobs: dict, machines: dict, operations: list[dict], predecessor: dict, horizon: datetime, *, frozen_operations: list[dict] | None = None, machine_blackouts: dict[str, list[tuple[float, float]]] | None = None, risk_machines: set[str] | None = None):
    from .knowledge import Compatible

    intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    scheduled: list[dict] = []
    done: dict[str, float] = {}
    by_id = {operation["id"]: operation for operation in operations}
    for machine_id, blocked_times in (machine_blackouts or {}).items():
        intervals[machine_id].extend((begin, end) for begin, end in blocked_times if end > begin)
    frozen_ids: set[str] = set()
    for item in sorted(frozen_operations or [], key=lambda row: (row["start_minute"], row["sequence"], row["operation_id"])):
        operation_id = item["operation_id"]
        if operation_id not in by_id or item["machine_id"] not in machines:
            raise SchedulingError(f"Saved in-progress operation {operation_id} cannot be protected because its input or machine is missing.")
        if operation_id in frozen_ids:
            raise SchedulingError(f"Saved in-progress operation {operation_id} was supplied more than once.")
        if not Compatible(by_id[operation_id], machines[item["machine_id"]]):
            raise SchedulingError(f"Saved in-progress operation {operation_id} cannot be protected on incompatible machine {item['machine_id']}.")
        pred = predecessor.get(operation_id)
        if pred and pred not in done:
            raise SchedulingError(f"Saved in-progress operation {operation_id} cannot be protected because predecessor {pred} is not complete.")
        scheduled.append(dict(item))
        intervals[item["machine_id"]].append((item["start_minute"], item["end_minute"]))
        done[operation_id] = item["end_minute"]
        frozen_ids.add(operation_id)
    pending = set(by_id) - frozen_ids
    risk_fallbacks: set[str] = set()
    while pending:
        options = []
        for op_id in pending:
            operation = by_id[op_id]
            pred = predecessor.get(op_id)
            if pred and pred not in done:
                continue
            job = jobs[operation["job_id"]]
            ready = max(job["release_minute"], done[pred] if pred else job["release_minute"])
            eligible = []
            for machine_id in sorted(set(operation["eligible_machine_ids"])):
                machine = machines[machine_id]
                if not Compatible(operation, machine):
                    continue
                duration = operation["processing_time_minutes"] + operation.get("setup_time_minutes", 0) + machine.get("setup_time_minutes", 0)
                start = _find_machine_start(machine, ready, duration, intervals)
                if start is not None:
                    eligible.append((start, machine_id, duration, machine))
            if eligible and risk_machines:
                safe = [item for item in eligible if item[1] not in risk_machines]
                if safe:
                    eligible = safe
                elif any(item[1] in risk_machines for item in eligible):
                    risk_fallbacks.add(op_id)
            if eligible:
                best_start = min(item[0] for item in eligible)
                machine_choice = min((item for item in eligible if abs(item[0] - best_start) < 1e-9), key=lambda item: item[1])
                options.append((best_start, _rank(operation, job, algorithm), op_id, operation, job, machine_choice, ready))
        if not options:
            blocked = []
            for op_id in sorted(pending):
                operation = by_id[op_id]
                if not any(machines[mid]["is_available"] for mid in operation["eligible_machine_ids"]):
                    blocked.append(f"Operation {op_id} has no available eligible machine.")
                elif predecessor.get(op_id) in pending:
                    blocked.append(f"Operation {op_id} is blocked by its predecessor.")
                else:
                    blocked.append(f"Operation {op_id} cannot fit within its eligible machine availability window or maintenance calendar.")
            raise SchedulingError(" ".join(blocked))
        earliest = min(item[0] for item in options)
        candidates = [item for item in options if abs(item[0] - earliest) < 1e-9]
        _, _, op_id, operation, job, machine_choice, ready = min(candidates, key=lambda item: (item[1], item[2].casefold()))
        start, machine_id, duration, machine = machine_choice
        end = start + duration
        item = {"operation_id": op_id, "job_id": job["id"], "machine_id": machine_id, "operation_name": operation["name"], "sequence": operation["sequence"], "start_minute": round(start, 4), "end_minute": round(end, 4), "processing_time_minutes": operation["processing_time_minutes"], "setup_time_minutes": operation.get("setup_time_minutes", 0) + machine.get("setup_time_minutes", 0), "duration_minutes": duration, "waiting_time_minutes": round(max(0, start - ready), 4), "due_minute": job["due_minute"], "due_at": _iso(as_utc(job["due_at"])), "start_at": _iso(horizon + timedelta(minutes=start)), "end_at": _iso(horizon + timedelta(minutes=end))}
        scheduled.append(item)
        intervals[machine_id].append((start, end))
        done[op_id] = end
        pending.remove(op_id)
    return sorted(scheduled, key=lambda row: (row["start_minute"], row["machine_id"], row["operation_id"])), sorted(risk_fallbacks)


def run_algorithm(
    algorithm: str, jobs: list[dict], machines: list[dict], operations: list[dict], scenario: str, *,
    frozen_operations: list[dict] | None = None, machine_blackouts: dict[str, list[tuple[float, float]]] | None = None,
    risk_machines: set[str] | None = None, search_options: dict | None = None, hard_due_dates: bool = False, trace_collector=None,
) -> dict:
    started = perf_counter()
    try:
        validate_dataset(jobs, machines, operations, scenario)
        if algorithm == "NEH" and scenario != "permutation_flow_shop":
            raise SchedulingError("NEH is only supported for the explicitly selected permutation-flow-shop scenario.")
        if scenario == "permutation_flow_shop" and algorithm not in {"NEH", *SEARCH_ALGORITHMS}:
            raise SchedulingError("Permutation flow shop supports NEH and the explicitly labelled state-space search algorithms; dispatch baselines require Job Shop or Parallel Machine.")
        if algorithm not in {*DISPATCH_ALGORITHMS, "NEH", *SEARCH_ALGORITHMS}:
            raise SchedulingError(f"Unknown scheduling algorithm {algorithm}.")
        if algorithm in SEARCH_ALGORITHMS:
            from .search import run_search
            return run_search(algorithm, jobs, machines, operations, scenario, machine_blackouts=machine_blackouts, risk_machines=risk_machines, frozen_operations=frozen_operations, search_options=search_options, hard_due_dates=hard_due_dates, trace_collector=trace_collector)
        if algorithm == "NEH" and (frozen_operations or risk_machines or machine_blackouts):
            raise SchedulingError("Dynamic rescheduling supports Job Shop and Parallel-Machine dispatch/search results; NEH permutation-flow-shop rescheduling is not implemented.")
        prepared_jobs, prepared_machines, prepared_ops, predecessor, horizon = _prepare(jobs, machines, operations)
        calendars = _calendar_blackouts(prepared_machines, horizon, machine_blackouts)
        if algorithm == "NEH":
            scheduled = _neh(prepared_jobs, prepared_machines, prepared_ops, horizon, calendars)
            risk_fallbacks = []
        else:
            scheduled, risk_fallbacks = _dispatch(algorithm, prepared_jobs, prepared_machines, prepared_ops, predecessor, horizon, frozen_operations=frozen_operations, machine_blackouts=calendars, risk_machines=risk_machines)
        metrics = calculate_metrics(list(prepared_jobs.values()), list(prepared_machines.values()), scheduled, 0.0, calendars)
        violations = validate_complete_schedule(list(prepared_jobs.values()), list(prepared_machines.values()), prepared_ops, scheduled, machine_blackouts=calendars, preserved_operations=frozen_operations)
        if violations:
            raise SchedulingError("Schedule failed knowledge-base validation: " + " ".join(violations))
        if hard_due_dates and any(value > 1e-7 for value in metrics.get("job_lateness_minutes", {}).values()):
            late = sorted(jid for jid, value in metrics.get("job_lateness_minutes", {}).items() if value > 1e-7)
            raise SchedulingError(f"Hard due-date constraint violated by job(s): {', '.join(late)}.")
        return {"algorithm_name": algorithm, "scenario": scenario, "feasible": True, "scheduled_operations": scheduled, "metrics": metrics, "risk_fallback_operation_ids": risk_fallbacks, "search_stats": None, "computation_time_ms": round((perf_counter() - started) * 1000, 4), "error_message": None}
    except (ValueError, KeyError, TypeError) as exc:
        return {"algorithm_name": algorithm, "scenario": scenario, "feasible": False, "scheduled_operations": [], "metrics": {}, "risk_fallback_operation_ids": [], "search_stats": None, "computation_time_ms": round((perf_counter() - started) * 1000, 4), "error_message": str(exc)}
