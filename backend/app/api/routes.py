from __future__ import annotations

from datetime import datetime, timezone
from typing import NoReturn
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, delete
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import AlgorithmResult, DatasetState, DisruptionEvent, Job, Machine, Operation, Recommendation, ScheduleRun, ScheduledOperation
from ..schemas import DynamicRescheduleInput, JobInput, MachineInput, OperationInput, ScheduleRequest, SelectScheduleInput
from ..scheduling.automotive import AUTOMOTIVE_WORKFLOWS, workflow_payload
from ..scheduling.engine import _calendar_blackouts, _prepare, run_algorithm
from ..scheduling.knowledge import Compatible, RULES, build_knowledge_facts
from ..scheduling.planning import applicable_actions
from ..scheduling.recommendation import rank_results
from ..scheduling.rescheduling import RescheduleError, build_reschedule_plan, compare_schedules
from ..scheduling.validation import DatasetError, validate_dataset

router = APIRouter(prefix="/api/v1")


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _job_dict(item: Job) -> dict:
    return {"id": item.id, "name": item.name, "product_name": item.product_name, "quantity": item.quantity, "priority": item.priority, "release_at": _iso(item.release_at), "due_at": _iso(item.due_at), "component_type": item.component_type, "status": item.status, "notes": item.notes, "is_sample": item.is_sample}


def _machine_dict(item: Machine) -> dict:
    return {"id": item.id, "name": item.name, "machine_type": item.machine_type, "available_from": _iso(item.available_from), "available_until": _iso(item.available_until), "is_available": item.is_available, "setup_time_minutes": item.setup_time_minutes, "processing_capabilities": item.processing_capabilities or [], "maintenance_schedule": item.maintenance_schedule or [], "is_sample": item.is_sample}


def _operation_dict(item: Operation) -> dict:
    return {"id": item.id, "job_id": item.job_id, "name": item.name, "sequence": item.sequence, "eligible_machine_ids": item.eligible_machine_ids, "processing_time_minutes": item.processing_time_minutes, "setup_time_minutes": item.setup_time_minutes, "predecessor_id": item.predecessor_id, "required_capability": item.required_capability, "is_sample": item.is_sample}


def _machine_values(payload: MachineInput) -> dict:
    values = payload.model_dump(exclude={"maintenance_schedule"})
    values["maintenance_schedule"] = [item.model_dump(mode="json") for item in payload.maintenance_schedule]
    return values


def _version(db: Session) -> int:
    state = db.get(DatasetState, 1)
    return state.version if state else 0


def _bump_version(db: Session) -> int:
    state = db.get(DatasetState, 1)
    if state is None:
        state = DatasetState(id=1, version=0)
        db.add(state)
    state.version += 1
    return state.version


def _not_found(entity: str, item_id: str) -> NoReturn:
    raise HTTPException(status_code=404, detail=f"{entity} {item_id} was not found.")


def _new_or_update(model, payload):
    return payload.model_dump()


def _run_payload(run: ScheduleRun, db: Session, include_snapshot: bool = False) -> dict:
    current_version = _version(db)
    results = []
    for result in run.results:
        operations = result.result_payload.get("scheduled_operations", []) if result.feasible else []
        metrics = result.metrics if result.feasible else {}
        violations = [] if result.feasible else [result.error_message or "No feasible schedule was produced for this algorithm."]
        results.append({"algorithm_name": result.algorithm_name, "scenario": run.scenario, "feasible": result.feasible, "scheduled_operations": operations, "metrics": metrics, "objective_value": metrics.get(run.objective), "constraint_violations": violations, "risk_fallback_operation_ids": result.result_payload.get("risk_fallback_operation_ids", []), "search_stats": result.result_payload.get("search_stats"), "computation_time_ms": result.computation_time_ms, "error_message": result.error_message})
    recommendation = run.recommendation
    payload = {"id": run.id, "scenario": run.scenario, "objective": run.objective, "secondary_objectives": run.secondary_objectives, "hard_due_dates": bool(run.input_snapshot.get("hard_due_dates", False)), "dataset_version": run.dataset_version, "current_dataset_version": current_version, "is_stale": run.dataset_version != current_version, "created_at": _iso(run.created_at), "selected_algorithm_name": run.selected_algorithm_name, "recommended_algorithm_name": recommendation.recommended_algorithm_name if recommendation else None, "recommendation_reason": recommendation.reason if recommendation else None, "recommendation_details": recommendation.details if recommendation else {}, "results": results}
    if include_snapshot:
        payload["input_snapshot"] = run.input_snapshot
        payload["dynamic_reschedule"] = run.input_snapshot.get("dynamic_reschedule")
    return payload


@router.get("/health")
def health():
    return {"status": "ok", "service": "forgeiq-api"}


@router.get("/dataset-version")
def dataset_version(db: Session = Depends(get_db)):
    return {"version": _version(db)}


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db)):
    return {"items": [_job_dict(x) for x in db.scalars(select(Job).order_by(Job.id)).all()]}


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_job(payload: JobInput, db: Session = Depends(get_db)):
    if db.get(Job, payload.id):
        raise HTTPException(409, f"Job ID {payload.id} already exists.")
    item = Job(**_new_or_update(Job, payload))
    db.add(item); _bump_version(db); db.commit(); db.refresh(item)
    return _job_dict(item)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    item = db.get(Job, job_id)
    if not item: _not_found("Job", job_id)
    return _job_dict(item)


