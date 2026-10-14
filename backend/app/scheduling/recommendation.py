from __future__ import annotations
from collections.abc import Sequence

DIRECTION = {"machine_utilization": -1}
LABELS = {
    "makespan": "makespan", "total_tardiness": "total tardiness",
    "maximum_lateness": "maximum lateness", "tardy_jobs": "number of tardy jobs",
    "machine_utilization": "machine utilization", "average_waiting": "average job waiting time",
}


def rank_results(results: list[dict], objective: str, secondary_objectives: Sequence[str] | None = None) -> tuple[str | None, str, list[str]]:
    feasible = [item for item in results if item.get("feasible") and item.get("metrics", {}).get(objective) is not None]
    if not feasible:
        reasons = [item.get("error_message") for item in results if item.get("error_message")]
        detail = reasons[0] if reasons else "The selected algorithms did not produce a feasible schedule. Review operation eligibility, machine availability, release times, and precedence constraints."
        return None, f"No feasible schedule was available for {LABELS.get(objective, objective)}. {detail}", []

    def key(item: dict):
        metrics = item.get("metrics", {})
        return tuple(DIRECTION.get(metric, 1) * (metrics[metric] if metrics.get(metric) is not None else float("inf")) for metric in [objective, *(secondary_objectives or [])]) + (item["algorithm_name"].casefold(),)

    ordered = sorted(feasible, key=key)
    winner = ordered[0]
    metric = winner["metrics"][objective]
    unit = "%" if objective == "machine_utilization" else (" tardy job(s)" if objective == "tardy_jobs" else " min")
    display = f"{metric:g}{unit}" if isinstance(metric, (int, float)) else str(metric)
    reason = f"{winner['algorithm_name']} achieved {display} for {LABELS.get(objective, objective)}—the best value among {len(feasible)} feasible schedule(s) evaluated."
    if len(ordered) > 1 and key(ordered[0])[:-1] == key(ordered[1])[:-1]:
        reason += f" The primary and configured secondary values tied; the documented alphabetical algorithm-name tie-break selected {winner['algorithm_name']}."
    elif secondary_objectives:
        reason += f" Configured tie-break objectives: {', '.join(LABELS.get(x, x) for x in secondary_objectives)}."
    return winner["algorithm_name"], reason, [item["algorithm_name"] for item in ordered]
