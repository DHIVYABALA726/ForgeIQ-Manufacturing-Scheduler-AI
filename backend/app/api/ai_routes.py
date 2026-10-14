from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import AlgorithmResult, DisruptionEvent, Job, Machine, Operation, ScheduleRun
from ..scheduling.engine import run_algorithm, SEARCH_ALGORITHMS, _prepare, _calendar_blackouts
from ..scheduling.recommendation import rank_results
from ..scheduling.knowledge import build_knowledge_facts
from ..scheduling.planning import applicable_actions
from ..ai.schemas import AgentAnalysis, RiskRequest, SearchExperiment
from ..ai.search_trace import SearchTrace, finalize_trace, trace_store
from ..ai.bayesian_risk import infer_risk
from ..ai.agents import analyze
from ..ai.recommendations import SUPPORTED, compare

router = APIRouter(prefix="/api/v1")

def _current(db: Session):
    jobs = [{"id":x.id,"name":x.name,"product_name":x.product_name,"quantity":x.quantity,"priority":x.priority,"release_at":x.release_at.isoformat(),"due_at":x.due_at.isoformat(),"component_type":x.component_type,"status":x.status,"notes":x.notes,"is_sample":x.is_sample} for x in db.scalars(select(Job).order_by(Job.id)).all()]
    machines = [{"id":x.id,"name":x.name,"machine_type":x.machine_type,"available_from":x.available_from.isoformat(),"available_until":x.available_until.isoformat() if x.available_until else None,"is_available":x.is_available,"setup_time_minutes":x.setup_time_minutes,"processing_capabilities":x.processing_capabilities or [],"maintenance_schedule":x.maintenance_schedule or [],"is_sample":x.is_sample} for x in db.scalars(select(Machine).order_by(Machine.id)).all()]
    operations = [{"id":x.id,"job_id":x.job_id,"name":x.name,"sequence":x.sequence,"eligible_machine_ids":x.eligible_machine_ids,"processing_time_minutes":x.processing_time_minutes,"setup_time_minutes":x.setup_time_minutes,"predecessor_id":x.predecessor_id,"required_capability":x.required_capability,"is_sample":x.is_sample} for x in db.scalars(select(Operation).order_by(Operation.job_id,Operation.sequence)).all()]
    return jobs,machines,operations

def _source(db: Session, source: str, schedule_id: str | None):
    if source == "current": return (*_current(db), None)
    if source != "saved_run" or not schedule_id: raise HTTPException(422,"Select current data or provide a saved schedule ID.")
    run = db.scalar(select(ScheduleRun).where(ScheduleRun.id == schedule_id).options(selectinload(ScheduleRun.results),selectinload(ScheduleRun.recommendation)))
    if not run: raise HTTPException(404,"Saved schedule was not found.")
    snap=run.input_snapshot
    return snap.get("jobs",[]),snap.get("machines",[]),snap.get("operations",[]),run

def _saved_results(run):
    return [{"algorithm_name":x.algorithm_name,"scenario":run.scenario,"feasible":x.feasible,"scheduled_operations":x.result_payload.get("scheduled_operations",[]) if x.feasible else [],"metrics":x.metrics if x.feasible else {},"computation_time_ms":x.computation_time_ms,"search_stats":x.result_payload.get("search_stats"),"error_message":x.error_message} for x in run.results]

@router.get("/ai-center")
def ai_center(db: Session = Depends(get_db)):
    jobs,machines,operations=_current(db)
    latest=db.scalar(select(ScheduleRun).order_by(ScheduleRun.created_at.desc()).options(selectinload(ScheduleRun.results),selectinload(ScheduleRun.recommendation)))
    saved=None
    if latest:
        saved=next((x for x in _saved_results(latest) if x["algorithm_name"]==(latest.selected_algorithm_name or (latest.recommendation.recommended_algorithm_name if latest.recommendation else None))),None)
    event=db.scalar(select(DisruptionEvent).order_by(DisruptionEvent.created_at.desc()))
    return {"counts":{"jobs":len(jobs),"machines":len(machines),"operations":len(operations)},"latest_schedule":{"id":latest.id,"created_at":latest.created_at.isoformat(),"scenario":latest.scenario,"objective":latest.objective,"recommended_algorithm_name":latest.recommendation.recommended_algorithm_name if latest and latest.recommendation else None,"result":saved} if latest else None,"latest_reschedule_event":{"id":event.id,"event_type":event.event_type,"created_at":event.created_at.isoformat(),"explanation":event.explanation} if event else None,"latest_trace":trace_store.latest(),"boundaries":["Search traces and agent activity are bounded process-local memory and disappear on restart.","Bayesian CPT values are illustrative assumptions, not calibrated factory predictions."]}