@router.put("/jobs/{job_id}")
def update_job(job_id: str, payload: JobInput, db: Session = Depends(get_db)):
    item = db.get(Job, job_id)
    if not item: _not_found("Job", job_id)
    if payload.id != job_id and db.get(Job, payload.id): raise HTTPException(409, f"Job ID {payload.id} already exists.")
    if payload.id != job_id: raise HTTPException(422, "Job IDs cannot be changed. Delete this job and recreate it with the new ID.")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    _bump_version(db); db.commit(); db.refresh(item)
    return _job_dict(item)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    item = db.get(Job, job_id)
    if not item: _not_found("Job", job_id)
    db.delete(item); _bump_version(db); db.commit()
    return None


@router.get("/machines")
def list_machines(db: Session = Depends(get_db)):
    return {"items": [_machine_dict(x) for x in db.scalars(select(Machine).order_by(Machine.id)).all()]}


@router.post("/machines", status_code=201)
def create_machine(payload: MachineInput, db: Session = Depends(get_db)):
    if db.get(Machine, payload.id): raise HTTPException(409, f"Machine ID {payload.id} already exists.")
    item = Machine(**_machine_values(payload)); db.add(item); _bump_version(db); db.commit(); db.refresh(item)
    return _machine_dict(item)


@router.put("/machines/{machine_id}")
def update_machine(machine_id: str, payload: MachineInput, db: Session = Depends(get_db)):
    item = db.get(Machine, machine_id)
    if not item: _not_found("Machine", machine_id)
    if payload.id != machine_id: raise HTTPException(422, "Machine IDs cannot be changed. Delete and recreate the machine to use another ID.")
    for key, value in _machine_values(payload).items(): setattr(item, key, value)
    _bump_version(db); db.commit(); db.refresh(item)
    return _machine_dict(item)


@router.delete("/machines/{machine_id}", status_code=204)
def delete_machine(machine_id: str, db: Session = Depends(get_db)):
    item = db.get(Machine, machine_id)
    if not item: _not_found("Machine", machine_id)
    used = [o.id for o in db.scalars(select(Operation)).all() if machine_id in (o.eligible_machine_ids or [])]
    if used: raise HTTPException(409, f"Machine {machine_id} is referenced by operation(s) {', '.join(used)}. Edit those operations before deleting the machine.")
    db.delete(item); _bump_version(db); db.commit()
    return None


@router.get("/operations")
def list_operations(db: Session = Depends(get_db)):
    return {"items": [_operation_dict(x) for x in db.scalars(select(Operation).order_by(Operation.job_id, Operation.sequence, Operation.id)).all()]}


def _validate_operation(payload: OperationInput, db: Session, current_id: str | None = None):
    if not db.get(Job, payload.job_id): raise HTTPException(422, f"Operation refers to missing job {payload.job_id}.")
    previous = db.scalar(select(Operation).where(Operation.job_id == payload.job_id, Operation.sequence < payload.sequence, Operation.id != (current_id or "")).order_by(Operation.sequence.desc()).limit(1))
    if payload.predecessor_id and (previous is None or payload.predecessor_id != previous.id):
        raise HTTPException(422, "Predecessor must be the immediately previous operation in this job's sequence.")
    if payload.predecessor_id:
        pred = db.get(Operation, payload.predecessor_id)
        if not pred and payload.predecessor_id != current_id: raise HTTPException(422, f"Predecessor operation {payload.predecessor_id} does not exist.")
        if pred and (pred.job_id != payload.job_id or pred.sequence >= payload.sequence): raise HTTPException(422, "Predecessor must be an earlier operation in the same job.")
    missing = [mid for mid in set(payload.eligible_machine_ids) if not db.get(Machine, mid)]
    if missing: raise HTTPException(422, f"Unknown eligible machine(s): {', '.join(missing)}.")
    if payload.required_capability:
        capable = [db.get(Machine, mid) for mid in payload.eligible_machine_ids]
        if not any(machine is not None and Compatible(payload.model_dump(), _machine_dict(machine)) for machine in capable):
            raise HTTPException(422, f"No eligible machine provides required processing capability {payload.required_capability}.")
    duplicate_sequence = db.scalar(select(Operation).where(Operation.job_id == payload.job_id, Operation.sequence == payload.sequence, Operation.id != (current_id or "")))
    if duplicate_sequence: raise HTTPException(409, f"Job {payload.job_id} already has an operation at sequence {payload.sequence}.")


@router.post("/operations", status_code=201)
def create_operation(payload: OperationInput, db: Session = Depends(get_db)):
    if db.get(Operation, payload.id): raise HTTPException(409, f"Operation ID {payload.id} already exists.")
    _validate_operation(payload, db)
    item = Operation(**payload.model_dump()); db.add(item); _bump_version(db); db.commit(); db.refresh(item)
    return _operation_dict(item)


