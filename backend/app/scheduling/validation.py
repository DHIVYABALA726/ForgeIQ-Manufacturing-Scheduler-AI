from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from .knowledge import validate_capabilities


class DatasetError(ValueError):
    pass


def validate_dataset(jobs: list[dict], machines: list[dict], operations: list[dict], scenario: str) -> None:
    if not jobs:
        raise DatasetError("Add at least one job before generating schedules.")
    if not machines:
        raise DatasetError("Add at least one machine before generating schedules.")
    if not operations:
        raise DatasetError("Add at least one operation before generating schedules.")
    job_ids = {j["id"] for j in jobs}
    machine_ids = {m["id"] for m in machines}
    by_job: dict[str, list[dict]] = defaultdict(list)
    operations_by_id = {o["id"]: o for o in operations}
    if len(operations_by_id) != len(operations):
        raise DatasetError("Operation IDs must be unique.")
    for op in operations:
        if op["job_id"] not in job_ids:
            raise DatasetError(f"Operation {op['id']} refers to missing job {op['job_id']}.")
        if op["processing_time_minutes"] <= 0 or op["setup_time_minutes"] < 0:
            raise DatasetError(f"Operation {op['id']} must have a positive processing time and non-negative setup time.")
        if not op["eligible_machine_ids"]:
            raise DatasetError(f"Operation {op['id']} needs at least one eligible machine.")
        missing = sorted(set(op["eligible_machine_ids"]) - machine_ids)
        if missing:
            raise DatasetError(f"Operation {op['id']} references missing machine(s): {', '.join(missing)}.")
        by_job[op["job_id"]].append(op)
    for job in jobs:
        items = sorted(by_job[job["id"]], key=lambda x: x["sequence"])
        if not items:
            raise DatasetError(f"Job {job['id']} has no operations.")
        seqs = [o["sequence"] for o in items]
        if len(set(seqs)) != len(seqs):
            raise DatasetError(f"Job {job['id']} has duplicate operation sequence numbers.")
        previous = None
        for op in items:
            explicit_predecessor = op.get("predecessor_id")
            if explicit_predecessor and explicit_predecessor != previous:
                raise DatasetError(f"Predecessor for operation {op['id']} must be the immediately previous operation in sequence.")
            pred = explicit_predecessor or previous
            if pred:
                if pred not in operations_by_id:
                    raise DatasetError(f"Operation {op['id']} refers to missing predecessor {pred}.")
                predecessor = operations_by_id[pred]
                if predecessor["job_id"] != op["job_id"] or predecessor["sequence"] >= op["sequence"]:
                    raise DatasetError(f"Predecessor for operation {op['id']} must be an earlier operation in the same job.")
            previous = op["id"]
    if scenario == "parallel_machine":
        multi = [job_id for job_id, items in by_job.items() if len(items) != 1]
        if multi:
            raise DatasetError("Single-Operation / Parallel-Machine scheduling requires exactly one operation per job. Choose Job Shop for multi-operation jobs.")
    if scenario == "permutation_flow_shop":
        sequences = []
        for job in jobs:
            items = sorted(by_job[job["id"]], key=lambda x: x["sequence"])
            if any(len(o["eligible_machine_ids"]) != 1 for o in items):
                raise DatasetError("NEH permutation flow shop requires exactly one eligible machine per operation.")
            sequences.append(tuple(o["eligible_machine_ids"][0] for o in items))
        if not sequences or any(seq != sequences[0] for seq in sequences):
            raise DatasetError("Permutation flow shop requires every job to use the same ordered machine sequence.")
        if len(set(sequences[0])) != len(sequences[0]):
            raise DatasetError("Each flow-shop stage must use a distinct machine.")
    try:
        validate_capabilities(operations, machines)
    except ValueError as exc:
        raise DatasetError(str(exc)) from exc


def as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        from datetime import timezone
        value = value.replace(tzinfo=timezone.utc)
    return value
