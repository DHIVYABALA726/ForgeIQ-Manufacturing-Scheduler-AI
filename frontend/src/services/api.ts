import type { AlgorithmName, AlgorithmResult, ApiCollections, DisruptionEvent, DynamicRescheduleInput, DynamicRescheduleResponse, Job, Machine, Objective, Operation, Scenario, SearchOptions, ScheduleRun } from '../types';

const configuredBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) { super(message); this.name = 'ApiError'; this.status = status; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${configuredBase}/api/v1${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError('Cannot reach the ForgeIQ API. Start the FastAPI backend, then retry. Your form entries have not been submitted.', 0);
  }
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => null) as { detail?: string | { msg?: string; loc?: (string | number)[] }[]; message?: string } | null;
  if (!response.ok) {
    const detail = Array.isArray(payload?.detail) ? payload.detail.map(item => `${item.loc?.slice(-1)[0] ?? 'Field'}: ${item.msg ?? 'invalid value'}`).join('; ') : payload?.detail;
    throw new ApiError(detail || payload?.message || `Request failed with HTTP ${response.status}.`, response.status);
  }
  return payload as T;
}

export async function loadCollections(): Promise<ApiCollections> {
  const [jobs, machines, operations, schedules] = await Promise.all([
    request<{ items: Job[] }>('/jobs'), request<{ items: Machine[] }>('/machines'),
    request<{ items: Operation[] }>('/operations'), request<{ items: ScheduleRun[] }>('/schedules'),
  ]);
  return { jobs: jobs.items, machines: machines.items, operations: operations.items, schedules: schedules.items };
}
export const getSchedule = (id: string) => request<ScheduleRun>(`/schedules/${encodeURIComponent(id)}`);
export const createJob = (data: Omit<Job, 'is_sample'> & Partial<Pick<Job, 'is_sample'>>) => request<Job>('/jobs', { method: 'POST', body: JSON.stringify(data) });
export const updateJob = (id: string, data: Omit<Job, 'is_sample'> & Partial<Pick<Job, 'is_sample'>>) => request<Job>(`/jobs/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteJob = (id: string) => request<void>(`/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const createMachine = (data: Omit<Machine, 'is_sample'> & Partial<Pick<Machine, 'is_sample'>>) => request<Machine>('/machines', { method: 'POST', body: JSON.stringify(data) });
export const updateMachine = (id: string, data: Omit<Machine, 'is_sample'> & Partial<Pick<Machine, 'is_sample'>>) => request<Machine>(`/machines/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteMachine = (id: string) => request<void>(`/machines/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const createOperation = (data: Omit<Operation, 'is_sample'> & Partial<Pick<Operation, 'is_sample'>>) => request<Operation>('/operations', { method: 'POST', body: JSON.stringify(data) });
export const updateOperation = (id: string, data: Omit<Operation, 'is_sample'> & Partial<Pick<Operation, 'is_sample'>>) => request<Operation>(`/operations/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteOperation = (id: string) => request<void>(`/operations/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const loadSample = () => request<{ message: string }>('/sample', { method: 'POST' });
export const loadAutomotiveSample = () => request<{ message: string; is_simulated: boolean; jobs: number; machines: number; operations: number }>('/automotive/sample', { method: 'POST' });
export const removeSample = () => request<{ message: string }>('/sample', { method: 'DELETE' });
export const generateSchedules = (data: { scenario: Scenario; algorithms: AlgorithmName[]; objective: Objective; secondary_objectives: Objective[]; hard_due_dates: boolean; search_options: SearchOptions }) => request<ScheduleRun>('/schedules/generate', { method: 'POST', body: JSON.stringify(data) });
export const selectSchedule = (runId: string, algorithm: AlgorithmName) => request<{ schedule_id: string; selected_algorithm_name: AlgorithmName; is_stale: boolean }>(`/schedules/${encodeURIComponent(runId)}/select`, { method: 'POST', body: JSON.stringify({ algorithm_name: algorithm }) });
export const fetchHealth = () => request<{ status: string }>('/health');
export const applyRescheduleEvent = (scheduleId: string, payload: DynamicRescheduleInput) => request<DynamicRescheduleResponse>(`/schedules/${encodeURIComponent(scheduleId)}/reschedule`, { method: 'POST', body: JSON.stringify(payload) });
export const fetchRescheduleHistory = (scheduleId: string) => request<{ items: DisruptionEvent[] }>(`/schedules/${encodeURIComponent(scheduleId)}/reschedules`);
export const fetchKnowledgeBase = () => request<Record<string, unknown>>('/knowledge-base');
export const fetchPlanningModel = () => request<Record<string, unknown>>('/planning/model');
export const fetchAutomotiveWorkflows = () => request<Record<string, unknown>>('/automotive/workflows');


export interface AITraceNode { id: number; parent_id: number | null; event: string; depth: number; g: number | null; h: number | null; f: number | null; action?: { operation_id: string; machine_id: string; start_minute: number; end_minute: number; preconditions?: string[]; effects?: string[] } | null; reason?: string | null; placements: { operation_id: string; machine_id: string; start_minute: number; end_minute: number }[]; }
export interface AITrace { trace_id: string; algorithm: string; scenario: Scenario; objective: string; nodes: AITraceNode[]; edges: { source: number; target: number }[]; truncated: boolean; result: AlgorithmResult; }
export interface AIExperiment { dataset_source: 'current' | 'saved_run'; schedule_id?: string; scenario: Scenario; objective: string; algorithms: AlgorithmName[]; max_expansions: number; max_seconds: number; max_trace_nodes: number; hard_due_dates?: boolean; }
const aiRequest = async <T,>(path: string, data?: unknown): Promise<T> => request<T>(path, data === undefined ? undefined : { method: 'POST', body: JSON.stringify(data) });
export const runAIExperiment = (data: AIExperiment) => aiRequest<{ dataset_source: string; schedule_id?: string; scenario: Scenario; objective: string; results: AlgorithmResult[]; traces: AITrace[] }>('/ai-search', data);
export const getAITrace = (id: string) => request<AITrace>(`/ai-search-traces/${encodeURIComponent(id)}`);
export const getAIOverview = () => request<Record<string, unknown>>('/ai-center');
export const compareAIRecommendations = (data: AIExperiment) => aiRequest<Record<string, unknown>>('/ai-recommendations', data);
export const runAIAgents = (data: Record<string, unknown>) => aiRequest<Record<string, unknown>>('/agents', data);
export const inferBayesianRisk = (evidence: Record<string, boolean>) => aiRequest<{ posterior: Record<string, number>; risk_probability: number; assumptions: string[]; cpt: Record<string, unknown>; model: string }>('/bayesian-risk', { evidence });