@router.put("/operations/{operation_id}")
def update_operation(operation_id: str, payload: OperationInput, db: Session = Depends(get_db)):
    item = db.get(Operation, operation_id)
    if not item: _not_found("Operation", operation_id)
    if payload.id != operation_id: raise HTTPException(422, "Operation IDs cannot be changed. Delete and recreate the operation with the new ID.")
    _validate_operation(payload, db, operation_id)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    _bump_version(db); db.commit(); db.refresh(item)
    return _operation_dict(item)


@router.delete("/operations/{operation_id}", status_code=204)
def delete_operation(operation_id: str, db: Session = Depends(get_db)):
    item = db.get(Operation, operation_id)
    if not item: _not_found("Operation", operation_id)
    dependents = db.scalars(select(Operation).where(Operation.predecessor_id == operation_id)).all()
    if dependents: raise HTTPException(409, f"Operation {operation_id} is a predecessor of {', '.join(x.id for x in dependents)}. Edit those operations before deleting it.")
    db.delete(item); _bump_version(db); db.commit()
    return None


@router.post("/sample", status_code=201)
def load_sample(db: Session = Depends(get_db)):
    if db.scalar(select(Job.id).limit(1)) or db.scalar(select(Machine.id).limit(1)):
        raise HTTPException(409, "Sample data can only be loaded into an empty workspace. Remove existing entries or create your own data.")
    stamp = "2030-01-15T08:00:00+00:00"
    machines = [Machine(id="M-101", name="Precision Mill", machine_type="Milling", available_from=datetime.fromisoformat(stamp), is_available=True, setup_time_minutes=0, is_sample=True), Machine(id="M-102", name="CNC Drill", machine_type="Drilling", available_from=datetime.fromisoformat(stamp), is_available=True, setup_time_minutes=0, is_sample=True), Machine(id="M-103", name="Assembly Cell", machine_type="Assembly", available_from=datetime.fromisoformat(stamp), is_available=True, setup_time_minutes=0, is_sample=True)]
    jobs = [Job(id="J-201", name="Bracket batch", product_name="Mounting bracket", quantity=24, priority="High", release_at=datetime.fromisoformat(stamp), due_at=datetime.fromisoformat("2030-01-15T12:00:00+00:00"), notes="Deterministic demonstration sample", is_sample=True), Job(id="J-202", name="Housing batch", product_name="Drive housing", quantity=12, priority="Medium", release_at=datetime.fromisoformat("2030-01-15T08:20:00+00:00"), due_at=datetime.fromisoformat("2030-01-15T15:00:00+00:00"), notes="Deterministic demonstration sample", is_sample=True), Job(id="J-203", name="Rotor batch", product_name="Rotor assembly", quantity=8, priority="Critical", release_at=datetime.fromisoformat("2030-01-15T08:10:00+00:00"), due_at=datetime.fromisoformat("2030-01-15T11:30:00+00:00"), notes="Deterministic demonstration sample", is_sample=True)]
    ops = [
        Operation(id="OP-201-1", job_id="J-201", name="Milling", sequence=1, eligible_machine_ids=["M-101"], processing_time_minutes=42, setup_time_minutes=5, is_sample=True),
        Operation(id="OP-201-2", job_id="J-201", name="Drilling", sequence=2, eligible_machine_ids=["M-102"], processing_time_minutes=24, setup_time_minutes=0, predecessor_id="OP-201-1", is_sample=True),
        Operation(id="OP-201-3", job_id="J-201", name="Assembly", sequence=3, eligible_machine_ids=["M-103"], processing_time_minutes=36, setup_time_minutes=3, predecessor_id="OP-201-2", is_sample=True),
        Operation(id="OP-202-1", job_id="J-202", name="Milling", sequence=1, eligible_machine_ids=["M-101"], processing_time_minutes=29, setup_time_minutes=0, is_sample=True),
        Operation(id="OP-202-2", job_id="J-202", name="Drilling", sequence=2, eligible_machine_ids=["M-102"], processing_time_minutes=22, setup_time_minutes=0, predecessor_id="OP-202-1", is_sample=True),
        Operation(id="OP-202-3", job_id="J-202", name="Assembly", sequence=3, eligible_machine_ids=["M-103"], processing_time_minutes=48, setup_time_minutes=0, predecessor_id="OP-202-2", is_sample=True),
        Operation(id="OP-203-1", job_id="J-203", name="Milling", sequence=1, eligible_machine_ids=["M-101"], processing_time_minutes=35, setup_time_minutes=2, is_sample=True),
        Operation(id="OP-203-2", job_id="J-203", name="Drilling", sequence=2, eligible_machine_ids=["M-102"], processing_time_minutes=18, setup_time_minutes=0, predecessor_id="OP-203-1", is_sample=True),
        Operation(id="OP-203-3", job_id="J-203", name="Assembly", sequence=3, eligible_machine_ids=["M-103"], processing_time_minutes=30, setup_time_minutes=0, predecessor_id="OP-203-2", is_sample=True),
    ]
    db.add_all([*machines, *jobs, *ops]); _bump_version(db); db.commit()
    return {"message": "Deterministic sample dataset loaded. Sample records are labelled and can be removed.", "jobs": len(jobs), "machines": len(machines), "operations": len(ops)}


