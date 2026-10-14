from __future__ import annotations

import pytest

from app.scheduling.engine import _prepare
from app.scheduling.search import _heuristic, _state_key, run_search

BASE = "2035-07-21T08:00:00Z"
DUE = "2035-07-21T12:00:00Z"


def jobs():
    return [
        {"id": "A", "name": "Engine block", "product_name": "Engine block", "component_type": "engine_block", "quantity": 1, "priority": "High", "release_at": BASE, "due_at": DUE},
        {"id": "B", "name": "Brake disc", "product_name": "Brake disc", "component_type": "brake_disc", "quantity": 1, "priority": "Medium", "release_at": BASE, "due_at": DUE},
    ]


def machines():
    return [
        {"id": "M1", "name": "Milling/turning", "machine_type": "CNC", "available_from": BASE, "available_until": None, "is_available": True, "setup_time_minutes": 0, "processing_capabilities": ["cnc_milling", "cnc_turning"]},
        {"id": "M2", "name": "Inspection/drilling", "machine_type": "Cell", "available_from": BASE, "available_until": None, "is_available": True, "setup_time_minutes": 0, "processing_capabilities": ["inspection", "drilling"]},
    ]


def operations():
    return [
        {"id": "A1", "job_id": "A", "name": "Milling", "sequence": 1, "eligible_machine_ids": ["M1"], "required_capability": "cnc_milling", "processing_time_minutes": 15, "setup_time_minutes": 0},
        {"id": "A2", "job_id": "A", "name": "Inspection", "sequence": 2, "eligible_machine_ids": ["M2"], "required_capability": "inspection", "processing_time_minutes": 20, "setup_time_minutes": 0, "predecessor_id": "A1"},
        {"id": "B1", "job_id": "B", "name": "Turning", "sequence": 1, "eligible_machine_ids": ["M1"], "required_capability": "cnc_turning", "processing_time_minutes": 10, "setup_time_minutes": 0},
        {"id": "B2", "job_id": "B", "name": "Drilling", "sequence": 2, "eligible_machine_ids": ["M2"], "required_capability": "drilling", "processing_time_minutes": 12, "setup_time_minutes": 0, "predecessor_id": "B1"},
    ]


def options(**overrides):
    result = {"max_expansions": 1000, "max_seconds": 2.0, "weights": {"makespan": 1, "total_tardiness": 1, "idle_time": 0, "setup_time": 0, "machine_risk": 0}}
    result.update(overrides)
    return result


@pytest.mark.parametrize("algorithm", ["A* Search", "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search"])
def test_every_search_method_returns_a_complete_precedence_and_capacity_valid_job_shop(algorithm):
    result = run_search(algorithm, jobs(), machines(), operations(), "job_shop", search_options=options())
    assert result["feasible"] is True, result["error_message"]
    assert {row["operation_id"] for row in result["scheduled_operations"]} == {"A1", "A2", "B1", "B2"}
    assert result["search_stats"]["states_expanded"] > 0
    assert result["search_stats"]["states_generated"] >= 2
    assert result["computation_time_ms"] >= 0
    by_id = {row["operation_id"]: row for row in result["scheduled_operations"]}
    assert by_id["A2"]["start_minute"] >= by_id["A1"]["end_minute"]
    assert by_id["B2"]["start_minute"] >= by_id["B1"]["end_minute"]
    for machine_id in {row["machine_id"] for row in result["scheduled_operations"]}:
        intervals = sorted((row["start_minute"], row["end_minute"]) for row in result["scheduled_operations"] if row["machine_id"] == machine_id)
        assert all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:]))


@pytest.mark.parametrize("algorithm", ["A* Search", "Uniform Cost Search"])
def test_astar_and_ucs_only_claim_optimality_when_the_bounded_search_proves_the_cost_model(algorithm):
    result = run_search(algorithm, jobs(), machines(), operations(), "job_shop", search_options=options())
    assert result["feasible"] is True
    assert result["search_stats"]["termination_status"] == "optimal"
    assert result["search_stats"]["optimality_proven"] is True
    assert result["search_stats"]["search_cost"] == result["metrics"]["search_cost"]


def test_remaining_work_heuristic_is_a_lower_bound_for_the_complete_fixture_cost():
    job_list = [{**jobs()[0], "due_at": "2035-07-21T08:10:00Z"}]
    machine_list = machines()
    operation_list = [operations()[0], operations()[1]]
    prepared_jobs, prepared_machines, prepared_operations, _, _ = _prepare(job_list, machine_list, operation_list)
    by_job = {"A": prepared_operations}
    h_initial = _heuristic({}, prepared_jobs, prepared_machines, {op["id"]: op for op in prepared_operations}, by_job, options()["weights"])
    result = run_search("A* Search", job_list, machine_list, operation_list, "job_shop", search_options=options())
    assert result["feasible"]
    assert result["metrics"]["total_tardiness"] == 25
    assert h_initial <= result["metrics"]["search_cost"] + 1e-8


def test_search_canonical_state_hash_is_assignment_order_independent():
    left = {"A1": {"machine_id": "M1", "start_minute": 0, "end_minute": 15}, "B1": {"machine_id": "M2", "start_minute": 0, "end_minute": 10}}
    right = {"B1": left["B1"], "A1": left["A1"]}
    changed = {**right, "A1": {"machine_id": "M1", "start_minute": 1, "end_minute": 16}}
    assert _state_key(left) == _state_key(right)
    assert _state_key(right) != _state_key(changed)


def test_expansion_limit_without_a_goal_returns_no_partial_schedule():
    result = run_search("A* Search", jobs(), machines(), operations(), "job_shop", search_options=options(max_expansions=1))
    assert result["feasible"] is False
    assert result["scheduled_operations"] == []
    assert result["search_stats"]["states_expanded"] == 1
    assert result["search_stats"]["termination_status"] == "limit_without_solution"
    assert result["search_stats"]["optimality_proven"] is False
    assert "No partial schedule was returned" in result["error_message"]


def test_wall_clock_limit_without_a_goal_returns_no_partial_schedule():
    result = run_search("A* Search", jobs(), machines(), operations(), "job_shop", search_options=options(max_seconds=1e-9))
    assert result["feasible"] is False
    assert result["scheduled_operations"] == []
    assert result["search_stats"]["states_expanded"] == 0
    assert result["search_stats"]["termination_status"] == "limit_without_solution"
    assert result["search_stats"]["optimality_proven"] is False
    assert "No partial schedule was returned" in result["error_message"]


def test_search_respects_maintenance_and_rejects_missing_required_capability():
    calendar = [{**machines()[0], "maintenance_schedule": [{"starts_at": "2035-07-21T08:00:00Z", "ends_at": "2035-07-21T08:20:00Z", "reason": "service"}]}]
    result = run_search("A* Search", [jobs()[0]], calendar, [operations()[0]], "job_shop", search_options=options())
    assert result["feasible"]
    assert result["scheduled_operations"][0]["start_minute"] >= 20

    incapable = [{**machines()[0], "processing_capabilities": ["cnc_turning"]}]
    invalid = run_search("A* Search", [jobs()[0]], incapable, [operations()[0]], "job_shop", search_options=options())
    assert invalid["feasible"] is False
    assert invalid["scheduled_operations"] == []
    assert "compatible eligible machine" in invalid["error_message"]
