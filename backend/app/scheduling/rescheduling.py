from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class RescheduleError(ValueError):
    """A disruption cannot be applied safely to the selected saved schedule."""


def _aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _minute(value: str | datetime, horizon: datetime) -> float:
    return (_aware(value) - horizon).total_seconds() / 60.0


def _at_minute(value: float, horizon: datetime) -> str:
    return _iso(horizon + timedelta(minutes=value))


def _ordered_ops(operations: list[dict]) -> dict[str, list[dict]]:
    by_job: dict[str, list[dict]] = {}
    for operation in operations:
        by_job.setdefault(operation["job_id"], []).append(operation)
    for items in by_job.values():
        items.sort(key=lambda item: (item["sequence"], item["id"].casefold()))
    return by_job


def build_reschedule_plan(snapshot: dict, scheduled: list[dict], payload: dict) -> dict[str, Any]:
    """Build a new, validated input snapshot while leaving the saved source untouched."""
    jobs = [dict(item) for item in snapshot.get("jobs", [])]
    machines = [dict(item) for item in snapshot.get("machines", [])]
    operations = [dict(item) for item in snapshot.get("operations", [])]
    if not jobs or not machines or not operations:
        raise RescheduleError("This saved schedule does not contain a complete manufacturing input snapshot. Generate a fresh schedule before rescheduling.")

    horizon = _aware(snapshot.get("horizon_start") or min(item["release_at"] for item in jobs))
    effective_at = _aware(payload["effective_at"])
    event_minute = _minute(effective_at, horizon)
    event_type = payload["event_type"]
    machine_by_id = {item["id"]: item for item in machines}
    op_by_id = {item["id"]: item for item in operations}
    schedule_by_id = {item["operation_id"]: item for item in scheduled}
    if set(schedule_by_id) != set(op_by_id):
        raise RescheduleError("The selected algorithm's saved schedule is missing or duplicates operations. It cannot be rescheduled safely.")
    if event_minute < min(item["start_minute"] for item in scheduled) - 1e-7:
        raise RescheduleError("Event time is earlier than the selected schedule. Choose a time at or after production starts.")

    scheduled_ids = set(schedule_by_id)
    automatically_completed = {operation_id for operation_id, item in schedule_by_id.items() if item["end_minute"] <= event_minute + 1e-7}
    explicit_completed = set(payload.get("completed_operation_ids") or [])
    unknown = explicit_completed - scheduled_ids
    if unknown:
        raise RescheduleError(f"Unknown completed operation ID(s): {', '.join(sorted(unknown))}.")
    not_finished = {operation_id for operation_id in explicit_completed if schedule_by_id[operation_id]["end_minute"] > event_minute + 1e-7}
    if not_finished:
        raise RescheduleError(f"Operation(s) cannot be marked complete before their planned end at the selected event time: {', '.join(sorted(not_finished))}.")
    completed = automatically_completed | explicit_completed
    unfinished = scheduled_ids - completed

    history = [dict(item) for item in snapshot.get("dynamic_event_history", [])]
    event: dict[str, Any] = {"event_type": event_type, "effective_at": _iso(effective_at)}
    for field in ("machine_id", "repair_until", "operation_id", "delay_minutes", "risk_note"):
        if payload.get(field) is not None:
            value = payload[field]
            event[field] = _iso(_aware(value)) if field == "repair_until" else value
    impact_direct: set[str] = set()
    affected_jobs: set[str] = set()
    restart_operation_ids: set[str] = set()
    operation_by_job = _ordered_ops(operations)

    if event_type in {"machine_breakdown", "maintenance"}:
        machine_id = payload.get("machine_id")
        if not isinstance(machine_id, str) or machine_id not in machine_by_id:
            raise RescheduleError(f"Machine {machine_id or '(missing)'} is not part of this saved schedule.")
        repair_at = _aware(payload["repair_until"])
        if repair_at <= effective_at:
            raise RescheduleError("Repair / maintenance end must be later than the event time.")
        impact_direct = {operation_id for operation_id in unfinished if schedule_by_id[operation_id]["machine_id"] == machine_id}
        if not impact_direct:
            raise RescheduleError(f"No pending operation is scheduled on {machine_id} after the chosen event time. Select a different time or machine.")
        event["repair_until"] = _iso(repair_at)
        # A non-preemptive operation interrupted by a breakdown/maintenance is
        # conservatively restarted from zero after the machine returns.
        restart_operation_ids = {operation_id for operation_id in impact_direct if schedule_by_id[operation_id]["start_minute"] < event_minute < schedule_by_id[operation_id]["end_minute"]}
    elif event_type == "processing_delay":
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str):
            raise RescheduleError("A processing-delay event requires a valid operation ID.")
        row = schedule_by_id.get(operation_id)
        if row is None:
            raise RescheduleError(f"Operation {operation_id or '(missing)'} is not part of the selected schedule.")
        if operation_id in completed or not (row["start_minute"] <= event_minute < row["end_minute"]):
            raise RescheduleError("A processing-delay event must target an operation in progress at the selected event time. Choose its active time window.")
        if operation_id in completed:
            raise RescheduleError("A completed operation cannot receive a processing delay.")
        impact_direct = {operation_id}
    elif event_type == "machine_risk":
        machine_id = payload.get("machine_id")
        if not isinstance(machine_id, str) or machine_id not in machine_by_id:
            raise RescheduleError(f"Machine {machine_id or '(missing)'} is not part of this saved schedule.")
        impact_direct = {
            operation_id for operation_id in unfinished
            if schedule_by_id[operation_id]["machine_id"] == machine_id
            and schedule_by_id[operation_id]["start_minute"] >= event_minute - 1e-7
        }
        if not impact_direct:
            raise RescheduleError(f"No not-yet-started operation is assigned to {machine_id} after the selected risk event time.")
        event["risk_note"] = (payload.get("risk_note") or "Operator-reported high machine risk.").strip()
    elif event_type == "urgent_order":
        new_job = dict(payload["urgent_job"])
        if any(item["id"] == new_job["id"] for item in jobs):
            raise RescheduleError(f"Urgent Job ID {new_job['id']} already exists in this schedule snapshot.")
        if _aware(new_job["due_at"]) <= effective_at:
            raise RescheduleError("The urgent job due time must be later than its event/release time.")
        new_job["priority"] = "Critical"
        new_job.setdefault("component_type", "other")
        new_job.setdefault("status", "queued")
        new_job["release_at"] = _iso(effective_at)
        new_job["is_sample"] = False
        urgent_operations = [dict(item) for item in payload["urgent_operations"]]
        existing_ids = set(op_by_id)
        seen_ids: set[str] = set()
        for sequence, operation in enumerate(urgent_operations, start=1):
            if operation["job_id"] != new_job["id"]:
                raise RescheduleError("Every urgent-order operation must refer to the new urgent Job ID.")
            if operation["id"] in existing_ids or operation["id"] in seen_ids:
                raise RescheduleError(f"Urgent operation ID {operation['id']} already exists.")
            if operation["sequence"] != sequence:
                raise RescheduleError("Urgent-order operation sequence numbers must be consecutive, starting at 1.")
            expected_predecessor = urgent_operations[sequence - 2]["id"] if sequence > 1 else None
            if operation.get("predecessor_id") != expected_predecessor:
                raise RescheduleError("Urgent-order operations must link to the immediately preceding operation, in sequence.")
            missing = set(operation["eligible_machine_ids"]) - set(machine_by_id)
            if missing:
                raise RescheduleError(f"Urgent operation {operation['id']} names unknown eligible machine(s): {', '.join(sorted(missing))}.")
            operation["is_sample"] = False
            operation.setdefault("required_capability", None)
            seen_ids.add(operation["id"])
        jobs.append(new_job)
        operations.extend(urgent_operations)
        affected_jobs.add(new_job["id"])
        impact_direct = {item["id"] for item in urgent_operations}
        operation_by_job = _ordered_ops(operations)
    else:
        raise RescheduleError(f"Unsupported event type {event_type}.")

    # Any downstream operation of disrupted work is also considered affected.
    affected_operations: set[str] = set(impact_direct)
    for operation_id in impact_direct:
        op = op_by_id.get(operation_id)
        if not op:
            continue
        affected_jobs.add(op["job_id"])
        for later in operation_by_job[op["job_id"]]:
            row = schedule_by_id.get(later["id"])
            if later["sequence"] >= op["sequence"] and (row is None or row["end_minute"] > event_minute + 1e-7):
                affected_operations.add(later["id"])
                affected_jobs.add(later["job_id"])

    if event_type == "processing_delay":
        delay = int(payload["delay_minutes"])
        target = op_by_id[payload["operation_id"]]
        target["processing_time_minutes"] += delay
        event["delay_minutes"] = delay
    elif event_type == "urgent_order":
        event["urgent_job_id"] = payload["urgent_job"]["id"]

    frozen: list[dict] = []
    frozen_ids: set[str] = set()
    for operation_id, row in schedule_by_id.items():
        is_active = row["start_minute"] <= event_minute < row["end_minute"]
        # Completed work is immutable. Other in-progress work is non-preemptive
        # and remains on its planned machine unless it is directly disrupted.
        if operation_id in completed or (is_active and operation_id not in impact_direct) or (event_type == "processing_delay" and operation_id == payload.get("operation_id")):
            fixed = dict(row)
            if event_type == "processing_delay" and operation_id == payload.get("operation_id"):
                fixed["processing_time_minutes"] += int(payload["delay_minutes"])
                fixed["duration_minutes"] += int(payload["delay_minutes"])
                fixed["end_minute"] += int(payload["delay_minutes"])
                fixed["end_at"] = _at_minute(fixed["end_minute"], horizon)
            frozen.append(fixed)
            frozen_ids.add(operation_id)

    blackouts: dict[str, list[tuple[float, float]]] = {}
    for prior_event in [*history, event]:
        if prior_event.get("event_type") not in {"machine_breakdown", "maintenance"}:
            continue
        machine_id = prior_event.get("machine_id")
        begin = _minute(prior_event["effective_at"], horizon)
        finish = _minute(prior_event["repair_until"], horizon)
        blackouts.setdefault(machine_id, []).append((begin, finish))
    risky_machines: set[str] = set()
    for item in [*history, event]:
        machine_id = item.get("machine_id")
        if item.get("event_type") == "machine_risk" and isinstance(machine_id, str):
            risky_machines.add(machine_id)
    for blackout_machine in blackouts:
        if blackout_machine not in machine_by_id:
            raise RescheduleError(f"Saved downtime history refers to unknown machine {blackout_machine}.")

    event["id"] = payload.get("event_id")
    history.append(event)
    explanations = {
        "machine_breakdown": f"Machine {event.get('machine_id')} is blocked from {event['effective_at']} until repair at {event.get('repair_until')}. Interrupted non-preemptive work is conservatively restarted with its full processing duration after repair.",
        "maintenance": f"Machine {event.get('machine_id')} is reserved for maintenance from {event['effective_at']} until {event.get('repair_until')}; remaining eligible work is rescheduled around that window.",
        "processing_delay": f"Operation {event.get('operation_id')} is extended by {event.get('delay_minutes')} minutes; its unfinished downstream work waits for the revised completion.",
        "urgent_order": f"Critical-priority urgent job {event.get('urgent_job_id')} is released at {event['effective_at']} and inserted with its ordered, machine-eligible operations.",
        "machine_risk": f"Machine {event.get('machine_id')} was marked high risk by an operator; safe eligible machines are preferred. Risky fallback use is disclosed if no safe assignment is feasible.",
    }
    explanation = explanations[event_type]

    return {
        "jobs": jobs,
        "machines": machines,
        "operations": operations,
        "horizon_start": _iso(horizon),
        "event": event,
        "event_history": history,
        "event_minute": event_minute,
        "machine_blackouts": blackouts,
        "risk_machines": risky_machines,
        "frozen_operations": frozen,
        "completed_operation_ids": sorted(completed),
        "locked_operation_ids": sorted(frozen_ids),
        "restart_operation_ids": sorted(restart_operation_ids),
        "affected_operation_ids": sorted(affected_operations),
        "affected_job_ids": sorted(affected_jobs),
        "explanation": explanation,
    }


