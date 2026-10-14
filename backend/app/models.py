from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetState(Base):
    __tablename__ = "dataset_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    component_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    operations: Mapped[list["Operation"]] = relationship(back_populates="job", cascade="all, delete-orphan", order_by="Operation.sequence")


class Machine(Base):
    __tablename__ = "machines"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    machine_type: Mapped[str] = mapped_column(String(120), nullable=False)
    available_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    setup_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    maintenance_schedule: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_machine_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    processing_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    predecessor_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    required_capability: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    job: Mapped[Job] = relationship(back_populates="operations")


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario: Mapped[str] = mapped_column(String(40), nullable=False)
    objective: Mapped[str] = mapped_column(String(40), nullable=False)
    secondary_objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    selected_algorithm_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    results: Mapped[list["AlgorithmResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    recommendation: Mapped["Recommendation | None"] = relationship(back_populates="run", cascade="all, delete-orphan", uselist=False)


class AlgorithmResult(Base):
    __tablename__ = "algorithm_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    algorithm_name: Mapped[str] = mapped_column(String(60), nullable=False)
    feasible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    computation_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run: Mapped[ScheduleRun] = relationship(back_populates="results")
    operations: Mapped[list["ScheduledOperation"]] = relationship(back_populates="result", cascade="all, delete-orphan")


class ScheduledOperation(Base):
    __tablename__ = "scheduled_operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("algorithm_results.id", ondelete="CASCADE"), index=True, nullable=False)
    operation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    job_id: Mapped[str] = mapped_column(String(80), nullable=False)
    machine_id: Mapped[str] = mapped_column(String(80), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_minute: Mapped[float] = mapped_column(Float, nullable=False)
    end_minute: Mapped[float] = mapped_column(Float, nullable=False)
    processing_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    waiting_time_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    due_at: Mapped[str] = mapped_column(String(48), nullable=False)
    start_at: Mapped[str] = mapped_column(String(48), nullable=False)
    end_at: Mapped[str] = mapped_column(String(48), nullable=False)
    result: Mapped[AlgorithmResult] = relationship(back_populates="operations")


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"), unique=True, nullable=False)
    recommended_algorithm_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    run: Mapped[ScheduleRun] = relationship(back_populates="recommendation")


class DisruptionEvent(Base):
    __tablename__ = "disruption_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_schedule_id: Mapped[str] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    revised_schedule_id: Mapped[str] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    impact: Mapped[dict] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
