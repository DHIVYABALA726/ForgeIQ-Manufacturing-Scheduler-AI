from app.ai.bayesian_risk import infer_risk
from app.ai.search_trace import SearchTrace
from app.scheduling.engine import run_algorithm
BASE = "2035-07-21T08:00:00Z"
DUE = "2035-07-21T12:00:00Z"

def sample_dataset():
    jobs = [{"id":"J1","name":"Job","product_name":"Part","quantity":1,"priority":"High","release_at":BASE,"due_at":DUE}]
    machines = [{"id":"M1","name":"Cell","machine_type":"CNC","available_from":BASE,"available_until":None,"is_available":True,"setup_time_minutes":0,"processing_capabilities":[]}]
    operations = [{"id":"O1","job_id":"J1","name":"Cut","sequence":1,"eligible_machine_ids":["M1"],"processing_time_minutes":10,"setup_time_minutes":0}]
    return jobs,machines,operations


def test_bayesian_risk_is_normalized_and_evidence_sensitive():
    baseline = infer_risk({})["risk_probability"]
    elevated = infer_risk({"recent_disruption": True})["risk_probability"]
    assert 0 <= baseline <= 1
    assert 0 <= elevated <= 1
    assert elevated > baseline
    assert abs(sum(infer_risk({})["posterior"].values()) - 1) < 1e-9
    assert infer_risk({"recent_disruption": True})["risk_probability"] > baseline
    assert infer_risk({"recent_disruption": False})["risk_probability"] < infer_risk({"recent_disruption": True})["risk_probability"]


def test_bayesian_risk_rejects_unknown_evidence():
    try:
        infer_risk({"unknown": True})
    except ValueError as exc:
        assert "Unknown evidence" in str(exc)
    else:
        raise AssertionError("Unknown evidence must be rejected")


def test_search_trace_captures_actual_parent_edges_and_is_bounded():
    jobs, machines, operations = sample_dataset()
    trace = SearchTrace(max_nodes=100)
    result = run_algorithm("Breadth-First Search", jobs, machines, operations, "job_shop", search_options={"max_expansions": 100, "max_seconds": 1}, trace_collector=trace)
    assert result["search_stats"]["states_generated"] >= 1
    assert trace.nodes[0]["event"] == "root"
    assert any(node["event"] == "generated" and node["action"] for node in trace.nodes)
    assert all(edge["source"] < edge["target"] for edge in trace.edges)
    assert all(node["g"] is not None and node["h"] is not None and node["f"] is not None for node in trace.nodes)
    bounded = SearchTrace(max_nodes=2)
    run_algorithm("Breadth-First Search", jobs, machines, operations, "job_shop", search_options={"max_expansions": 100, "max_seconds": 1}, trace_collector=bounded)
    assert len(bounded.nodes) == 2
    assert bounded.truncated


def test_search_without_trace_is_still_supported():
    jobs, machines, operations = sample_dataset()
    result = run_algorithm("Breadth-First Search", jobs, machines, operations, "job_shop", search_options={"max_expansions": 100, "max_seconds": 1})
    assert result["feasible"]
    assert result["scheduled_operations"]


def test_ai_endpoints_capture_trace_and_disclose_model(client):
    loaded = client.post("/api/v1/sample")
    assert loaded.status_code == 201
    response = client.post("/api/v1/ai-search", json={
        "dataset_source": "current", "scenario": "job_shop", "objective": "makespan",
        "algorithms": ["Breadth-First Search"], "max_expansions": 100,
        "max_seconds": 1, "max_trace_nodes": 12,
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["traces"][0]["nodes"]
    trace_id = payload["traces"][0]["trace_id"]
    fetched = client.get(f"/api/v1/ai-search-traces/{trace_id}")
    assert fetched.status_code == 200
    assert fetched.json()["trace_id"] == trace_id
    risk = client.post("/api/v1/bayesian-risk", json={"evidence":{"maintenance":True}})
    assert risk.status_code == 200
    assert "illustrative" in risk.json()["model"].lower()
    agents = client.post("/api/v1/agents", json={"dataset_source":"current"})
    assert agents.status_code == 200, agents.text
    assert len(agents.json()["agents"]) == 5
    assert agents.json()["schedule_change_performed"] is False
    overview = client.get("/api/v1/ai-center")
    assert overview.status_code == 200 and overview.json()["counts"]["jobs"] > 0
    recommendation = client.post("/api/v1/ai-recommendations", json={"scenario":"job_shop","objective":"makespan","algorithms":["FCFS","A* Search"],"max_expansions":100,"max_seconds":1,"max_trace_nodes":10})
    assert recommendation.status_code == 200, recommendation.text
    assert recommendation.json()["results"]


def test_ai_endpoints_reject_inapplicable_method(client):
    client.post("/api/v1/sample")
    response = client.post("/api/v1/ai-search", json={
        "scenario":"job_shop", "algorithms":["NEH"], "max_expansions":10,
        "max_seconds":1, "max_trace_nodes":10,
    })
    assert response.status_code == 422
