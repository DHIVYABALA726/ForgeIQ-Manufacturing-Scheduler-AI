export type Priority = 'Critical' | 'High' | 'Medium' | 'Low';
export type ComponentType = 'engine_block' | 'crankshaft' | 'brake_disc' | 'other';
export type JobStatus = 'queued' | 'in_progress' | 'completed' | 'on_hold';
export type Scenario = 'parallel_machine' | 'job_shop' | 'permutation_flow_shop';
export type Objective = 'makespan' | 'total_tardiness' | 'maximum_lateness' | 'tardy_jobs' | 'machine_utilization' | 'average_waiting';
export type AlgorithmName = 'FCFS' | 'SPT' | 'EDD' | 'Priority-Based' | 'LPT' | 'NEH' | 'A* Search' | 'Uniform Cost Search' | 'Greedy Best-First' | 'Breadth-First Search' | 'Depth-First Search';

export interface SearchWeights { makespan: number; total_tardiness: number; idle_time: number; setup_time: number; machine_risk: number; }
export interface SearchOptions { max_expansions: number; max_seconds: number; weights: SearchWeights; }
export interface SearchStats {
  states_expanded: number; states_generated: number; duplicate_states: number;
  termination_status: string; optimality_proven: boolean; max_expansions: number;
  max_seconds: number; search_cost?: number | null; weights?: SearchWeights;
}

export interface Job {
  id: string; name: string; product_name: string; quantity: number; priority: Priority;
  release_at: string; due_at: string; component_type?: ComponentType; status?: JobStatus;
  notes?: string | null; is_sample: boolean;
}
export interface MaintenanceWindow { starts_at: string; ends_at: string; reason?: string | null; }
export interface Machine {
  id: string; name: string; machine_type: string; available_from: string; available_until?: string | null;
  is_available: boolean; setup_time_minutes: number; processing_capabilities?: string[];
  maintenance_schedule?: MaintenanceWindow[]; is_sample: boolean;
}
export interface Operation {
  id: string; job_id: string; name: string; sequence: number; eligible_machine_ids: string[];
  processing_time_minutes: number; setup_time_minutes: number; predecessor_id?: string | null;
  required_capability?: string | null; is_sample: boolean;
}
export interface ScheduledOperation {
  operation_id: string; job_id: string; machine_id: string; operation_name: string; sequence: number;
  start_minute: number; end_minute: number; processing_time_minutes: number; setup_time_minutes: number;
  duration_minutes: number; waiting_time_minutes: number; due_minute: number; due_at: string; start_at: string; end_at: string;
}
export interface Metrics {
  makespan?: number | null; total_completion_time?: number | null; total_tardiness?: number | null;
  maximum_lateness?: number | null; tardy_jobs?: number | null; average_waiting?: number | null;
  machine_utilization?: number | null; job_completion_minutes?: Record<string, number>;
  job_lateness_minutes?: Record<string, number>; horizon_start_minute?: number;
  horizon_end_minute?: number; productive_time_minutes?: number; available_machine_time_minutes?: number;
  idle_time_minutes?: number | null; setup_time_minutes?: number | null; search_cost?: number | null;
}
export interface AlgorithmResult {
  algorithm_name: AlgorithmName; scenario: Scenario; feasible: boolean; scheduled_operations: ScheduledOperation[];
  metrics: Metrics; objective_value?: number | null; constraint_violations?: string[];
  risk_fallback_operation_ids?: string[]; search_stats?: SearchStats | null;
  computation_time_ms: number; error_message?: string | null;
}
export type DisruptionType = 'machine_breakdown' | 'urgent_order' | 'processing_delay' | 'maintenance' | 'machine_risk';
export interface MovedOperation {
  operation_id: string; job_id: string; operation_name: string;
  machine_before: string; machine_after: string; start_before: string; start_after: string; end_before: string; end_after: string;
}
export interface DisruptionImpact {
  affected_job_ids: string[]; affected_operation_ids: string[]; moved_operation_ids: string[];
  moved_operations: MovedOperation[]; added_operation_ids: string[]; completed_operation_ids: string[];
  locked_operation_ids: string[]; restarted_operation_ids: string[]; risk_fallback_operation_ids: string[];
  stability_percent: number; stability_definition: string; shared_operation_count: number; unchanged_operation_count: number;
  metrics_before: Metrics; metrics_after: Metrics; algorithm_name: AlgorithmName; scenario: Scenario;
}
export interface DisruptionEvent {
  id: string; parent_schedule_id: string; revised_schedule_id: string; event_type: DisruptionType;
  effective_at: string; event_payload: Record<string, unknown>; impact: DisruptionImpact; explanation: string; created_at: string;
}
export interface DynamicRescheduleInput {
  event_type: DisruptionType; effective_at: string; algorithm_name: AlgorithmName;
  search_options?: SearchOptions;
  machine_id?: string; repair_until?: string; operation_id?: string; delay_minutes?: number; risk_note?: string;
  urgent_job?: Omit<Job, 'is_sample'>;
  urgent_operations?: Omit<Operation, 'is_sample'>[];
  completed_operation_ids?: string[];
}
export interface DynamicRescheduleResponse { event: DisruptionEvent; run: ScheduleRun; }
export interface DynamicRescheduleDetails extends Partial<DisruptionImpact> {
  event_id: string; parent_schedule_id: string; event_type: DisruptionType; effective_at: string; explanation: string;
}
export interface ScheduleRun {
  id: string; scenario: Scenario; objective: Objective; secondary_objectives: Objective[]; hard_due_dates: boolean;
  dataset_version: number; current_dataset_version: number; is_stale: boolean; created_at: string;
  selected_algorithm_name?: AlgorithmName | null; recommended_algorithm_name?: AlgorithmName | null;
  recommendation_reason?: string | null; recommendation_details?: { scope?: string; ranking?: string[] };
  results: AlgorithmResult[]; dynamic_reschedule?: DynamicRescheduleDetails | null;
  input_snapshot?: { jobs: Job[]; machines: Machine[]; operations: Operation[]; scenario?: Scenario; hard_due_dates?: boolean; search_options?: SearchOptions; dynamic_event_history?: Record<string, unknown>[]; dynamic_reschedule?: DynamicRescheduleDetails };
}
export type Section = 'workspace' | 'data' | 'scheduling' | 'rescheduling' | 'knowledge' | 'gantt' | 'comparison' | 'report' | 'ai-center' | 'ai-search' | 'ai-tree' | 'intelligence' | 'agents' | 'risk';
export interface ApiCollections { jobs: Job[]; machines: Machine[]; operations: Operation[]; schedules: ScheduleRun[]; }
