from __future__ import annotations

from datetime import datetime, timedelta

BASE = "2035-07-21T08:00:00Z"


def _job(job_id: str = "AUTO-ENG", due: str = "2035-07-21T12:00:00Z"):
    return {
        "id": job_id, "name": "Engine block machining", "product_name": "Automotive engine block",
        "quantity": 4, "priority": "High", "component_type": "engine_block", "status": "queued",
        "release_at": BASE, "due_at": due, "notes": "Test fixture",
    }


def _machine():
    return {
        "id": "M-MILL", "name": "CNC milling cell", "machine_type": "CNC",
        "available_from": BASE, "available_until": None, "is_available": True,
        "setup_time_minutes": 0, "processing_capabilities": ["cnc_milling"],
        "maintenance_schedule": [{
            "starts_at": "2035-07-21T08:00:00Z", "ends_at": "2035-07-21T08:20:00Z", "reason": "planned service",
        }],
    }


def _operation(operation_id="ENG-OP1", job_id="AUTO-ENG", sequence=1, predecessor=None, minutes=15):
    return {
        "id": operation_id, "job_id": job_id, "name": "Cylinder block milling", "sequence": sequence,
        "eligible_machine_ids": ["M-MILL"], "processing_time_minutes": minutes,
        "setup_time_minutes": 0, "predecessor_id": predecessor, "required_capability": "cnc_milling",
    }


def _create(client, jobs, operations):
    for route, item in [("/api/v1/jobs", jobs), ("/api/v1/machines", _machine())]:
        assert client.post(route, json=item).status_code == 201
    for operation in operations:
        assert client.post("/api/v1/operations", json=operation).status_code == 201


def test_search_settings_and_stats_persist_with_automotive_calendar_constraints(client):
    _create(client, _job(), [_operation()])
    settings = {
        "max_expansions": 120, "max_seconds": 1.25,
        "weights": {"makespan": 1, "total_tardiness": 2, "idle_time": 0, "setup_time": 0.5, "machine_risk": 0},
    }
    response = client.post("/api/v1/schedules/generate", json={
        "scenario": "parallel_machine", "algorithms": ["A* Search", "Uniform Cost Search", "Greedy Best-First"],
        "objective": "makespan", "hard_due_dates": False, "search_options": settings,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["input_snapshot"]["search_options"] == settings
    for result in body["results"]:
        assert result["feasible"] is True
        assert result["search_stats"]["max_expansions"] == 120
        assert result["search_stats"]["max_seconds"] == 1.25
        assert result["search_stats"]["states_expanded"] >= 0
        assert result["search_stats"]["states_generated"] >= 1
        assert result["computation_time_ms"] >= 0
        assert result["scheduled_operations"][0]["start_minute"] >= 20
    astar = next(item for item in body["results"] if item["algorithm_name"] == "A* Search")
    assert astar["search_stats"]["optimality_proven"] is True
    assert client.get(f"/api/v1/schedules/{body['id']}").json()["results"][0]["search_stats"]
    comparison = client.get(f"/api/v1/schedules/{body['id']}/comparison").json()
    assert comparison["algorithms"][0]["search_stats"]["termination_status"] == "optimal"

    facts = client.get("/api/v1/knowledge-base").json()
    assert facts["facts"]["jobs"][0]["component_type"] == "engine_block"
    assert facts["facts"]["compatible"] == [{"operation_id": "ENG-OP1", "machine_id": "M-MILL", "required_capability": "cnc_milling"}]
    assert facts["facts"]["finished"] == [{"operation_id": "ENG-OP1", "at_minute": astar["scheduled_operations"][0]["end_minute"]}]


def test_dynamic_disruption_reuses_bounded_search_and_preserves_original_automotive_snapshot(client):
    _create(client, _job(), [
        _operation("ENG-OP1", sequence=1, minutes=15),
        _operation("ENG-OP2", sequence=2, predecessor="ENG-OP1", minutes=20),
    ])
    original_settings = {"max_expansions": 100, "max_seconds": 2, "weights": {"makespan": 1, "total_tardiness": 1, "idle_time": 0, "setup_time": 0, "machine_risk": 0}}
    parent_response = client.post("/api/v1/schedules/generate", json={
        "scenario": "job_shop", "algorithms": ["A* Search"], "objective": "makespan", "search_options": original_settings,
    })
    assert parent_response.status_code == 201, parent_response.text
    parent = parent_response.json()
    revised_settings = {"max_expansions": 70, "max_seconds": 1.5, "weights": {"makespan": 0, "total_tardiness": 2, "idle_time": 0, "setup_time": 0, "machine_risk": 0}}
    response = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={
        "event_type": "machine_breakdown", "effective_at": "2035-07-21T08:25:00Z",
        "algorithm_name": "A* Search", "machine_id": "M-MILL", "repair_until": "2035-07-21T08:40:00Z",
        "search_options": revised_settings,
    })
    assert response.status_code == 201, response.text
    revised = response.json()["run"]
    assert revised["input_snapshot"]["search_options"] == revised_settings
    result = revised["results"][0]
    assert result["algorithm_name"] == "A* Search"
    assert result["search_stats"]["max_expansions"] == 70
    assert result["search_stats"]["max_seconds"] == 1.5
    assert result["scheduled_operations"][0]["start_minute"] >= 40
    assert revised["input_snapshot"]["jobs"][0]["component_type"] == "engine_block"
    assert client.get(f"/api/v1/schedules/{parent['id']}").json()["input_snapshot"]["search_options"] == original_settings
    assert client.get(f"/api/v1/schedules/{revised['id']}").json()["results"][0]["search_stats"]["max_expansions"] == 70


def test_opt_in_automotive_sample_to_ai_plan_and_breakdown_smoke(client):
    workflows = client.get("/api/v1/automotive/workflows")
    assert workflows.status_code == 200
    assert set(workflows.json()["workflows"]) == {"engine_block", "crankshaft", "brake_disc"}

    loaded = client.post("/api/v1/automotive/sample")
    assert loaded.status_code == 201, loaded.text
    sample = loaded.json()
    assert sample["is_simulated"] is True
    assert (sample["jobs"], sample["machines"], sample["operations"]) == (3, 5, 9)
    assert set(sample["components"]) == {"engine_block", "crankshaft", "brake_disc"}
    assert all(item["is_sample"] for route in ("jobs", "machines", "operations") for item in client.get(f"/api/v1/{route}").json()["items"])

    knowledge = client.get("/api/v1/knowledge-base").json()
    assert len(knowledge["facts"]["compatible"]) == 9
    model = client.get("/api/v1/planning/model").json()
    assert model["valid"] is True
    assert all(action["preconditions"] and action["effects"] for action in model["actions"])

    options = {"max_expansions": 1500, "max_seconds": 3, "weights": {"makespan": 1, "total_tardiness": 1, "idle_time": 0, "setup_time": 0, "machine_risk": 0}}
    response = client.post("/api/v1/schedules/generate", json={
        "scenario": "job_shop", "algorithms": ["A* Search", "FCFS"], "objective": "makespan", "search_options": options,
    })
    assert response.status_code == 201, response.text
    parent = response.json()
    ai_result = next(result for result in parent["results"] if result["algorithm_name"] == "A* Search")
    assert ai_result["feasible"] is True
    assert len(ai_result["scheduled_operations"]) == 9
    assert ai_result["search_stats"]["states_generated"] > 0

    first = min(ai_result["scheduled_operations"], key=lambda item: item["start_minute"])
    event_time = datetime.fromisoformat(first["start_at"].replace("Z", "+00:00")) + timedelta(minutes=5)
    repair_time = event_time + timedelta(minutes=10)
    event_response = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={
        "event_type": "machine_breakdown", "effective_at": event_time.isoformat(), "algorithm_name": "A* Search",
        "machine_id": first["machine_id"], "repair_until": repair_time.isoformat(), "search_options": options,
    })
    assert event_response.status_code == 201, event_response.text
    revised = event_response.json()["run"]
    revised_ai = next(result for result in revised["results"] if result["algorithm_name"] == "A* Search")
    assert revised_ai["feasible"] is True
    assert len(revised_ai["scheduled_operations"]) == 9
    assert revised_ai["search_stats"]["max_expansions"] == 1500
    assert client.get(f"/api/v1/schedules/{parent['id']}").json()["id"] == parent["id"]
    history = client.get(f"/api/v1/schedules/{parent['id']}/reschedules").json()
    assert any(item["revised_schedule_id"] == revised["id"] for item in history["items"])


