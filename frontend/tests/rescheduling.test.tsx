import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Rescheduling from '../src/pages/Rescheduling';
import { reconcileScheduleRuns } from '../src/services/run-history';
import type { ApiCollections, DisruptionEvent, ScheduleRun } from '../src/types';
import { LocaleProvider } from '../src/i18n';

const apiMocks = vi.hoisted(() => ({
  apply: vi.fn(), history: vi.fn(), getSchedule: vi.fn(),
}));
vi.mock('../src/services/api', () => ({
  ApiError: class ApiError extends Error {},
  applyRescheduleEvent: apiMocks.apply,
  fetchRescheduleHistory: apiMocks.history,
  getSchedule: apiMocks.getSchedule,
}));
vi.mock('../src/components/GanttChart', () => ({ default: () => <div data-testid="actual-gantt"/> }));

const operation = {
  operation_id: 'OP-1', job_id: 'J-1', machine_id: 'M-1', operation_name: 'Mill', sequence: 1,
  start_minute: 0, end_minute: 60, processing_time_minutes: 60, setup_time_minutes: 0,
  duration_minutes: 60, waiting_time_minutes: 0, due_minute: 360, due_at: '2034-03-18T14:00:00Z',
  start_at: '2034-03-18T08:00:00Z', end_at: '2034-03-18T09:00:00Z',
};
const metric = { makespan: 60, total_tardiness: 0, machine_utilization: 100, idle_time_minutes: 0, setup_time_minutes: 0 };
const job = { id: 'J-1', name: 'Job one', product_name: 'Bracket', quantity: 4, priority: 'High' as const, release_at: '2034-03-18T08:00:00Z', due_at: '2034-03-18T14:00:00Z', notes: '', is_sample: false };
const machine = { id: 'M-1', name: 'CNC 1', machine_type: 'CNC', available_from: '2034-03-18T08:00:00Z', available_until: null, is_available: true, setup_time_minutes: 0, is_sample: false };
function makeRun(id: string): ScheduleRun {
  return {
    id, scenario: 'parallel_machine', objective: 'makespan', secondary_objectives: [], hard_due_dates: false,
    dataset_version: 1, current_dataset_version: 1, is_stale: false, created_at: '2034-03-18T07:00:00Z',
    selected_algorithm_name: 'FCFS', recommended_algorithm_name: 'FCFS', recommendation_reason: 'Minimum measured makespan',
    results: [{ algorithm_name: 'FCFS', scenario: 'parallel_machine', feasible: true, scheduled_operations: [operation], metrics: metric, computation_time_ms: 1 }],
    input_snapshot: { jobs: [job], machines: [machine], operations: [{ id: 'OP-1', job_id: 'J-1', name: 'Mill', sequence: 1, eligible_machine_ids: ['M-1'], processing_time_minutes: 60, setup_time_minutes: 0, is_sample: false }] },
  };
}
const baseRun = makeRun('run-source');
const revisedRun = makeRun('run-revised');
const event: DisruptionEvent = {
  id: 'event-1', parent_schedule_id: baseRun.id, revised_schedule_id: revisedRun.id,
  event_type: 'machine_breakdown', effective_at: '2034-03-18T08:15:00Z',
  event_payload: { machine_id: 'M-1', repair_until: '2034-03-18T09:00:00Z' },
  impact: {
    affected_job_ids: ['J-1'], affected_operation_ids: ['OP-1'], moved_operation_ids: ['OP-1'], moved_operations: [], added_operation_ids: [],
    completed_operation_ids: [], locked_operation_ids: [], restarted_operation_ids: ['OP-1'], risk_fallback_operation_ids: [],
    stability_percent: 0, stability_definition: 'Percentage of unchanged operation placements.', shared_operation_count: 1, unchanged_operation_count: 0,
    metrics_before: metric, metrics_after: { ...metric, makespan: 120 }, algorithm_name: 'FCFS', scenario: 'parallel_machine',
  },
  explanation: 'Machine M-1 is blocked until repair.', created_at: '2034-03-18T08:15:00Z',
};
const collections: ApiCollections = { jobs: [job], machines: [machine], operations: [], schedules: [baseRun] };

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.history.mockResolvedValue({ items: [] });
  apiMocks.getSchedule.mockImplementation(async (id: string) => id === baseRun.id ? baseRun : revisedRun);
  apiMocks.apply.mockResolvedValue({ event, run: revisedRun });
});

describe('dynamic rescheduling', () => {
  it('immediately marks saved runs stale when the backend dataset version advances for an urgent order', () => {
    const olderRun = { ...makeRun('old-run'), dataset_version: 2, is_stale: false };
    const previouslyStaleRun = { ...makeRun('stale-run'), dataset_version: 1, current_dataset_version: 2, is_stale: true };
    const urgentRevision = { ...makeRun('urgent-revision'), dataset_version: 3, current_dataset_version: 3, is_stale: false };
    const reconciled = reconcileScheduleRuns([olderRun, previouslyStaleRun], urgentRevision);
    expect(reconciled.map(item => item.id)).toEqual(['urgent-revision', 'old-run', 'stale-run']);
    expect(reconciled[0]).toMatchObject({ current_dataset_version: 3, is_stale: false });
    expect(reconciled[1]).toMatchObject({ current_dataset_version: 3, is_stale: true });
    expect(reconciled[2]).toMatchObject({ current_dataset_version: 3, is_stale: true });
  });

  it('submits the selected machine event and renders saved before/after impact', async () => {
    const onRescheduled = vi.fn();
    render(<LocaleProvider><Rescheduling run={baseRun} allRuns={[baseRun]} data={collections} onRescheduled={onRescheduled} onLoadSchedule={vi.fn()} onNavigate={vi.fn()}/></LocaleProvider>);
    fireEvent.click(screen.getByRole('button', { name: /Apply event & reschedule/i }));
    await waitFor(() => expect(apiMocks.apply).toHaveBeenCalledTimes(1));
    expect(apiMocks.apply).toHaveBeenCalledWith(baseRun.id, expect.objectContaining({
      event_type: 'machine_breakdown', algorithm_name: 'FCFS', machine_id: 'M-1', repair_until: expect.stringMatching(/^2034-03-18T09:00:00/),
    }));
    await screen.findByRole('heading', { name: /Machine breakdown · measured impact/i });
    expect(screen.getByText(/Original schedule/)).toBeInTheDocument();
    expect(screen.getAllByText(/Revised schedule/).length).toBeGreaterThan(0);
    expect(screen.getByText(/schedule stability/i)).toBeInTheDocument();
    expect(screen.getAllByTestId('actual-gantt')).toHaveLength(2);
    expect(onRescheduled).toHaveBeenCalledWith(revisedRun);
  });
});
