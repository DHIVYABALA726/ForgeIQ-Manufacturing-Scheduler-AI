import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Results from '../src/pages/Results';
import type { ApiCollections, AlgorithmResult, ScheduleRun } from '../src/types';
import { LocaleProvider } from '../src/i18n';

vi.mock('../src/components/GanttChart', () => ({ default: () => null }));
const empty: ApiCollections = { jobs: [], machines: [], operations: [], schedules: [] };
const result = (name: AlgorithmResult['algorithm_name']): AlgorithmResult => ({ algorithm_name: name, scenario: 'parallel_machine', feasible: true, scheduled_operations: [], metrics: { makespan: 20 }, computation_time_ms: 0.4 });
function makeRun(id: string, recommended: ScheduleRun['recommended_algorithm_name'], selected: ScheduleRun['selected_algorithm_name'] = null, names: AlgorithmResult['algorithm_name'][] = ['FCFS', 'SPT']): ScheduleRun {
  return { id, scenario: 'parallel_machine', objective: 'makespan', secondary_objectives: [], hard_due_dates: false, dataset_version: 1, current_dataset_version: 1, is_stale: false, created_at: '2032-05-11T08:00:00Z', selected_algorithm_name: selected, recommended_algorithm_name: recommended, recommendation_reason: 'Measured comparison', recommendation_details: {}, results: names.map(result), input_snapshot: { jobs: [], machines: [], operations: [] } };
}

describe('saved schedule results', () => {
  it('uses the next saved run selection rather than a stale algorithm selected on the previous run', () => {
    const runA = makeRun('run-a', 'FCFS');
    const runB = makeRun('run-b', 'FCFS', 'EDD', ['FCFS', 'EDD', 'SPT']);
    const props = { run: runA, allRuns: [runA, runB], data: { ...empty, schedules: [runA, runB] }, initialView: 'gantt' as const, onLoadSchedule: vi.fn(async () => {}) };
    const { rerender } = render(<LocaleProvider><Results {...props}/></LocaleProvider>);
    const select = screen.getByLabelText('Selected schedule') as HTMLSelectElement;
    expect(select.value).toBe('FCFS');
    fireEvent.change(select, { target: { value: 'SPT' } });
    expect(select.value).toBe('SPT');
    rerender(<LocaleProvider><Results {...props} run={runB}/></LocaleProvider>);
    expect((screen.getByLabelText('Selected schedule') as HTMLSelectElement).value).toBe('EDD');
  });

  it('shows persisted AI-search evidence and component details from the input snapshot', () => {
    const run = makeRun('run-ai', 'A* Search', null, ['A* Search']);
    run.results[0].search_stats = { states_expanded: 17, states_generated: 42, duplicate_states: 6, termination_status: 'optimal', optimality_proven: true, max_expansions: 120, max_seconds: 1.25 };
    run.results[0].scheduled_operations = [{ operation_id: 'ENG-OP1', job_id: 'AUTO-ENG', machine_id: 'M-MILL', operation_name: 'Milling', sequence: 1, start_minute: 0, end_minute: 20, processing_time_minutes: 20, setup_time_minutes: 0, duration_minutes: 20, waiting_time_minutes: 0, due_minute: 180, due_at: '2032-05-11T11:00:00Z', start_at: '2032-05-11T08:00:00Z', end_at: '2032-05-11T08:20:00Z' }];
    run.input_snapshot = {
      jobs: [{ id: 'AUTO-ENG', name: 'Engine block batch', product_name: 'Engine block', component_type: 'engine_block', status: 'queued', quantity: 4, priority: 'High', release_at: '2032-05-11T08:00:00Z', due_at: '2032-05-11T11:00:00Z', is_sample: false }],
      machines: [{ id: 'M-MILL', name: 'Milling cell', machine_type: 'CNC', available_from: '2032-05-11T08:00:00Z', available_until: null, is_available: true, setup_time_minutes: 0, processing_capabilities: ['cnc_milling'], maintenance_schedule: [], is_sample: false }],
      operations: [{ id: 'ENG-OP1', job_id: 'AUTO-ENG', name: 'Milling', sequence: 1, eligible_machine_ids: ['M-MILL'], processing_time_minutes: 20, setup_time_minutes: 0, predecessor_id: null, required_capability: 'cnc_milling', is_sample: false }],
    };
    render(<LocaleProvider><Results run={run} allRuns={[run]} data={empty} initialView="report" onLoadSchedule={vi.fn(async () => {})}/></LocaleProvider>);
    expect(screen.getByText('Search evidence and optimality status')).toBeInTheDocument();
    const searchRow = screen.getAllByRole('row').find(row => row.textContent?.includes('A* Search') && row.textContent.includes('42'));
    expect(searchRow).toBeDefined();
    expect(within(searchRow!).getByText('17')).toBeInTheDocument();
    expect(within(searchRow!).getByText('Proven')).toBeInTheDocument();
    const automotiveRow = screen.getAllByRole('row').find(row => row.textContent?.includes('AUTO-ENG'));
    expect(automotiveRow).toBeDefined();
    expect(within(automotiveRow!).getAllByText('Engine block').length).toBeGreaterThan(0);
    expect(within(automotiveRow!).getByText(/1\. Milling/)).toBeInTheDocument();
  });
});
