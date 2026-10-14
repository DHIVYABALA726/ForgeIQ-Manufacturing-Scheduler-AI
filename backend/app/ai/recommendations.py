from __future__ import annotations

from ..scheduling.recommendation import rank_results

SUPPORTED = {
    "parallel_machine": ["FCFS", "SPT", "EDD", "Priority-Based", "LPT", "A* Search", "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search"],
    "job_shop": ["FCFS", "SPT", "EDD", "Priority-Based", "LPT", "A* Search", "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search"],
    "permutation_flow_shop": ["NEH", "A* Search", "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search"],
}

def compare(results: list[dict], objective: str, scenario: str) -> dict:
    applicable = [r for r in results if r.get("algorithm_name") in SUPPORTED.get(scenario, [])]
    feasible = [r for r in applicable if r.get("feasible")]
    winner, reason, ranking = rank_results(feasible, objective, []) if feasible else (None, "No complete feasible schedule was produced.", [])
    return {"scenario": scenario, "objective": objective, "applicable_methods": SUPPORTED.get(scenario, []),
            "results": applicable, "recommended_algorithm_name": winner,
            "reason": reason, "ranking": ranking,
            "limitations": "Only feasible complete schedules are ranked. Search g/h/f values are not compared across methods; interrupted searches are not proof of optimality."}
