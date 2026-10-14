from __future__ import annotations

from itertools import product

# Illustrative P(cause | observed condition) values; not learned or validated.
BINARY_CPTS = {
    "maintenance": {False: 0.025, True: 0.11},
    "high_workload": {False: 0.035, True: 0.13},
    "recent_disruption": {False: 0.03, True: 0.16},
}


def validate_cpts() -> bool:
    for name, table in BINARY_CPTS.items():
        for observed, probability in table.items():
            if not 0.0 <= probability <= 1.0 or abs(probability + (1.0 - probability) - 1.0) > 1e-12:
                raise ValueError(f"Invalid binary CPT for {name} given evidence={observed}.")
    return True


def infer_risk(evidence: dict[str, bool] | None = None) -> dict:
    evidence = evidence or {}
    unknown = set(evidence) - set(BINARY_CPTS)
    if unknown:
        raise ValueError(f"Unknown evidence key(s): {', '.join(sorted(unknown))}.")
    if any(not isinstance(v, bool) for v in evidence.values()):
        raise ValueError("Evidence values must be boolean.")
    validate_cpts()
    variables = list(BINARY_CPTS)
    cause_probabilities = {name: BINARY_CPTS[name][bool(evidence.get(name, False))] for name in variables}
    total = risky = 0.0
    # Exact enumeration over three conditionally independent latent risk causes.
    for values in product((False, True), repeat=len(variables)):
        probability = 1.0
        for name, is_cause in zip(variables, values):
            p = cause_probabilities[name]
            probability *= p if is_cause else 1.0 - p
        total += probability
        if any(values):
            risky += probability
    posterior = risky / total if total else 0.0
    return {
        "evidence": evidence,
        "posterior": {"low": max(0.0, 1.0 - posterior), "elevated": posterior},
        "risk_probability": posterior,
        "model": "Illustrative factorized binary Bayesian model; exact enumeration, not trained or validated.",
        "cpt": {name: {"cause_probability_given_evidence_false": values[False], "no_cause_probability_given_evidence_false": 1.0 - values[False], "cause_probability_given_evidence_true": values[True], "no_cause_probability_given_evidence_true": 1.0 - values[True]} for name, values in BINARY_CPTS.items()},
        "assumptions": [
            "Maintenance, workload and recent-disruption evidence condition independent latent risk causes.",
            "Elevated risk is the event that at least one latent cause is active.",
            "Each cause probability is an illustrative assumption, not an empirical estimate.",
            "Risk is advisory and cannot change machine availability or schedules.",
        ],
    }