@router.delete("/sample")
def remove_sample(db: Session = Depends(get_db)):
    sample_jobs = set(db.scalars(select(Job.id).where(Job.is_sample.is_(True))).all())
    sample_machines = set(db.scalars(select(Machine.id).where(Machine.is_sample.is_(True))).all())
    if not sample_jobs and not sample_machines: raise HTTPException(404, "No labelled sample dataset is loaded.")
    user_ops = db.scalars(select(Operation).where(Operation.is_sample.is_(False))).all()
    blockers = [op.id for op in user_ops if op.job_id in sample_jobs or sample_machines.intersection(op.eligible_machine_ids or [])]
    if blockers: raise HTTPException(409, f"Sample data is referenced by manually entered operation(s): {', '.join(blockers)}. Edit or remove them before removing the sample.")
    db.execute(delete(Operation).where(Operation.is_sample.is_(True)))
    for job_id in sample_jobs:
        item = db.get(Job, job_id)
        if item: db.delete(item)
    for machine_id in sample_machines:
        item = db.get(Machine, machine_id)
        if item: db.delete(item)
    _bump_version(db); db.commit()
    return {"message": "Labelled sample records removed."}


def _snapshot(db: Session):
    jobs = [_job_dict(x) for x in db.scalars(select(Job).order_by(Job.id)).all()]
    machines = [_machine_dict(x) for x in db.scalars(select(Machine).order_by(Machine.id)).all()]
    operations = [_operation_dict(x) for x in db.scalars(select(Operation).order_by(Operation.job_id, Operation.sequence)).all()]
    return jobs, machines, operations


@router.get("/automotive/workflows")
def automotive_workflows():
    return workflow_payload()


@router.post("/automotive/sample", status_code=201)
def load_automotive_sample(db: Session = Depends(get_db)):
    if db.scalar(select(Job.id).limit(1)) or db.scalar(select(Machine.id).limit(1)):
        raise HTTPException(409, "Automotive demonstration data can only be loaded into an empty workspace. Remove existing entries or use manual entry.")
    stamp = "2030-01-15T08:00:00+00:00"
    machine_specs = [
        ("AUTO-MILL", "CNC Milling Cell", "CNC Milling", ["cnc_milling"]),
        ("AUTO-TURN", "CNC Turning Cell", "CNC Turning", ["cnc_turning"]),
        ("AUTO-DRILL", "Drilling Cell", "Drilling", ["drilling"]),
        ("AUTO-GRIND", "Grinding Cell", "Grinding", ["grinding"]),
        ("AUTO-INSP", "Inspection Cell", "Inspection", ["inspection"]),
    ]
    machines = [Machine(id=mid, name=name, machine_type=kind, available_from=datetime.fromisoformat(stamp), is_available=True, setup_time_minutes=0, processing_capabilities=caps, maintenance_schedule=[], is_sample=True) for mid, name, kind, caps in machine_specs]
    job_specs = [
        ("AUTO-ENG-01", "Engine Block Batch", "engine_block", "Aluminum engine block", 12, "High", 480),
        ("AUTO-CRANK-01", "Crankshaft Batch", "crankshaft", "Steel crankshaft", 8, "Critical", 600),
        ("AUTO-BRAKE-01", "Brake Disc Batch", "brake_disc", "Brake disc", 16, "Medium", 720),
    ]
    jobs = [Job(id=jid, name=name, product_name=product, component_type=component, status="queued", quantity=quantity, priority=priority, release_at=datetime.fromisoformat(stamp), due_at=datetime.fromisoformat(f"2030-01-15T{8 + due_minutes // 60:02d}:{due_minutes % 60:02d}:00+00:00"), notes="Simulated educational automotive workflow; not a certified process plan.", is_sample=True) for jid, name, component, product, quantity, priority, due_minutes in job_specs]
    machine_for_capability = {capability: mid for mid, _name, _kind, capabilities in machine_specs for capability in capabilities}
    durations_by_component = {
        "engine_block": [("Milling", "cnc_milling", 40), ("Drilling", "drilling", 28), ("Inspection", "inspection", 15)],
        "crankshaft": [("Turning", "cnc_turning", 35), ("Grinding", "grinding", 26), ("Inspection", "inspection", 12)],
        "brake_disc": [("Turning", "cnc_turning", 24), ("Drilling", "drilling", 18), ("Inspection", "inspection", 10)],
    }
    operations = []
    for job_id, _name, component, _product, _quantity, _priority, _due_minutes in job_specs:
        for sequence, (name, capability, minutes) in enumerate(durations_by_component[component], start=1):
            operations.append(Operation(id=f"{job_id}-OP-{sequence}", job_id=job_id, name=name, sequence=sequence, eligible_machine_ids=[machine_for_capability[capability]], processing_time_minutes=minutes, setup_time_minutes=0, predecessor_id=f"{job_id}-OP-{sequence - 1}" if sequence > 1 else None, required_capability=capability, is_sample=True))
    db.add_all([*machines, *jobs, *operations]); _bump_version(db); db.commit()
    return {"message": "Automotive workflow sample loaded. These are simulated educational examples, labelled SAMPLE, and removable.", "jobs": len(jobs), "machines": len(machines), "operations": len(operations), "components": [job.component_type for job in jobs], "is_simulated": True}


