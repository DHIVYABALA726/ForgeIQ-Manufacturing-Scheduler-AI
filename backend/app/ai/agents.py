from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4

def analyze(jobs: list[dict], machines: list[dict], operations: list[dict], schedule: dict | None = None, *, machine_id: str | None = None, risk_probability: float = 0.0, knowledge_facts: dict | None = None, applicable_planning_actions: list[dict] | None = None, disruption_evidence: dict | None = None) -> dict:
    ops_by_machine: dict[str, list[dict]] = {m["id"]: [] for m in machines}
    if schedule and schedule.get("feasible"):
        for row in schedule.get("scheduled_operations", []):
            ops_by_machine.setdefault(row["machine_id"], []).append(row)
    available = {m["id"]: bool(m.get("is_available")) for m in machines}
    target = next((m for m in machines if m["id"] == machine_id), None) if machine_id else None
    activities = []
    def entry(agent, status, evidence, explanation):
        activities.append({"id": str(uuid4()), "time": datetime.now(timezone.utc).isoformat(), "agent": agent, "status": status, "evidence": evidence, "explanation": explanation})
    entry("Production planner", "ready" if schedule and schedule.get("feasible") else "needs-data", {"jobs": len(jobs), "operations": len(operations), "feasible_schedule": bool(schedule and schedule.get("feasible")), "applicable_planning_actions": len(applicable_planning_actions or [])}, "Inspected the current dataset, latest selected schedule and existing planning preconditions; no schedule was changed.")
    entry("Machine availability monitor", "attention" if target and not available.get(target["id"], False) else "ready", {"machine_id": target["id"] if target else None, "available": available.get(target["id"]) if target else None, "machines_available": sum(available.values())}, "Availability is read-only; this agent never changes machine state.")
    entry("Disruption response", "advisory" if risk_probability >= .15 or disruption_evidence else "ready", {"risk_probability": round(risk_probability, 4), "latest_saved_disruption": disruption_evidence}, "Risk signal and saved disruption history are advisory; rescheduling requires an explicit operator action in the existing workflow.")
    entry("Decision coordinator", "ready", {"selected_machine": machine_id, "scheduled_machine_loads": {k: len(v) for k,v in ops_by_machine.items()}}, "Summarized evidence and constraints; no automatic commit or reschedule was attempted.")
    entry("Monitoring and coordination", "ready", {"knowledge_facts_available": bool(knowledge_facts), "dataset_counts": {"jobs":len(jobs),"machines":len(machines),"operations":len(operations)}}, "Coordinates deterministic evidence from the existing knowledge base and monitoring inputs.")
    return {"run_id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), "agents": activities, "activities": activities, "schedule_change_performed": False,
            "recommendation": "Review the schedule evidence, then use Dynamic Rescheduling only after explicit operator confirmation."}