@router.post("/ai-search")
def ai_search(request: SearchExperiment, db: Session = Depends(get_db)):
    jobs,machines,operations,run=_source(db,request.dataset_source,request.schedule_id)
    scenario=run.scenario if run and request.dataset_source=="saved_run" else request.scenario
    if scenario not in SUPPORTED: raise HTTPException(422,"Unsupported scheduling scenario.")
    traces=[]; results=[]
    for algorithm in request.algorithms:
        if algorithm not in SEARCH_ALGORITHMS: raise HTTPException(422,f"{algorithm} is not a state-space search method.")
        if algorithm not in SUPPORTED[scenario]: raise HTTPException(422,f"{algorithm} is not applicable to {scenario}.")
        trace=SearchTrace(max_nodes=request.max_trace_nodes)
        result=run_algorithm(algorithm,jobs,machines,operations,scenario,search_options={"max_expansions":request.max_expansions,"max_seconds":request.max_seconds},hard_due_dates=request.hard_due_dates,trace_collector=trace)
        results.append(result)
        traces.append(finalize_trace(trace,result,dataset_source=request.dataset_source,scenario=scenario,objective=request.objective,algorithm=algorithm))
    return {"dataset_source":request.dataset_source,"schedule_id":run.id if run else None,"scenario":scenario,"objective":request.objective,"results":results,"traces":[{"trace_id":t["trace_id"],"algorithm":t["algorithm"],"nodes":t["nodes"],"edges":t["edges"],"truncated":t["truncated"],"result":t["result"]} for t in traces]}

@router.get("/ai-search-traces/{trace_id}")
def get_trace(trace_id:str):
    result=trace_store.get(trace_id)
    if result is None: raise HTTPException(404,"Search trace is missing or expired; run the experiment again.")
    return result

@router.post("/ai-recommendations")
def recommendations(request:SearchExperiment,db:Session=Depends(get_db)):
    jobs,machines,operations,run=_source(db,request.dataset_source,request.schedule_id)
    scenario=run.scenario if run and request.dataset_source=="saved_run" else request.scenario
    algorithms=request.algorithms or SUPPORTED.get(scenario,[])
    results=[run_algorithm(a,jobs,machines,operations,scenario,search_options={"max_expansions":request.max_expansions,"max_seconds":request.max_seconds},hard_due_dates=request.hard_due_dates) for a in algorithms if a in SUPPORTED.get(scenario,[])]
    if run and not algorithms: results=_saved_results(run)
    outcome=compare(results,request.objective,scenario)
    outcome["dataset_source"]=request.dataset_source
    return outcome

@router.post("/agents")
def agent_analysis(request:AgentAnalysis,db:Session=Depends(get_db)):
    jobs,machines,operations,run=_source(db,request.dataset_source,request.schedule_id)
    selected=None
    if run:
        selected=next((x for x in _saved_results(run) if x["algorithm_name"]==(run.selected_algorithm_name or (run.recommendation.recommended_algorithm_name if run.recommendation else None))),None)
    evidence={"maintenance":request.maintenance,"high_workload":request.high_workload,"recent_disruption":request.recent_disruption}
    risk=infer_risk(evidence)["risk_probability"]
    facts=build_knowledge_facts(jobs,machines,operations,selected.get("scheduled_operations",[]) if selected else [])
    available_actions=[]
    if jobs and machines and operations:
        try:
            prepared_jobs,prepared_machines,prepared_ops,predecessor,horizon=_prepare(jobs,machines,operations)
            blackouts=_calendar_blackouts(prepared_machines,horizon)
            available_actions=[{"operation_id":a.operation_id,"machine_id":a.machine_id,"start_minute":a.start_minute,"end_minute":a.end_minute} for a in applicable_actions(prepared_jobs,prepared_machines,prepared_ops,{},predecessor,blackouts)]
        except (ValueError,KeyError,TypeError):
            available_actions=[]
    event=db.scalar(select(DisruptionEvent).order_by(DisruptionEvent.created_at.desc()))
    disruption={"event_type":event.event_type,"created_at":event.created_at.isoformat(),"explanation":event.explanation} if event else None
    result=analyze(jobs,machines,operations,selected,machine_id=request.machine_id,risk_probability=risk,knowledge_facts=facts,applicable_planning_actions=available_actions,disruption_evidence=disruption)
    result["dataset_source"]=request.dataset_source
    result["planning_actions"]=available_actions
    result["knowledge_facts"]=facts
    return result

@router.post("/bayesian-risk")
def bayesian_risk(request:RiskRequest):
    try: return infer_risk(request.evidence)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc

@router.get("/bayesian-risk")
def bayesian_model():
    return infer_risk({})