@router.get("/knowledge-base")
def knowledge_base(db: Session = Depends(get_db)):
    jobs, machines, operations = _snapshot(db)
    latest = db.scalar(select(ScheduleRun).order_by(ScheduleRun.created_at.desc()).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    scheduled: list[dict] = []
    if latest and latest.dataset_version == _version(db):
        algorithm = latest.selected_algorithm_name or (latest.recommendation.recommended_algorithm_name if latest.recommendation else None)
        result = next((item for item in latest.results if item.algorithm_name == algorithm and item.feasible), None)
        if result:
            scheduled = result.result_payload.get("scheduled_operations", [])
    return build_knowledge_facts(jobs, machines, operations, scheduled)


@router.get("/planning/model")
def planning_model(db: Session = Depends(get_db)):
    jobs_raw, machines_raw, operations_raw = _snapshot(db)
    facts = build_knowledge_facts(jobs_raw, machines_raw, operations_raw)
    if not jobs_raw or not machines_raw or not operations_raw:
        return {"valid": False, "validation_errors": ["Add jobs, machines and operations to evaluate planning actions."], "facts": facts, "rules": list(RULES), "actions": []}
    try:
        validate_dataset(jobs_raw, machines_raw, operations_raw, "job_shop")
        jobs, machines, operations, predecessor, horizon = _prepare(jobs_raw, machines_raw, operations_raw)
        blackouts = _calendar_blackouts(machines, horizon)
        actions = applicable_actions(jobs, machines, operations, {}, predecessor, blackouts)
        names = {operation["id"]: operation["name"] for operation in operations}
        return {"valid": True, "validation_errors": [], "facts": facts, "rules": list(RULES), "actions": [{"name": f"Perform {names[action.operation_id]} on {action.machine_id}", "operation_id": action.operation_id, "machine_id": action.machine_id, "start_minute": action.start_minute, "end_minute": action.end_minute, "preconditions": list(action.preconditions), "effects": list(action.effects)} for action in actions]}
    except ValueError as exc:
        return {"valid": False, "validation_errors": [str(exc)], "facts": facts, "rules": list(RULES), "actions": []}


@router.post("/schedules/generate", status_code=201)
def generate_schedules(request: ScheduleRequest, db: Session = Depends(get_db)):
    jobs, machines, operations = _snapshot(db)
    try:
        validate_dataset(jobs, machines, operations, request.scenario)
    except DatasetError as exc:
        raise HTTPException(422, str(exc)) from exc
    if request.scenario == "permutation_flow_shop" and any(name != "NEH" for name in request.algorithms):
        raise HTTPException(422, "Permutation flow shop currently supports NEH only. Remove other algorithms or choose a supported scenario.")
    if request.scenario != "permutation_flow_shop" and "NEH" in request.algorithms:
        raise HTTPException(422, "NEH requires the explicitly supported permutation-flow-shop scenario; remove NEH or change the scenario.")
    run_id = str(uuid4()); dataset_version = _version(db)
    search_options = request.search_options.model_dump()
    results = [
        run_algorithm(
            name, jobs, machines, operations, request.scenario,
            search_options=search_options, hard_due_dates=request.hard_due_dates,
        )
        for name in request.algorithms
    ]
    for result in results:
        if request.hard_due_dates and result["feasible"]:
            late = [jid for jid, value in result["metrics"].get("job_lateness_minutes", {}).items() if value > 0]
            if late:
                result["feasible"] = False
                result["error_message"] = f"Hard due-date constraint violated by job(s): {', '.join(sorted(late))}."
    winner, reason, ranking = rank_results(results, request.objective, request.secondary_objectives)
    run = ScheduleRun(id=run_id, scenario=request.scenario, objective=request.objective, secondary_objectives=request.secondary_objectives, dataset_version=dataset_version, input_snapshot={"jobs": jobs, "machines": machines, "operations": operations, "scenario": request.scenario, "horizon_start": min(x["release_at"] for x in jobs), "hard_due_dates": request.hard_due_dates, "search_options": search_options}, selected_algorithm_name=None)
    db.add(run)
    db.flush()
    for item in results:
        payload = {"scheduled_operations": item.get("scheduled_operations", []), "search_stats": item.get("search_stats")}
        result_row = AlgorithmResult(run_id=run_id, algorithm_name=item["algorithm_name"], feasible=item["feasible"], metrics=item.get("metrics", {}), result_payload=payload, computation_time_ms=item["computation_time_ms"], error_message=item.get("error_message"))
        db.add(result_row); db.flush()
        for op in item.get("scheduled_operations", []):
            db.add(ScheduledOperation(result_id=result_row.id, operation_id=op["operation_id"], job_id=op["job_id"], machine_id=op["machine_id"], operation_name=op["operation_name"], sequence=op["sequence"], start_minute=op["start_minute"], end_minute=op["end_minute"], processing_time_minutes=op["processing_time_minutes"], setup_time_minutes=op["setup_time_minutes"], waiting_time_minutes=op["waiting_time_minutes"], due_at=op["due_at"], start_at=op["start_at"], end_at=op["end_at"]))
    db.add(Recommendation(run_id=run_id, recommended_algorithm_name=winner, reason=reason, details={"objective": request.objective, "secondary_objectives": request.secondary_objectives, "hard_due_dates": request.hard_due_dates, "ranking": ranking, "scope": "Best among the feasible algorithms evaluated for this dataset. This is not a guarantee of global optimality."}))
    db.commit()
    stored = db.scalar(select(ScheduleRun).where(ScheduleRun.id == run_id).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    if stored is None:
        _not_found("Schedule", run_id)
    return _run_payload(stored, db, True)


@router.get("/schedules")
def list_schedules(db: Session = Depends(get_db)):
    runs = db.scalars(select(ScheduleRun).order_by(ScheduleRun.created_at.desc())).all()
    return {"items": [_run_payload(run, db) for run in runs]}


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    run = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    if not run: _not_found("Schedule", schedule_id)
    return _run_payload(run, db, True)


@router.get("/schedules/{schedule_id}/comparison")
def get_comparison(schedule_id: str, db: Session = Depends(get_db)):
    run = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.results)))
    if not run: _not_found("Schedule", schedule_id)
    return {"schedule_id": run.id, "objective": run.objective, "hard_due_dates": bool(run.input_snapshot.get("hard_due_dates", False)), "algorithms": [{"algorithm_name": x.algorithm_name, "feasible": x.feasible, "metrics": x.metrics if x.feasible else {}, "objective_value": x.metrics.get(run.objective) if x.feasible else None, "constraint_violations": [] if x.feasible else [x.error_message or "No feasible schedule was produced for this algorithm."], "search_stats": x.result_payload.get("search_stats"), "computation_time_ms": x.computation_time_ms, "error_message": x.error_message} for x in run.results]}


