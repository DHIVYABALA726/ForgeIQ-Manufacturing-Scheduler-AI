from __future__ import annotations

from datetime import datetime, timedelta, timezone

BASE = "2034-03-18T08:00:00Z"


def _job(job_id: str, release: str = BASE, due: str = "2034-03-18T14:00:00Z", priority: str = "High"):
    return {"id": job_id, "name": f"Job {job_id}", "product_name": "Bracket", "quantity": 4, "priority": priority, "release_at": release, "due_at": due, "notes": ""}


def _machine(machine_id: str):
    return {"id": machine_id, "name": f"Machine {machine_id}", "machine_type": "CNC", "available_from": BASE, "available_until": None, "is_available": True, "setup_time_minutes": 0}


def _operation(operation_id: str, job_id: str, sequence: int, machines: list[str], minutes: int, predecessor: str | None = None):
    return {"id": operation_id, "job_id": job_id, "name": f"Operation {sequence}", "sequence": sequence, "eligible_machine_ids": machines, "processing_time_minutes": minutes, "setup_time_minutes": 0, "predecessor_id": predecessor}


def _shop(client):
    for job in [_job("J-1"), _job("J-2")]:
        assert client.post("/api/v1/jobs", json=job).status_code == 201
    for machine_id in ["M-1", "M-2"]:
        assert client.post("/api/v1/machines", json=_machine(machine_id)).status_code == 201
    operations = [
        _operation("OP-1", "J-1", 1, ["M-1"], 60),
        _operation("OP-2", "J-1", 2, ["M-2"], 20, "OP-1"),
        _operation("OP-3", "J-2", 1, ["M-1", "M-2"], 30),
    ]
    for operation in operations:
        assert client.post("/api/v1/operations", json=operation).status_code == 201
    created = client.post("/api/v1/schedules/generate", json={"scenario": "job_shop", "algorithms": ["FCFS", "Priority-Based"], "objective": "makespan", "secondary_objectives": [], "hard_due_dates": False})
    assert created.status_code == 201, created.text
    return created.json()


def _post_event(client, run, event_type: str, **fields):
    return client.post(f"/api/v1/schedules/{run['id']}/reschedule", json={"event_type": event_type, "effective_at": "2034-03-18T08:15:00Z", "algorithm_name": "FCFS", **fields})


def _ops(run):
    return {item["operation_id"]: item for item in run["results"][0]["scheduled_operations"]}


def test_breakdown_restarts_interrupted_operation_respects_repair_and_keeps_parent_immutable(client):
    parent = _shop(client)
    source = _ops(parent)
    revised = _post_event(client, parent, "machine_breakdown", machine_id="M-1", repair_until="2034-03-18T09:00:00Z")
    assert revised.status_code == 201, revised.text
    body = revised.json()
    after = _ops(body["run"])
    assert len(after) == len(source) == 3
    assert after["OP-1"]["start_at"] >= "2034-03-18T09:00:00"
    assert body["event"]["impact"]["restarted_operation_ids"] == ["OP-1"]
    assert "restarted with its full processing duration" in body["event"]["explanation"]
    assert body["event"]["impact"]["stability_percent"] <= 100
    for item in after.values():
        if item["machine_id"] == "M-1":
            assert item["end_at"] <= "2034-03-18T08:15:00" or item["start_at"] >= "2034-03-18T09:00:00"
    saved_source = client.get(f"/api/v1/schedules/{parent['id']}").json()
    assert _ops(saved_source) == source
    events = client.get(f"/api/v1/schedules/{body['run']['id']}/reschedules").json()["items"]
    assert [item["id"] for item in events] == [body["event"]["id"]]


def test_scheduled_maintenance_blocks_only_its_selected_window(client):
    parent = _shop(client)
    response = _post_event(client, parent, "maintenance", machine_id="M-1", repair_until="2034-03-18T08:45:00Z")
    assert response.status_code == 201, response.text
    revised = _ops(response.json()["run"])
    assert revised["OP-1"]["start_at"] >= "2034-03-18T08:45:00"
    assert response.json()["run"]["results"][0]["metrics"]["idle_time_minutes"] is not None
    assert response.json()["run"]["results"][0]["metrics"]["setup_time_minutes"] >= 0


def test_processing_delay_extends_active_task_and_moves_its_predecessors(client):
    parent = _shop(client)
    before = _ops(parent)
    response = _post_event(client, parent, "processing_delay", operation_id="OP-1", delay_minutes=15)
    assert response.status_code == 201, response.text
    after = _ops(response.json()["run"])
    assert after["OP-1"]["start_at"] == before["OP-1"]["start_at"]
    assert after["OP-1"]["end_minute"] == before["OP-1"]["end_minute"] + 15
    assert after["OP-2"]["start_minute"] >= after["OP-1"]["end_minute"]
    assert response.json()["event"]["impact"]["moved_operation_ids"] == ["OP-1", "OP-2"]


