import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Workspace from '../src/pages/Workspace';
import type { ApiCollections, ScheduleRun } from '../src/types';
import { LocaleProvider } from '../src/i18n';

const empty: ApiCollections = { jobs: [], machines: [], operations: [], schedules: [] };

const failedRun: ScheduleRun = {
  id: 'run-infeasible', scenario: 'parallel_machine', objective: 'makespan', secondary_objectives: [], hard_due_dates: true,
  dataset_version: 1, current_dataset_version: 1, is_stale: false, created_at: '2032-05-11T08:00:00Z',
  selected_algorithm_name: null, recommended_algorithm_name: null, recommendation_reason: 'No feasible result.', recommendation_details: {},
  results: [{ algorithm_name: 'FCFS', scenario: 'parallel_machine', feasible: false, scheduled_operations: [], metrics: {}, computation_time_ms: 1, error_message: 'Hard due-date constraint violated.' }],
  input_snapshot: { jobs: [], machines: [], operations: [], hard_due_dates: true },
};

describe('manufacturing workspace', () => {
  it('starts empty with zero counts and only loads a sample after explicit activation', () => {
    const loadSample = vi.fn();
    render(<LocaleProvider><Workspace data={empty} online staleCount={0} onNavigate={vi.fn()} onLoadSample={loadSample} onLoadAutomotiveSample={vi.fn()} onRemoveSample={vi.fn()} loading={false}/></LocaleProvider>);
    expect(screen.getByText(/No manufacturing data available/i)).toBeInTheDocument();
    expect(screen.getByText('MANUALLY ENTERED JOBS').parentElement).toHaveTextContent('0');
    expect(screen.getByRole('button', { name: /Load Sample Dataset/i })).toBeInTheDocument();
    expect(loadSample).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Load Sample Dataset/i }));
    expect(loadSample).toHaveBeenCalledOnce();
  });

  it('does not report Scheduled when every algorithm result is infeasible', () => {
    render(<LocaleProvider><Workspace data={{ ...empty, schedules: [failedRun] }} online staleCount={0} onNavigate={vi.fn()} onLoadSample={vi.fn()} onLoadAutomotiveSample={vi.fn()} onRemoveSample={vi.fn()} loading={false}/></LocaleProvider>);
    expect(screen.getByText('No feasible schedule')).toBeInTheDocument();
    expect(screen.getAllByText('SCHEDULED OPERATIONS')[0].closest('.stat-cell')).toHaveTextContent('0');
  });
});
