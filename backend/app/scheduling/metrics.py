from __future__ import annotations


def calculate_metrics(jobs: list[dict], machines: list[dict], scheduled: list[dict], horizon_start: float, machine_blackouts: dict[str, list[tuple[float, float]]] | None = None) -> dict:
    machine_blackouts = machine_blackouts or {}
    if not scheduled:
        return {"makespan": None, "total_completion_time": None, "total_tardiness": None, "maximum_lateness": None, "tardy_jobs": None, "average_waiting": None, "machine_utilization": None, "idle_time_minutes": None, "setup_time_minutes": None}
    completion: dict[str, float] = {}
    for item in scheduled:
        completion[item["job_id"]] = max(completion.get(item["job_id"], float("-inf")), item["end_minute"])
    due_by_job = {j["id"]: j["due_minute"] for j in jobs}
    lateness = {jid: end - due_by_job[jid] for jid, end in completion.items()}
    tardiness = {jid: max(0.0, value) for jid, value in lateness.items()}
    horizon_end = max(item["end_minute"] for item in scheduled)
    productive_processing = sum(item["processing_time_minutes"] for item in scheduled)
    available = 0.0
    for machine in machines:
        if not machine["is_available"]:
            continue
        start = max(horizon_start, machine["available_from_minute"])
        window_end = machine.get("available_until_minute")
        end = min(horizon_end, window_end if window_end is not None else horizon_end)
        machine_available = max(0.0, end - start)
        merged: list[list[float]] = []
        for blackout_start, blackout_end in sorted(machine_blackouts.get(machine["id"], [])):
            clipped_start, clipped_end = max(start, blackout_start), min(end, blackout_end)
            if clipped_end <= clipped_start:
                continue
            if merged and clipped_start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], clipped_end)
            else:
                merged.append([clipped_start, clipped_end])
        blocked = sum(blackout_end - blackout_start for blackout_start, blackout_end in merged)
        available += max(0.0, machine_available - blocked)
    waiting = [item["waiting_time_minutes"] for item in scheduled]
    total_setup = sum(item.get("setup_time_minutes", 0.0) for item in scheduled)
    idle = max(0.0, available - productive_processing - total_setup)
    return {
        "makespan": round(horizon_end - horizon_start, 4),
        "total_completion_time": round(sum(end - horizon_start for end in completion.values()), 4),
        "total_tardiness": round(sum(tardiness.values()), 4),
        "maximum_lateness": round(max(lateness.values(), default=0.0), 4),
        "tardy_jobs": sum(1 for value in lateness.values() if value > 0),
        "average_waiting": round(sum(waiting) / len(waiting), 4) if waiting else None,
        "machine_utilization": round(100 * productive_processing / available, 4) if available > 0 else None,
        "job_completion_minutes": {jid: round(end, 4) for jid, end in completion.items()},
        "job_lateness_minutes": {jid: round(value, 4) for jid, value in lateness.items()},
        "horizon_start_minute": round(horizon_start, 4),
        "horizon_end_minute": round(horizon_end, 4),
        "productive_time_minutes": round(productive_processing, 4),
        "available_machine_time_minutes": round(available, 4),
        "idle_time_minutes": round(idle, 4),
        "setup_time_minutes": round(total_setup, 4),
    }