def test_urgent_multistep_order_is_critical_persisted_and_included_only_after_success(client):
    parent = _shop(client)
    urgent_id = "J-URGENT"
    response = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={
        "event_type": "urgent_order", "effective_at": "2034-03-18T08:15:00Z", "algorithm_name": "Priority-Based",
        "urgent_job": {**_job(urgent_id, "2034-03-18T08:15:00Z", "2034-03-18T12:00:00Z", "Low"), "name": "Urgent repair"},
        "urgent_operations": [
            _operation(f"{urgent_id}-op-1", urgent_id, 1, ["M-1"], 20),
            _operation(f"{urgent_id}-op-2", urgent_id, 2, ["M-2"], 10, f"{urgent_id}-op-1"),
        ],
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert client.get(f"/api/v1/jobs/{urgent_id}").json()["priority"] == "Critical"
    stored_ops = client.get("/api/v1/operations").json()["items"]
    assert sum(item["job_id"] == urgent_id for item in stored_ops) == 2
    revised = _ops(body["run"])
    assert set(revised) == {"OP-1", "OP-2", "OP-3", f"{urgent_id}-op-1", f"{urgent_id}-op-2"}
    source_after = client.get(f"/api/v1/schedules/{parent['id']}").json()
    assert {item["id"] for item in source_after["input_snapshot"]["jobs"]} == {"J-1", "J-2"}
    assert source_after["is_stale"] is True
    assert body["run"]["is_stale"] is False
    assert body["run"]["input_snapshot"]["jobs"][-1]["id"] == urgent_id
    assert body["event"]["impact"]["added_operation_ids"] == [f"{urgent_id}-op-1", f"{urgent_id}-op-2"]


def test_high_risk_event_prefers_safe_eligible_machine(client):
    assert client.post("/api/v1/jobs", json=_job("J-RISK")).status_code == 201
    for machine_id in ["M-1", "M-2"]:
        assert client.post("/api/v1/machines", json=_machine(machine_id)).status_code == 201
    assert client.post("/api/v1/operations", json=_operation("OP-RISK", "J-RISK", 1, ["M-1", "M-2"], 25)).status_code == 201
    base = client.post("/api/v1/schedules/generate", json={"scenario": "parallel_machine", "algorithms": ["FCFS"], "objective": "makespan"}).json()
    assert _ops(base)["OP-RISK"]["machine_id"] == "M-1"
    response = client.post(f"/api/v1/schedules/{base['id']}/reschedule", json={"event_type": "machine_risk", "effective_at": BASE, "algorithm_name": "FCFS", "machine_id": "M-1", "risk_note": "Operator vibration report"})
    assert response.status_code == 201, response.text
    revised = response.json()
    assert _ops(revised["run"])["OP-RISK"]["machine_id"] == "M-2"
    assert revised["event"]["event_payload"]["risk_note"] == "Operator vibration report"


def test_high_risk_fallback_is_explicit_if_only_risky_machine_is_eligible(client):
    assert client.post("/api/v1/jobs", json=_job("J-ONLY")).status_code == 201
    assert client.post("/api/v1/machines", json=_machine("M-1")).status_code == 201
    assert client.post("/api/v1/operations", json=_operation("OP-ONLY", "J-ONLY", 1, ["M-1"], 25)).status_code == 201
    base = client.post("/api/v1/schedules/generate", json={"scenario": "parallel_machine", "algorithms": ["FCFS"], "objective": "makespan"}).json()
    response = client.post(f"/api/v1/schedules/{base['id']}/reschedule", json={"event_type": "machine_risk", "effective_at": BASE, "algorithm_name": "FCFS", "machine_id": "M-1"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["run"]["results"][0]["risk_fallback_operation_ids"] == ["OP-ONLY"]
    assert "only feasible eligible assignment" in body["event"]["explanation"]


def test_completed_operations_are_locked_and_unavailable_after_invalid_run_rejected(client):
    parent = _shop(client)
    before = _ops(parent)
    response = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={
        "event_type": "machine_risk", "effective_at": "2034-03-18T09:00:00Z", "algorithm_name": "FCFS", "machine_id": "M-2",
    })
    assert response.status_code == 201, response.text
    after = _ops(response.json()["run"])
    impact = response.json()["event"]["impact"]
    assert {"OP-1", "OP-3"}.issubset(set(impact["completed_operation_ids"]))
    for operation_id in ["OP-1", "OP-3"]:
        assert after[operation_id]["machine_id"] == before[operation_id]["machine_id"]
        assert after[operation_id]["start_at"] == before[operation_id]["start_at"]
        assert after[operation_id]["end_at"] == before[operation_id]["end_at"]


def test_infeasible_outage_saves_neither_event_nor_partial_revision(client):
    assert client.post("/api/v1/jobs", json=_job("J-OUTAGE")).status_code == 201
    machine = _machine("M-1")
    machine["available_until"] = "2034-03-18T12:00:00Z"
    assert client.post("/api/v1/machines", json=machine).status_code == 201
    assert client.post("/api/v1/operations", json=_operation("OP-OUTAGE", "J-OUTAGE", 1, ["M-1"], 60)).status_code == 201
    parent = client.post("/api/v1/schedules/generate", json={"scenario": "parallel_machine", "algorithms": ["FCFS"], "objective": "makespan"}).json()
    response = _post_event(client, parent, "machine_breakdown", machine_id="M-1", repair_until="2034-03-19T08:00:00Z")
    assert response.status_code == 422
    assert "could not be rescheduled" in response.json()["detail"]
    assert client.get(f"/api/v1/schedules/{parent['id']}/reschedules").json()["items"] == []
    schedules = client.get("/api/v1/schedules").json()["items"]
    assert len(schedules) == 1
    assert [item["id"] for item in client.get("/api/v1/jobs").json()["items"]] == ["J-OUTAGE"]


def test_infeasible_urgent_order_is_not_persisted(client):
    assert client.post("/api/v1/jobs", json=_job("J-LIMITED")).status_code == 201
    machine = _machine("M-1")
    machine["available_until"] = "2034-03-18T12:00:00Z"
    assert client.post("/api/v1/machines", json=machine).status_code == 201
    assert client.post("/api/v1/operations", json=_operation("OP-LIMITED", "J-LIMITED", 1, ["M-1"], 60)).status_code == 201
    parent = client.post("/api/v1/schedules/generate", json={"scenario": "parallel_machine", "algorithms": ["FCFS"], "objective": "makespan"}).json()
    urgent_id = "J-URGENT-TOO-LATE"
    response = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={
        "event_type": "urgent_order", "effective_at": "2034-03-18T08:15:00Z", "algorithm_name": "FCFS",
        "urgent_job": _job(urgent_id, "2034-03-18T08:15:00Z", "2034-03-18T14:00:00Z", "Low"),
        "urgent_operations": [_operation(f"{urgent_id}-op-1", urgent_id, 1, ["M-1"], 300)],
    })
    assert response.status_code == 422
    assert client.get(f"/api/v1/jobs/{urgent_id}").status_code == 404
    assert [item["id"] for item in client.get("/api/v1/operations").json()["items"]] == ["OP-LIMITED"]
    assert client.get(f"/api/v1/schedules/{parent['id']}/reschedules").json()["items"] == []
    assert len(client.get("/api/v1/schedules").json()["items"]) == 1


def test_dynamic_request_rejects_neh_and_stale_base(client):
    # NEH stays scoped to permutation-flow-shop; it is never presented as a dynamic rule.
    job = _job("J-NEH")
    machine = _machine("M-1")
    op = _operation("OP-NEH", "J-NEH", 1, ["M-1"], 10)
    for route, record in [("/api/v1/jobs", job), ("/api/v1/machines", machine), ("/api/v1/operations", op)]:
        assert client.post(route, json=record).status_code == 201
    base = client.post("/api/v1/schedules/generate", json={"scenario": "permutation_flow_shop", "algorithms": ["NEH"], "objective": "makespan"}).json()
    response = client.post(f"/api/v1/schedules/{base['id']}/reschedule", json={"event_type": "maintenance", "effective_at": BASE, "algorithm_name": "NEH", "machine_id": "M-1", "repair_until": "2034-03-18T09:00:00Z"})
    assert response.status_code == 422
    assert "not implemented" in response.json()["detail"]

    parent = base
    assert client.put("/api/v1/machines/M-1", json={**_machine("M-1"), "setup_time_minutes": 4}).status_code == 200
    stale = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={"event_type": "machine_breakdown", "effective_at": "2034-03-18T08:15:00Z", "algorithm_name": "FCFS", "machine_id": "M-1", "repair_until": "2034-03-18T09:00:00Z"})
    assert stale.status_code == 409
    assert "outdated" in stale.json()["detail"]
