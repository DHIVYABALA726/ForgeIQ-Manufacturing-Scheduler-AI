from __future__ import annotations
import pytest
from app.scheduling.engine import run_algorithm
from app.scheduling.metrics import calculate_metrics
from app.scheduling.recommendation import rank_results
from app.scheduling.validation import validate_dataset, DatasetError

BASE = "2031-03-04T08:00:00Z"

def jobs_two():
    return [
        {"id": "A", "name": "Long", "product_name": "P-A", "quantity": 1, "priority": "Medium", "release_at": BASE, "due_at": "2031-03-04T10:00:00Z"},
        {"id": "B", "name": "Short", "product_name": "P-B", "quantity": 1, "priority": "Medium", "release_at": BASE, "due_at": "2031-03-04T10:00:00Z"},
    ]

def machine(mid="M1", available=True, start=BASE, until=None):
    return {"id": mid, "name": mid, "machine_type": "CNC", "available_from": start, "available_until": until, "is_available": available, "setup_time_minutes": 0}

def two_ops():
    return [
        {"id": "O-A", "job_id": "A", "name": "Long cut", "sequence": 1, "eligible_machine_ids": ["M1"], "processing_time_minutes": 60, "setup_time_minutes": 0, "predecessor_id": None},
        {"id": "O-B", "job_id": "B", "name": "Short cut", "sequence": 1, "eligible_machine_ids": ["M1"], "processing_time_minutes": 10, "setup_time_minutes": 0, "predecessor_id": None},
    ]

def test_dispatch_rules_are_real_and_deterministic():
    inputs = jobs_two(), [machine()], two_ops()
    results = {name: run_algorithm(name, *inputs, "parallel_machine") for name in ["FCFS", "SPT", "EDD", "Priority-Based", "LPT"]}
    assert all(item["feasible"] for item in results.values())
    assert [x["operation_id"] for x in results["FCFS"]["scheduled_operations"]][0] == "O-A"
    assert [x["operation_id"] for x in results["SPT"]["scheduled_operations"]][0] == "O-B"
    assert [x["operation_id"] for x in results["LPT"]["scheduled_operations"]][0] == "O-A"
    assert results["SPT"]["computation_time_ms"] >= 0
    assert results["SPT"]["metrics"]["makespan"] == 70
    altered = jobs_two(); altered[1]["due_at"] = "2031-03-04T09:00:00Z"; altered[1]["priority"] = "Critical"
    assert run_algorithm("EDD", altered, [machine()], two_ops(), "parallel_machine")["scheduled_operations"][0]["job_id"] == "B"
    assert run_algorithm("Priority-Based", altered, [machine()], two_ops(), "parallel_machine")["scheduled_operations"][0]["job_id"] == "B"

def test_release_times_and_machine_availability_are_respected():
    j = jobs_two(); j[1]["release_at"] = "2031-03-04T09:00:00Z"
    m = machine(start="2031-03-04T08:30:00Z")
    result = run_algorithm("SPT", j, [m], two_ops(), "parallel_machine")
    assert result["feasible"]
    assert all(item["start_minute"] >= 30 for item in result["scheduled_operations"])
    assert next(x for x in result["scheduled_operations"] if x["job_id"] == "B")["start_minute"] >= 60

def test_operation_uses_the_earliest_genuinely_eligible_machine():
    op = [{"id":"O-A","job_id":"A","name":"Cut","sequence":1,"eligible_machine_ids":["M1","M2"],"processing_time_minutes":20,"setup_time_minutes":0}]
    result = run_algorithm("FCFS", [jobs_two()[0]], [machine("M1", start="2031-03-04T08:30:00Z"), machine("M2")], op, "parallel_machine")
    assert result["feasible"]
    assert result["scheduled_operations"][0]["machine_id"] == "M2"
    assert result["scheduled_operations"][0]["start_minute"] == 0

def test_no_two_operations_overlap_on_one_machine():
    result = run_algorithm("FCFS", jobs_two(), [machine()], two_ops(), "parallel_machine")
    intervals = sorted((x["start_minute"], x["end_minute"]) for x in result["scheduled_operations"])
    assert all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:]))

def test_precedence_is_enforced_for_job_shop_operations():
    ops = [
        {"id": "O1", "job_id": "A", "name": "Cut", "sequence": 1, "eligible_machine_ids": ["M1"], "processing_time_minutes": 30, "setup_time_minutes": 0},
        {"id": "O2", "job_id": "A", "name": "Drill", "sequence": 2, "eligible_machine_ids": ["M2"], "processing_time_minutes": 20, "setup_time_minutes": 0, "predecessor_id": "O1"},
        {"id": "O3", "job_id": "B", "name": "Inspect", "sequence": 1, "eligible_machine_ids": ["M2"], "processing_time_minutes": 45, "setup_time_minutes": 0},
    ]
    result = run_algorithm("FCFS", jobs_two(), [machine("M1"), machine("M2")], ops, "job_shop")
    assert result["feasible"]
    lookup = {x["operation_id"]: x for x in result["scheduled_operations"]}
    assert lookup["O2"]["start_minute"] >= lookup["O1"]["end_minute"]
    assert lookup["O2"]["start_minute"] >= lookup["O3"]["end_minute"] or lookup["O2"]["machine_id"] != lookup["O3"]["machine_id"]

