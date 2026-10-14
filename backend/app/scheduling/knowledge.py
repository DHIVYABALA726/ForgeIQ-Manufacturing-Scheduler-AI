from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable


PREDICATE_NAMES = ("Compatible", "Precedes", "Available", "Finished")

RULES = (
    "Each required operation occurs exactly once in a complete schedule.",
    "A machine processes at most one operation at a time.",
    "A dependent operation starts no earlier than its predecessor's completion.",
    "An operation may use only an explicitly eligible machine with its required processing capability.",
    "An unavailable machine, a maintenance interval, and the time outside its configured availability window cannot contain processing.",
    "A completed production operation retained during rescheduling keeps its original machine and start/end times.",
)


def _aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def Compatible(operation: dict, machine: dict) -> bool:  # noqa: N802 - domain predicate
    """Knowledge predicate: explicit eligibility plus any declared capability."""
    if machine["id"] not in set(operation.get("eligible_machine_ids", [])):
        return False
    required = operation.get("required_capability")
    capabilities = set(machine.get("processing_capabilities") or [])
    # Empty legacy capability lists mean capability metadata was not entered;
    # explicit eligible_machine_ids remain authoritative for old user records.
    return not required or required in capabilities


def Precedes(operation_a: dict, operation_b: dict) -> bool:  # noqa: N802 - domain predicate
    """Knowledge predicate for the immediate ordered operation dependency."""
    return operation_b.get("predecessor_id") == operation_a.get("id") or (
        operation_a.get("job_id") == operation_b.get("job_id")
        and operation_a.get("sequence", 0) + 1 == operation_b.get("sequence", -1)
    )


def Available(machine: dict, minute: float, blackout_intervals: Iterable[tuple[float, float]] = ()) -> bool:  # noqa: N802
    """Knowledge predicate for availability at a minute relative to the run horizon."""
    if not machine.get("is_available", True):
        return False
    start = float(machine.get("available_from_minute", 0.0))
    until = machine.get("available_until_minute")
    if minute < start - 1e-7 or (until is not None and minute >= float(until) - 1e-7):
        return False
    return not any(begin - 1e-7 <= minute < end - 1e-7 for begin, end in blackout_intervals)


def Finished(operation_id: str, at_minute: float, completions: dict[str, float]) -> bool:  # noqa: N802
    """Knowledge predicate derived only from an actual completed operation record."""
    return operation_id in completions and completions[operation_id] <= at_minute + 1e-7


def validate_capabilities(operations: list[dict], machines: list[dict]) -> None:
    machine_by_id = {machine["id"]: machine for machine in machines}
    for operation in operations:
        eligible = [machine_by_id[mid] for mid in operation.get("eligible_machine_ids", []) if mid in machine_by_id]
        capable = [machine for machine in eligible if Compatible(operation, machine)]
        if not capable:
            requirement = operation.get("required_capability")
            suffix = f" with required capability {requirement}" if requirement else ""
            raise ValueError(f"Operation {operation['id']} has no compatible eligible machine{suffix}.")