@router.get("/schedules/{schedule_id}/gantt")
def get_gantt(schedule_id: str, algorithm_name: str | None = Query(default=None), db: Session = Depends(get_db)):
    run = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    if not run: _not_found("Schedule", schedule_id)
    selected = algorithm_name or run.selected_algorithm_name or (run.recommendation.recommended_algorithm_name if run.recommendation else None)
    result = next((x for x in run.results if x.algorithm_name == selected), None)
    if not result: raise HTTPException(404, f"No schedule result found for algorithm {selected or '(not selected)'}." )
    if not result.feasible: raise HTTPException(422, result.error_message or "This algorithm did not produce a feasible schedule; no Gantt is available.")
    return {"schedule_id": run.id, "algorithm_name": result.algorithm_name, "scenario": run.scenario, "feasible": result.feasible, "scheduled_operations": result.result_payload.get("scheduled_operations", [])}


@router.get("/schedules/{schedule_id}/recommendation")
def get_recommendation(schedule_id: str, db: Session = Depends(get_db)):
    run = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.recommendation)))
    if not run: _not_found("Schedule", schedule_id)
    if not run.recommendation: raise HTTPException(404, "Recommendation details are unavailable for this schedule.")
    return {"recommended_algorithm_name": run.recommendation.recommended_algorithm_name, "reason": run.recommendation.reason, "objective": run.objective, "hard_due_dates": bool(run.input_snapshot.get("hard_due_dates", False)), "scope": run.recommendation.details.get("scope"), "ranking": run.recommendation.details.get("ranking", []), "is_stale": run.dataset_version != _version(db)}


@router.post("/schedules/{schedule_id}/select")
def select_saved_schedule(schedule_id: str, payload: SelectScheduleInput, db: Session = Depends(get_db)):
    run = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    if not run: _not_found("Schedule", schedule_id)
    result = next((x for x in run.results if x.algorithm_name == payload.algorithm_name and x.feasible), None)
    if not result: raise HTTPException(422, "Choose a feasible algorithm result to save as the selected schedule.")
    run.selected_algorithm_name = payload.algorithm_name
    db.commit(); db.refresh(run)
    return {"schedule_id": run.id, "selected_algorithm_name": run.selected_algorithm_name, "is_stale": run.dataset_version != _version(db)}


def _disruption_payload(item: DisruptionEvent) -> dict:
    return {
        "id": item.id,
        "parent_schedule_id": item.parent_schedule_id,
        "revised_schedule_id": item.revised_schedule_id,
        "event_type": item.event_type,
        "effective_at": _iso(item.effective_at),
        "event_payload": item.event_payload,
        "impact": item.impact,
        "explanation": item.explanation,
        "created_at": _iso(item.created_at),
    }


