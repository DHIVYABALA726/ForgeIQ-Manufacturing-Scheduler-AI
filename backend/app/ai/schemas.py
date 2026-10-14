from typing import Literal
from pydantic import BaseModel, Field

class SearchExperiment(BaseModel):
    dataset_source: str = "current"
    schedule_id: str | None = None
    scenario: Literal["parallel_machine", "job_shop", "permutation_flow_shop"] = "job_shop"
    objective: str = "makespan"
    algorithms: list[str] = Field(min_length=1, max_length=5)
    max_expansions: int = Field(default=1000, ge=1, le=10000)
    max_seconds: float = Field(default=1.0, gt=0, le=10)
    max_trace_nodes: int = Field(default=300, ge=1, le=1000)
    hard_due_dates: bool = False

class AgentAnalysis(BaseModel):
    dataset_source: str = "current"
    schedule_id: str | None = None
    scenario: Literal["parallel_machine", "job_shop", "permutation_flow_shop"] = "job_shop"
    objective: str = "makespan"
    machine_id: str | None = None
    maintenance: bool = False
    high_workload: bool = False
    recent_disruption: bool = False

class RiskRequest(BaseModel):
    evidence: dict[str, bool] = Field(default_factory=dict)