def validate_complete_schedule(
    jobs: list[dict],
    machines: list[dict],
    operations: list[dict],
    scheduled: list[dict],
    *,
    machine_blackouts: dict[str, list[tuple[float, float]]] | None = None,
    preserved_operations: list[dict] | None = None,
) -> list[str]:
    """Evaluate the logical schedule rules; return every detected violation."""
    blackouts = machine_blackouts or {}
    violations: list[str] = []
    jobs_by_id = {job["id"]: job for job in jobs}
    machines_by_id = {machine["id"]: machine for machine in machines}
    operations_by_id = {operation["id"]: operation for operation in operations}
    counts = Counter(row.get("operation_id") for row in scheduled)
    duplicate = sorted(str(operation_id) for operation_id, count in counts.items() if count > 1 and operation_id is not None)
    if duplicate:
        violations.append(f"Operation(s) appear more than once: {', '.join(map(str, duplicate))}.")
    missing = sorted(set(operations_by_id) - set(counts))
    unknown = sorted({str(operation_id) for operation_id in counts if operation_id not in operations_by_id})
    if missing:
        violations.append(f"Required operation(s) are missing: {', '.join(missing)}.")
    if unknown:
        violations.append(f"Unknown operation(s) appear in the schedule: {', '.join(unknown)}.")

    by_machine: dict[str, list[dict]] = defaultdict(list)
    rows_by_operation = {row.get("operation_id"): row for row in scheduled if row.get("operation_id") in operations_by_id}
    for row in scheduled:
        operation = operations_by_id.get(row.get("operation_id"))
        machine = machines_by_id.get(row.get("machine_id"))
        if not operation or not machine:
            violations.append(f"Scheduled operation {row.get('operation_id')} refers to a missing operation or machine.")
            continue
        job = jobs_by_id.get(operation["job_id"])
        if not job:
            violations.append(f"Operation {operation['id']} refers to missing job {operation['job_id']}.")
            continue
        if not Compatible(operation, machine):
            violations.append(f"Operation {operation['id']} is not compatible with machine {machine['id']}.")
        start, end = float(row["start_minute"]), float(row["end_minute"])
        if end <= start:
            violations.append(f"Operation {operation['id']} must finish after it starts.")
        if not machine.get("is_available", True):
            violations.append(f"Machine {machine['id']} is unavailable.")
        available_from = float(machine.get("available_from_minute", 0.0))
        available_until = machine.get("available_until_minute")
        if start < available_from - 1e-7 or (available_until is not None and end > float(available_until) + 1e-7):
            violations.append(f"Operation {operation['id']} falls outside machine {machine['id']}'s availability window.")
        for begin, finish in blackouts.get(machine["id"], []):
            if start < finish - 1e-7 and end > begin + 1e-7:
                violations.append(f"Operation {operation['id']} overlaps unavailable/maintenance time on machine {machine['id']}.")
                break
        process = float(operation.get("processing_time_minutes", 0))
        setup = float(operation.get("setup_time_minutes", 0)) + float(machine.get("setup_time_minutes", 0))
        if abs((end - start) - (process + setup)) > 1e-5:
            violations.append(f"Operation {operation['id']} has an inconsistent scheduled duration.")
        if "release_minute" in job and start < float(job["release_minute"]) - 1e-7:
            violations.append(f"Operation {operation['id']} starts before job {job['id']} is released.")
        by_machine[machine["id"]].append(row)

    for machine_id, rows in by_machine.items():
        rows.sort(key=lambda row: (float(row["start_minute"]), float(row["end_minute"]), str(row["operation_id"])))
        for left, right in zip(rows, rows[1:]):
            if float(left["end_minute"]) > float(right["start_minute"]) + 1e-7:
                violations.append(f"Machine {machine_id} processes operations {left['operation_id']} and {right['operation_id']} simultaneously.")

    for operation in operations:
        row = rows_by_operation.get(operation["id"])
        if not row:
            continue
        predecessor_id = operation.get("predecessor_id")
        if not predecessor_id:
            previous = next((candidate for candidate in operations if candidate["job_id"] == operation["job_id"] and candidate.get("sequence", 0) == operation.get("sequence", 0) - 1), None)
            predecessor_id = previous["id"] if previous else None
        if predecessor_id:
            predecessor = rows_by_operation.get(predecessor_id)
            if not predecessor or float(row["start_minute"]) < float(predecessor["end_minute"]) - 1e-7:
                violations.append(f"Operation {operation['id']} starts before predecessor {predecessor_id} finishes.")

    for preserved in preserved_operations or []:
        row = rows_by_operation.get(preserved.get("operation_id"))
        if row is None or row.get("machine_id") != preserved.get("machine_id") or abs(float(row["start_minute"]) - float(preserved["start_minute"])) > 1e-7 or abs(float(row["end_minute"]) - float(preserved["end_minute"])) > 1e-7:
            violations.append(f"Completed operation {preserved.get('operation_id')} moved or was duplicated during rescheduling.")
    return violations


def build_knowledge_facts(jobs: list[dict], machines: list[dict], operations: list[dict], scheduled: list[dict] | None = None) -> dict:
    """Serialize the current dataset as inspectable ground facts for the UI/API."""
    machine_by_id = {machine["id"]: machine for machine in machines}
    operation_by_id = {operation["id"]: operation for operation in operations}
    compatible = [
        {"operation_id": operation["id"], "machine_id": machine["id"], "required_capability": operation.get("required_capability")}
        for operation in operations for machine_id in operation.get("eligible_machine_ids", [])
        if (machine := machine_by_id.get(machine_id)) is not None and Compatible(operation, machine)
    ]
    precedes = []
    by_job: dict[str, list[dict]] = defaultdict(list)
    for operation in operations:
        by_job[operation["job_id"]].append(operation)
    for values in by_job.values():
        values.sort(key=lambda value: (value["sequence"], value["id"]))
        precedes.extend({"before": left["id"], "after": right["id"]} for left, right in zip(values, values[1:]))
    finished = []
    for row in scheduled or []:
        finished.append({"operation_id": row["operation_id"], "at_minute": row["end_minute"]})
    return {
        "predicates": list(PREDICATE_NAMES),
        "facts": {
            "jobs": [{"job_id": job["id"], "component_type": job.get("component_type", "other"), "priority": job["priority"], "release_at": job["release_at"], "due_at": job["due_at"], "status": job.get("status", "queued")} for job in jobs],
            "machines": [{"machine_id": machine["id"], "type": machine["machine_type"], "available": machine["is_available"], "capabilities": machine.get("processing_capabilities", []), "maintenance_schedule": machine.get("maintenance_schedule", [])} for machine in machines],
            "operations": [{"operation_id": operation["id"], "job_id": operation["job_id"], "sequence": operation["sequence"], "required_capability": operation.get("required_capability")} for operation in operations],
            "compatible": compatible,
            "precedes": precedes,
            "finished": finished,
        },
        "rules": list(RULES),
        "counts": {"jobs": len(jobs), "machines": len(machines), "operations": len(operations), "compatible_pairs": len(compatible), "precedence_links": len(precedes)},
        "predicate_definitions": {
            "Compatible(operation,machine)": "The machine is explicitly eligible and, when required, has the operation's processing capability.",
            "Precedes(operation_A,operation_B)": "operation_A is the immediate earlier operation of the same job, and must finish before B starts.",
            "Available(machine,time)": "The machine is enabled, within its configured time window, and outside maintenance/breakdown intervals.",
            "Finished(operation,time)": "An actual schedule record for the operation has end_minute no later than time.",
        },
    }
