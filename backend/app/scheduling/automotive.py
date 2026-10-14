from __future__ import annotations

AUTOMOTIVE_WORKFLOWS = {
    "engine_block": {
        "label": "Engine block",
        "steps": [
            {"sequence": 1, "name": "Milling", "required_capability": "cnc_milling", "suggested_minutes": 40},
            {"sequence": 2, "name": "Drilling", "required_capability": "drilling", "suggested_minutes": 28},
            {"sequence": 3, "name": "Inspection", "required_capability": "inspection", "suggested_minutes": 15},
        ],
    },
    "crankshaft": {
        "label": "Crankshaft",
        "steps": [
            {"sequence": 1, "name": "Turning", "required_capability": "cnc_turning", "suggested_minutes": 35},
            {"sequence": 2, "name": "Grinding", "required_capability": "grinding", "suggested_minutes": 26},
            {"sequence": 3, "name": "Inspection", "required_capability": "inspection", "suggested_minutes": 12},
        ],
    },
    "brake_disc": {
        "label": "Brake disc",
        "steps": [
            {"sequence": 1, "name": "Turning", "required_capability": "cnc_turning", "suggested_minutes": 24},
            {"sequence": 2, "name": "Drilling", "required_capability": "drilling", "suggested_minutes": 18},
            {"sequence": 3, "name": "Inspection", "required_capability": "inspection", "suggested_minutes": 10},
        ],
    },
}


def workflow_payload() -> dict:
    return {
        "is_simulated_learning_example": True,
        "notice": "Editable educational templates only; not certified automotive process plans or real-company specifications.",
        "workflows": AUTOMOTIVE_WORKFLOWS,
    }
