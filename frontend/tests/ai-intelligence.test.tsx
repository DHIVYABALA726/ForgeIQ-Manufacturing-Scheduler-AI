import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StateSpaceTree from '../src/components/StateSpaceTree';
import BayesianRisk from '../src/pages/BayesianRisk';
import IntelligentAgents from '../src/pages/IntelligentAgents';
import type { AITrace } from '../src/services/api';

vi.mock('../src/services/api', () => ({
  inferBayesianRisk: vi.fn(async (evidence: Record<string, boolean>) => ({ posterior: { low: 1, elevated: 0 }, risk_probability: evidence.maintenance ? .2 : .03, assumptions: ['illustrative'], cpt: {}, model: 'Illustrative exact model' })),
  runAIAgents: vi.fn(async () => ({ recommendation: 'Review evidence.', agents: [{ id: 'a', agent: 'Production planner', status: 'ready', explanation: 'Read-only analysis', evidence: { jobs: 1 } }], activities: [{ id: 'a', agent: 'Production planner', status: 'ready', explanation: 'Read-only analysis' }] })),
}));

const trace: AITrace = { trace_id: 'trace', algorithm: 'A* Search', scenario: 'job_shop', objective: 'makespan', truncated: true, edges: [{ source: 0, target: 1 }], result: { algorithm_name: 'A* Search', scenario: 'job_shop', feasible: true, scheduled_operations: [], metrics: {}, computation_time_ms: 1 }, nodes: [
  { id: 0, parent_id: null, event: 'root', depth: 0, g: 0, h: 10, f: 10, placements: [] },
  { id: 1, parent_id: 0, event: 'generated', depth: 1, g: 5, h: 4, f: 9, action: { operation_id: 'OP-1', machine_id: 'M-1', start_minute: 0, end_minute: 5 }, placements: [{ operation_id: 'OP-1', machine_id: 'M-1', start_minute: 0, end_minute: 5 }] },
] };

describe('AI intelligence interactions', () => {
  beforeEach(() => vi.clearAllMocks());
  it('selects a captured trace node and displays its actual action and values', () => {
    render(<StateSpaceTree trace={trace} />);
    fireEvent.click(screen.getByRole('button', { name: 'generated node 1' }));
    expect(screen.getByText(/g\(n\) 5/)).toBeTruthy();
    expect(screen.getByText(/OP-1 → M-1/)).toBeTruthy();
    expect(screen.getByText(/Trace truncated at 2 displayed nodes/)).toBeTruthy();
  });
  it('updates Bayesian evidence and can reset it', async () => {
    render(<BayesianRisk />);
    const maintenance = screen.getByRole('checkbox', { name: /maintenance/i });
    fireEvent.click(maintenance);
    expect((maintenance as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /reset evidence/i }));
    expect((maintenance as HTMLInputElement).checked).toBe(false);
  });
  it('requires explicit confirmation before navigating into existing rescheduling', async () => {
    const onNavigate = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<IntelligentAgents onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole('button', { name: /run agent analysis/i }));
    const button = await screen.findByRole('button', { name: /review in dynamic rescheduling/i });
    fireEvent.click(button);
    expect(confirm).toHaveBeenCalled();
    expect(onNavigate).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(button);
    expect(onNavigate).toHaveBeenCalledWith('rescheduling');
  });
});