def compare_schedules(before: list[dict], after: list[dict], event_affected_jobs: list[str], event_affected_operations: list[str]) -> dict[str, Any]:
    before_by_id = {item["operation_id"]: item for item in before}
    after_by_id = {item["operation_id"]: item for item in after}
    shared = sorted(set(before_by_id) & set(after_by_id))
    moved = []
    unchanged = 0
    for operation_id in shared:
        old = before_by_id[operation_id]
        new = after_by_id[operation_id]
        same = old["machine_id"] == new["machine_id"] and abs(old["start_minute"] - new["start_minute"]) < 1e-7 and abs(old["end_minute"] - new["end_minute"]) < 1e-7
        if same:
            unchanged += 1
            continue
        moved.append({
            "operation_id": operation_id,
            "job_id": old["job_id"],
            "operation_name": old["operation_name"],
            "machine_before": old["machine_id"],
            "machine_after": new["machine_id"],
            "start_before": old["start_at"],
            "start_after": new["start_at"],
            "end_before": old["end_at"],
            "end_after": new["end_at"],
        })
    shared_count = len(shared)
    stability = round(100.0 * unchanged / shared_count, 2) if shared_count else 100.0
    affected_jobs = set(event_affected_jobs)
    affected_operations = set(event_affected_operations)
    for item in moved:
        affected_jobs.add(item["job_id"])
        affected_operations.add(item["operation_id"])
    added = sorted(set(after_by_id) - set(before_by_id))
    for operation_id in added:
        affected_operations.add(operation_id)
        affected_jobs.add(after_by_id[operation_id]["job_id"])
    return {
        "moved_operations": moved,
        "moved_operation_ids": [item["operation_id"] for item in moved],
        "added_operation_ids": added,
        "affected_job_ids": sorted(affected_jobs),
        "affected_operation_ids": sorted(affected_operations),
        "shared_operation_count": shared_count,
        "unchanged_operation_count": unchanged,
        "stability_percent": stability,
        "stability_definition": "Percentage of operations present in both runs whose machine, start minute, and end minute are unchanged.",
    }
