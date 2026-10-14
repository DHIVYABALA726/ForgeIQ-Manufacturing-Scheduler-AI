from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

Priority = Literal["Critical", "High", "Medium", "Low"]
Scenario = Literal["parallel_machine", "job_shop", "permutation_flow_shop"]
Objective = Literal["makespan", "total_tardiness", "maximum_lateness", "tardy_jobs", "machine_utilization", "average_waiting"]
Algorithm = Literal["FCFS", "SPT", "EDD", "Priority-Based", "LPT", "NEH", "A* Search", "Uniform Cost Search", "Greedy Best-First", "Breadth-First Search", "Depth-First Search"]
ComponentType = Literal["engine_block", "crankshaft", "brake_disc", "other"]
JobStatus = Literal["queued", "in_progress", "completed", "on_hold"]


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SearchWeights(BaseModel):
    makespan: float = Field(default=1.0, ge=0, le=1000)
    total_tardiness: float = Field(default=1.0, ge=0, le=1000)
    idle_time: float = Field(default=0.0, ge=0, le=1000)
    setup_time: float = Field(default=0.0, ge=0, le=1000)
    machine_risk: float = Field(default=0.0, ge=0, le=1000)

    @model_validator(mode="after")
    def at_least_one_weight(self):
        if not any(value > 0 for value in self.model_dump().values()):
            raise ValueError("At least one search cost weight must be greater than zero.")
        return self


class SearchOptions(BaseModel):
    max_expansions: int = Field(default=2500, ge=1, le=100000)
    max_seconds: float = Field(default=2.0, gt=0, le=30)
    weights: SearchWeights = Field(default_factory=SearchWeights)


class JobInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    product_name: str = Field(min_length=1, max_length=160)
    quantity: int = Field(gt=0)
    priority: Priority
    release_at: datetime
    due_at: datetime
    component_type: ComponentType = "other"
    status: JobStatus = "queued"
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("release_at", "due_at")
    @classmethod
    def normalize_dates(cls, value: datetime) -> datetime:
        return normalize_datetime(value)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.due_at < self.release_at:
            raise ValueError("Due date must not precede the release date.")
        return self


class MaintenanceWindow(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=240)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_dates(cls, value: datetime) -> datetime:
        return normalize_datetime(value)

    @model_validator(mode="after")
    def valid_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Maintenance end must be later than its start.")
        return self


class MachineInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    machine_type: str = Field(min_length=1, max_length=120)
    available_from: datetime
    available_until: datetime | None = None
    is_available: bool = True
    setup_time_minutes: int = Field(default=0, ge=0)
    processing_capabilities: list[str] = Field(default_factory=list, max_length=50)
    maintenance_schedule: list[MaintenanceWindow] = Field(default_factory=list, max_length=200)

    @field_validator("available_from", "available_until")
    @classmethod
    def normalize_dates(cls, value: datetime | None):
        return normalize_datetime(value) if value else None

    @field_validator("processing_capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str]):
        normalized = [item.strip().casefold() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Processing capabilities must be unique.")
        return normalized

    @model_validator(mode="after")
    def valid_window(self):
        if self.available_until and self.available_until <= self.available_from:
            raise ValueError("Available Until must be later than Available From.")
        return self


class OperationInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    job_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    sequence: int = Field(gt=0)
    eligible_machine_ids: list[str] = Field(min_length=1)
    processing_time_minutes: int = Field(gt=0)
    setup_time_minutes: int = Field(default=0, ge=0)
    predecessor_id: str | None = None
    required_capability: str | None = Field(default=None, min_length=1, max_length=80)


class ScheduleRequest(BaseModel):
    scenario: Scenario
    algorithms: list[Algorithm] = Field(min_length=1)
    objective: Objective
    secondary_objectives: list[Objective] = Field(default_factory=list)
    hard_due_dates: bool = False
    search_options: SearchOptions = Field(default_factory=SearchOptions)

    @field_validator("algorithms")
    @classmethod
    def unique_algorithms(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Select each scheduling algorithm only once.")
        return value

    @field_validator("secondary_objectives")
    @classmethod
    def distinct_secondary(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Select each secondary objective only once.")
        return value


class SelectScheduleInput(BaseModel):
    algorithm_name: Algorithm


DisruptionType = Literal["machine_breakdown", "urgent_order", "processing_delay", "maintenance", "machine_risk"]


class DynamicRescheduleInput(BaseModel):
    event_type: DisruptionType
    effective_at: datetime
    algorithm_name: Algorithm
    search_options: SearchOptions = Field(default_factory=SearchOptions)
    machine_id: str | None = Field(default=None, min_length=1, max_length=80)
    repair_until: datetime | None = None
    operation_id: str | None = Field(default=None, min_length=1, max_length=80)
    delay_minutes: int | None = Field(default=None, ge=1, le=1_000_000)
    risk_note: str | None = Field(default=None, max_length=1000)
    urgent_job: JobInput | None = None
    urgent_operations: list[OperationInput] | None = Field(default=None, min_length=1, max_length=100)
    completed_operation_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("effective_at", "repair_until")
    @classmethod
    def normalize_event_dates(cls, value: datetime | None) -> datetime | None:
        return normalize_datetime(value) if value else None

    @field_validator("completed_operation_ids")
    @classmethod
    def unique_completed_operations(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Completed operation IDs must be unique.")
        return value

    @model_validator(mode="after")
    def event_fields_match_type(self):
        outage = self.event_type in {"machine_breakdown", "maintenance"}
        if outage and (not self.machine_id or not self.repair_until):
            raise ValueError("Machine breakdown and maintenance require a machine and a repair/maintenance end time.")
        if outage and self.repair_until and self.repair_until <= self.effective_at:
            raise ValueError("Repair / maintenance end must be later than the event time.")
        if self.event_type == "machine_risk" and not self.machine_id:
            raise ValueError("An operator-reported high-risk event requires a machine ID.")
        if self.event_type == "processing_delay" and (not self.operation_id or not self.delay_minutes):
            raise ValueError("A processing delay requires an active operation and a positive delay in minutes.")
        if self.event_type == "urgent_order":
            if not self.urgent_job or not self.urgent_operations:
                raise ValueError("An urgent order requires a new job and at least one ordered operation.")
            if self.urgent_job.due_at <= self.effective_at:
                raise ValueError("The urgent job due time must be later than its event/release time.")
            if any(item.job_id != self.urgent_job.id for item in self.urgent_operations):
                raise ValueError("Every urgent operation must refer to the new urgent Job ID.")
            sequences = [item.sequence for item in self.urgent_operations]
            if sequences != list(range(1, len(sequences) + 1)):
                raise ValueError("Urgent-order operations must use consecutive sequence numbers starting at 1.")
            for index, item in enumerate(self.urgent_operations):
                predecessor = self.urgent_operations[index - 1].id if index else None
                if item.predecessor_id != predecessor:
                    raise ValueError("Urgent operations must link to the immediately preceding operation.")
            ids = [item.id for item in self.urgent_operations]
            if len(ids) != len(set(ids)):
                raise ValueError("Urgent-operation IDs must be unique.")
        elif self.urgent_job or self.urgent_operations:
            raise ValueError("Urgent job and operations fields are only valid for an urgent-order event.")
        return self