def test_unavailable_machine_produces_infeasible_result():
    result = run_algorithm("FCFS", jobs_two(), [machine(available=False)], two_ops(), "parallel_machine")
    assert not result["feasible"]
    assert "eligible machine" in result["error_message"]
    assert result["scheduled_operations"] == []

def test_machine_window_that_cannot_fit_operation_is_infeasible():
    result = run_algorithm("FCFS", jobs_two(), [machine(until="2031-03-04T08:30:00Z")], two_ops(), "parallel_machine")
    assert not result["feasible"]
    assert "availability window" in result["error_message"]

def test_metrics_match_documented_definitions():
    jobs = [{"id": "A", "due_minute": 30}, {"id": "B", "due_minute": 120}]
    machines = [{"id": "M1", "is_available": True, "available_from_minute": 0, "available_until_minute": None}, {"id": "M2", "is_available": False, "available_from_minute": 0, "available_until_minute": None}]
    ops = [
        {"job_id": "A", "end_minute": 40, "start_minute": 0, "duration_minutes": 40, "processing_time_minutes": 35, "waiting_time_minutes": 2},
        {"job_id": "B", "end_minute": 70, "start_minute": 40, "duration_minutes": 30, "processing_time_minutes": 25, "waiting_time_minutes": 10},
    ]
    value = calculate_metrics(jobs, machines, ops, 0)
    assert value["makespan"] == 70
    assert value["total_completion_time"] == 110
    assert value["total_tardiness"] == 10
    assert value["maximum_lateness"] == 10
    assert value["tardy_jobs"] == 1
    assert value["average_waiting"] == 6
    assert value["productive_time_minutes"] == 60
    assert value["machine_utilization"] == pytest.approx(60 / 70 * 100, abs=0.0001)

def test_neh_only_supports_same_permutation_flowshop_route():
    jobs = jobs_two(); machines = [machine("M1"), machine("M2")]; ops = []
    for job_id, first, second in [("A", 30, 15), ("B", 20, 25)]:
        ops.extend([
            {"id": f"{job_id}-1", "job_id": job_id, "name": "Stage 1", "sequence": 1, "eligible_machine_ids": ["M1"], "processing_time_minutes": first, "setup_time_minutes": 0},
            {"id": f"{job_id}-2", "job_id": job_id, "name": "Stage 2", "sequence": 2, "eligible_machine_ids": ["M2"], "processing_time_minutes": second, "setup_time_minutes": 0, "predecessor_id": f"{job_id}-1"},
        ])
    result = run_algorithm("NEH", jobs, machines, ops, "permutation_flow_shop")
    assert result["feasible"] and len(result["scheduled_operations"]) == 4
    assert not run_algorithm("NEH", jobs, machines, ops, "job_shop")["feasible"]

def test_recommendation_filters_infeasible_and_breaks_ties_deterministically():
    results = [
        {"algorithm_name": "SPT", "feasible": True, "metrics": {"makespan": 10, "machine_utilization": 85}},
        {"algorithm_name": "FCFS", "feasible": False, "metrics": {"makespan": 1, "machine_utilization": 100}},
        {"algorithm_name": "EDD", "feasible": True, "metrics": {"makespan": 10, "machine_utilization": 90}},
    ]
    winner, reason, ranking = rank_results(results, "makespan")
    assert winner == "EDD" and ranking == ["EDD", "SPT"]
    assert "best value" in reason
    assert rank_results(results, "machine_utilization")[0] == "EDD"

def test_dataset_rejects_invalid_parallel_multi_operation_job_and_skipped_predecessor():
    ops = [*two_ops(), {"id":"O-A2","job_id":"A","name":"Second","sequence":2,"eligible_machine_ids":["M1"],"processing_time_minutes":10,"setup_time_minutes":0}]
    with pytest.raises(DatasetError, match="exactly one operation"):
        validate_dataset(jobs_two(), [machine()], ops, "parallel_machine")
    chain = [
        {"id":"A1","job_id":"A","name":"1","sequence":1,"eligible_machine_ids":["M1"],"processing_time_minutes":5,"setup_time_minutes":0},
        {"id":"A2","job_id":"A","name":"2","sequence":2,"eligible_machine_ids":["M1"],"processing_time_minutes":5,"setup_time_minutes":0},
        {"id":"A3","job_id":"A","name":"3","sequence":3,"eligible_machine_ids":["M1"],"processing_time_minutes":5,"setup_time_minutes":0,"predecessor_id":"A1"},
    ]
    with pytest.raises(DatasetError, match="immediately previous"):
        validate_dataset([jobs_two()[0]], [machine()], chain, "job_shop")
