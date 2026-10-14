import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Scheduling from '../src/pages/Scheduling';
import { LocaleProvider } from '../src/i18n';
import { generateSchedules } from '../src/services/api';
import type { ApiCollections, ScheduleRun } from '../src/types';

vi.mock('../src/services/api', () => ({ generateSchedules: vi.fn() }));

const data: ApiCollections = {
  jobs: [{ id: 'J1', name: 'Engine block', product_name: 'Engine block', component_type: 'engine_block', status: 'queued', quantity: 2, priority: 'High', release_at: '2034-01-01T08:00:00Z', due_at: '2034-01-01T12:00:00Z', notes: null, is_sample: false }],
  machines: [{ id: 'M1', name: 'Mill', machine_type: 'CNC', available_from: '2034-01-01T08:00:00Z', available_until: null, is_available: true, setup_time_minutes: 0, processing_capabilities: ['cnc_milling'], maintenance_schedule: [], is_sample: false }],
  operations: [{ id: 'O1', job_id: 'J1', name: 'Mill', sequence: 1, eligible_machine_ids: ['M1'], processing_time_minutes: 20, setup_time_minutes: 0, predecessor_id: null, required_capability: 'cnc_milling', is_sample: false }],
  schedules: [],
};

describe('bounded scheduling controls', () => {
  it('sends selected AI search methods, limits and weights to the schedule endpoint', async () => {
    vi.mocked(generateSchedules).mockResolvedValue({ results: [] } as unknown as ScheduleRun);
    const onGenerated = vi.fn();
    const onNavigate = vi.fn();
    render(<LocaleProvider><Scheduling data={data} onGenerated={onGenerated} onNavigate={onNavigate}/></LocaleProvider>);

    expect(screen.getByLabelText('Maximum state expansions')).toHaveValue(2500);
    expect(screen.getByLabelText('Time limit (seconds)')).toHaveValue(2);
    fireEvent.change(screen.getByLabelText('Maximum state expansions'), { target: { value: '47' } });
    fireEvent.change(screen.getByLabelText('Time limit (seconds)'), { target: { value: '1.4' } });
    fireEvent.change(screen.getByLabelText('Reported machine-risk penalty'), { target: { value: '0.5' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /Depth-First Search/ }));
    fireEvent.click(screen.getByRole('button', { name: /Generate and Compare Schedules/ }));

    await waitFor(() => expect(generateSchedules).toHaveBeenCalledOnce());
    expect(generateSchedules).toHaveBeenCalledWith(expect.objectContaining({
      algorithms: expect.arrayContaining(['A* Search', 'Depth-First Search']),
      search_options: { max_expansions: 47, max_seconds: 1.4, weights: { makespan: 1, total_tardiness: 1, idle_time: 0, setup_time: 0, machine_risk: 0.5 } },
    }));
    expect(onGenerated).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it('switches scheduling control labels into Tamil and saves the selected locale', () => {
    window.localStorage.setItem('forgeiq-language', 'ta');
    render(<LocaleProvider><Scheduling data={data} onGenerated={vi.fn()} onNavigate={vi.fn()}/></LocaleProvider>);
    expect(screen.getByText('அட்டவணை அமைப்பு')).toBeInTheDocument();
    expect(screen.getByText('அதிகபட்ச நிலை விரிவாக்கங்கள்')).toBeInTheDocument();
  });
});