def test_search_rescheduling_commits_urgent_automotive_order_only_with_a_complete_result(client):
    _create(client, _job(), [
        _operation("ENG-OP1", sequence=1, minutes=15),
        _operation("ENG-OP2", sequence=2, predecessor="ENG-OP1", minutes=20),
    ])
    settings = {"max_expansions": 100, "max_seconds": 1.5, "weights": {"makespan": 1, "total_tardiness": 1, "idle_time": 0, "setup_time": 0, "machine_risk": 0}}
    parent_response = client.post("/api/v1/schedules/generate", json={
        "scenario": "job_shop", "algorithms": ["A* Search"], "objective": "makespan", "search_options": settings,
    })
    assert parent_response.status_code == 201, parent_response.text
    parent = parent_response.json()
    urgent_job_id = "AUTO-URGENT"
    urgent_order = {
        **_job(urgent_job_id, due="2035-07-21T11:00:00Z"),
        "name": "Urgent engine-block repair batch", "component_type": "engine_block", "priority": "Critical",
    }
    revised_settings = {"max_expansions": 60, "max_seconds": 1, "weights": {"makespan": 1, "total_tardiness": 2, "idle_time": 0, "setup_time": 0, "machine_risk": 0}}
    response = client.post(f"/api/v1/schedules/{parent['id']}/reschedule", json={
        "event_type": "urgent_order", "effective_at": "2035-07-21T09:00:00Z", "algorithm_name": "A* Search",
        "urgent_job": urgent_order,
        "urgent_operations": [_operation("URG-OP1", job_id=urgent_job_id, sequence=1, minutes=10)],
        "search_options": revised_settings,
    })
    assert response.status_code == 201, response.text
    revised = response.json()["run"]
    result = next(item for item in revised["results"] if item["algorithm_name"] == "A* Search")
    assert result["feasible"] is True
    assert result["search_stats"]["max_expansions"] == 60
    urgent_operation = next(item for item in result["scheduled_operations"] if item["operation_id"] == "URG-OP1")
    assert urgent_operation["start_minute"] >= 60
    assert revised["input_snapshot"]["search_options"] == revised_settings
    assert any(job["id"] == urgent_job_id and job["priority"] == "Critical" for job in revised["input_snapshot"]["jobs"])
    assert client.get(f"/api/v1/schedules/{parent['id']}").json()["input_snapshot"]["jobs"] == parent["input_snapshot"]["jobs"]