@router.post("/schedules/{schedule_id}/reschedule", status_code=status.HTTP_201_CREATED)
def reschedule_saved_schedule(schedule_id: str, request: DynamicRescheduleInput, db: Session = Depends(get_db)):
    parent = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    if not parent:
        _not_found("Schedule", schedule_id)
    if parent.dataset_version != _version(db):
        raise HTTPException(409, "This saved schedule is outdated because manufacturing data changed. Generate a current schedule before applying a disruption.")
    if parent.scenario == "permutation_flow_shop":
        raise HTTPException(422, "Dynamic rescheduling currently supports Job Shop and Single-Operation / Parallel-Machine schedules. NEH permutation-flow-shop rescheduling is not implemented.")
    source_result = next((item for item in parent.results if item.algorithm_name == request.algorithm_name), None)
    if not source_result:
        raise HTTPException(404, f"Algorithm {request.algorithm_name} was not evaluated in the selected saved schedule.")
    if not source_result.feasible:
        raise HTTPException(422, "Choose a feasible algorithm result before applying a disruption.")
    if not source_result.result_payload.get("scheduled_operations"):
        raise HTTPException(422, "The saved result contains no operation schedule to revise.")

    event_id = str(uuid4())
    payload = request.model_dump(mode="json", exclude_none=True)
    payload["event_id"] = event_id
    try:
        plan = build_reschedule_plan(parent.input_snapshot, source_result.result_payload["scheduled_operations"], payload)
        validate_dataset(plan["jobs"], plan["machines"], plan["operations"], parent.scenario)
    except (DatasetError, RescheduleError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc

    result = run_algorithm(
        request.algorithm_name,
        plan["jobs"],
        plan["machines"],
        plan["operations"],
        parent.scenario,
        frozen_operations=plan["frozen_operations"],
        machine_blackouts=plan["machine_blackouts"],
        risk_machines=plan["risk_machines"],
        search_options=request.search_options.model_dump(),
        hard_due_dates=bool(parent.input_snapshot.get("hard_due_dates", False)),
    )
    if not result["feasible"]:
        raise HTTPException(422, f"The disruption could not be rescheduled without violating manufacturing constraints: {result['error_message']}")
    if parent.input_snapshot.get("hard_due_dates"):
        late = [jid for jid, value in result["metrics"].get("job_lateness_minutes", {}).items() if value > 0]
        if late:
            raise HTTPException(422, f"The revised schedule violates hard due dates for job(s): {', '.join(sorted(late))}. The event was not saved; adjust the repair window, machine choices or due constraints.")
    if len(result["scheduled_operations"]) != len(plan["operations"]):
        raise HTTPException(422, "The revised schedule did not contain every operation exactly once; no event or urgent order was saved.")

    impact = compare_schedules(
        source_result.result_payload["scheduled_operations"],
        result["scheduled_operations"],
        plan["affected_job_ids"],
        plan["affected_operation_ids"],
    )
    impact.update({
        "event_id": event_id,
        "event_type": request.event_type,
        "effective_at": _iso(request.effective_at),
        "algorithm_name": request.algorithm_name,
        "scenario": parent.scenario,
        "completed_operation_ids": plan["completed_operation_ids"],
        "locked_operation_ids": plan["locked_operation_ids"],
        "restarted_operation_ids": plan["restart_operation_ids"],
        "risk_fallback_operation_ids": result.get("risk_fallback_operation_ids", []),
        "metrics_before": source_result.metrics,
        "metrics_after": result["metrics"],
    })
    explanation = plan["explanation"]
    if plan["restart_operation_ids"]:
        explanation += " Restart-from-zero assumption applied to interrupted operation(s): " + ", ".join(plan["restart_operation_ids"]) + "."
    if result.get("risk_fallback_operation_ids"):
        explanation += " Warning: a reported high-risk machine remained the only feasible eligible assignment for operation(s): " + ", ".join(result["risk_fallback_operation_ids"]) + "."

    urgent_job_id = plan["event"].get("urgent_job_id")
    if urgent_job_id:
        urgent_job_request = request.urgent_job
        if urgent_job_request is None:
            raise HTTPException(422, "An urgent-order event requires a complete urgent job.")
        if db.get(Job, urgent_job_id):
            raise HTTPException(409, f"Urgent Job ID {urgent_job_id} already exists in the manufacturing workspace.")
        urgent_job = next(item for item in plan["jobs"] if item["id"] == urgent_job_id)
        for operation in plan["operations"]:
            if operation["job_id"] == urgent_job_id and db.get(Operation, operation["id"]):
                raise HTTPException(409, f"Urgent operation ID {operation['id']} already exists in the manufacturing workspace.")
        db.add(Job(
            id=urgent_job["id"], name=urgent_job["name"], product_name=urgent_job["product_name"],
            quantity=urgent_job["quantity"], priority="Critical", release_at=request.effective_at,
            due_at=urgent_job_request.due_at, component_type=urgent_job.get("component_type", "other"),
            status=urgent_job.get("status", "queued"), notes=urgent_job.get("notes"), is_sample=False,
        ))
        for op in plan["operations"]:
            if op["job_id"] == urgent_job_id:
                db.add(Operation(
                    id=op["id"], job_id=op["job_id"], name=op["name"], sequence=op["sequence"],
                    eligible_machine_ids=op["eligible_machine_ids"], processing_time_minutes=op["processing_time_minutes"],
                    setup_time_minutes=op["setup_time_minutes"], predecessor_id=op.get("predecessor_id"),
                    required_capability=op.get("required_capability"), is_sample=False,
                ))
        dataset_version = _bump_version(db)
    else:
        dataset_version = _version(db)

    run_id = str(uuid4())
    dynamic_details = {
        "event_id": event_id,
        "parent_schedule_id": parent.id,
        "event_type": request.event_type,
        "effective_at": _iso(request.effective_at),
        "affected_job_ids": impact["affected_job_ids"],
        "affected_operation_ids": impact["affected_operation_ids"],
        "moved_operation_ids": impact["moved_operation_ids"],
        "completed_operation_ids": plan["completed_operation_ids"],
        "locked_operation_ids": plan["locked_operation_ids"],
        "restarted_operation_ids": plan["restart_operation_ids"],
        "risk_fallback_operation_ids": result.get("risk_fallback_operation_ids", []),
        "stability_percent": impact["stability_percent"],
        "stability_definition": impact["stability_definition"],
        "metrics_before": source_result.metrics,
        "metrics_after": result["metrics"],
        "explanation": explanation,
    }
    input_snapshot = {
        "jobs": plan["jobs"], "machines": plan["machines"], "operations": plan["operations"],
        "scenario": parent.scenario, "horizon_start": plan["horizon_start"],
        "hard_due_dates": bool(parent.input_snapshot.get("hard_due_dates", False)),
        "search_options": request.search_options.model_dump(),
        "dynamic_event_history": plan["event_history"], "dynamic_reschedule": dynamic_details,
    }
    revised = ScheduleRun(
        id=run_id, scenario=parent.scenario, objective=parent.objective,
        secondary_objectives=parent.secondary_objectives, dataset_version=dataset_version,
        input_snapshot=input_snapshot, selected_algorithm_name=request.algorithm_name,
    )
    db.add(revised)
    db.flush()
    result_row = AlgorithmResult(
        run_id=run_id, algorithm_name=request.algorithm_name, feasible=True, metrics=result["metrics"],
        result_payload={"scheduled_operations": result["scheduled_operations"], "risk_fallback_operation_ids": result.get("risk_fallback_operation_ids", []), "search_stats": result.get("search_stats")},
        computation_time_ms=result["computation_time_ms"], error_message=None,
    )
    db.add(result_row)
    db.flush()
    for op in result["scheduled_operations"]:
        db.add(ScheduledOperation(
            result_id=result_row.id, operation_id=op["operation_id"], job_id=op["job_id"], machine_id=op["machine_id"],
            operation_name=op["operation_name"], sequence=op["sequence"], start_minute=op["start_minute"],
            end_minute=op["end_minute"], processing_time_minutes=op["processing_time_minutes"],
            setup_time_minutes=op["setup_time_minutes"], waiting_time_minutes=op["waiting_time_minutes"],
            due_at=op["due_at"], start_at=op["start_at"], end_at=op["end_at"],
        ))
    winner, reason, ranking = rank_results([result], parent.objective, parent.secondary_objectives)
    db.add(Recommendation(run_id=run_id, recommended_algorithm_name=winner, reason=reason, details={"objective": parent.objective, "secondary_objectives": parent.secondary_objectives, "ranking": ranking, "scope": "Revised schedule for the selected algorithm and this disruption; this is not a guarantee of global optimality."}))
    db.add(DisruptionEvent(
        id=event_id, parent_schedule_id=parent.id, revised_schedule_id=run_id, event_type=request.event_type,
        effective_at=request.effective_at, event_payload=payload, impact=impact, explanation=explanation,
    ))
    db.commit()
    stored = db.scalar(select(ScheduleRun).where(ScheduleRun.id == run_id).options(selectinload(ScheduleRun.results), selectinload(ScheduleRun.recommendation)))
    event_record = db.get(DisruptionEvent, event_id)
    if stored is None or event_record is None:
        _not_found("Revised schedule", run_id)
    return {"event": _disruption_payload(event_record), "run": _run_payload(stored, db, True)}


@router.get("/schedules/{schedule_id}/reschedules")
def list_reschedule_history(schedule_id: str, db: Session = Depends(get_db)):
    if not db.get(ScheduleRun, schedule_id):
        _not_found("Schedule", schedule_id)
    found: dict[str, DisruptionEvent] = {}
    cursor = schedule_id
    visited = {cursor}
    while True:
        prior = db.scalar(select(DisruptionEvent).where(DisruptionEvent.revised_schedule_id == cursor))
        if prior is None:
            break
        found[prior.id] = prior
        cursor = prior.parent_schedule_id
        if cursor in visited:
            break
        visited.add(cursor)
    children = db.scalars(select(DisruptionEvent).where(DisruptionEvent.parent_schedule_id == schedule_id).order_by(DisruptionEvent.created_at)).all()
    for item in children:
        found[item.id] = item
    ordered = sorted(found.values(), key=lambda item: (item.created_at, item.id))
    return {"items": [_disruption_payload(item) for item in ordered]}
