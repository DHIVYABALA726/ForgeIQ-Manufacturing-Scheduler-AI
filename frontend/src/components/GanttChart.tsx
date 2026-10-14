import { useMemo, useState } from 'react';
import { Clock3, ZoomIn, ZoomOut } from 'lucide-react';
import type { AlgorithmName, AlgorithmResult, Machine } from '../types';

const palette = ['#2563eb', '#0f766e', '#7c3aed', '#c2410c', '#0891b2', '#be123c', '#4d7c0f', '#9333ea'];
const clockLabel = (minute: number, originMs: number, span: number) => new Date(originMs + minute * 60_000).toLocaleString(undefined, span > 1_440 ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
const componentLabel = (value?: string) => ({ engine_block: 'Engine block', crankshaft: 'Crankshaft', brake_disc: 'Brake disc', other: 'Other' }[value || 'other'] || value || 'Other');

export default function GanttChart({ results, machines, jobs, initialAlgorithm }: { results: AlgorithmResult[]; machines: Machine[]; jobs: { id: string; name: string; release_at: string; due_at: string; component_type?: string }[]; initialAlgorithm?: AlgorithmName | null }) {
  const feasible = results.filter(result => result.feasible);
  const [algorithm, setAlgorithm] = useState<AlgorithmName>(initialAlgorithm || feasible[0]?.algorithm_name || 'FCFS');
  const [machineFilter, setMachineFilter] = useState('all');
  const [jobFilter, setJobFilter] = useState('all');
  const [zoom, setZoom] = useState(13);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const current = feasible.find(result => result.algorithm_name === algorithm) || feasible[0];
  const jobMap = useMemo(() => new Map(jobs.map((job, index) => [job.id, { ...job, color: palette[index % palette.length] }])), [jobs]);
  const operations = current?.scheduled_operations ?? [];
  const machinesPresent = [...new Set(operations.map(op => op.machine_id))];
  const rows = machines.filter(machine => machinesPresent.includes(machine.id) && (machineFilter === 'all' || machine.id === machineFilter));
  const visible = operations.filter(op => (machineFilter === 'all' || op.machine_id === machineFilter) && (jobFilter === 'all' || op.job_id === jobFilter));
  const originMs = jobs.length ? Math.min(...jobs.map(job => Date.parse(job.release_at)).filter(Number.isFinite)) : Date.now();
  const visibleJobIds = new Set(visible.map(op => op.job_id));
  const dueByJob = new Map(jobs.filter(job => visibleJobIds.has(job.id)).map(job => [job.id, (Date.parse(job.due_at) - originMs) / 60_000]));
  const lastSequence = new Map<string, number>();
  for (const op of operations) lastSequence.set(op.job_id, Math.max(lastSequence.get(op.job_id) ?? 0, op.sequence));
  const start = Math.min(0, ...visible.map(op => op.start_minute));
  const end = Math.max(1, ...visible.map(op => op.end_minute), ...dueByJob.values());
  const span = Math.max(1, end - start);
  const chartWidth = Math.max(900, 154 + span * zoom + 24);
  const chartHeight = 82 + rows.length * 66;
  const tick = span > 1_440 ? 360 : span > 720 ? 180 : span > 360 ? 60 : span > 180 ? 30 : span > 90 ? 15 : span > 35 ? 10 : 5;
  const ticks: number[] = [];
  for (let point = Math.ceil(start / tick) * tick; point <= end + 0.1; point += tick) ticks.push(point);
  const task = operations.find(op => op.operation_id === selectedId);

  if (!feasible.length || !current) return <div className="chart-empty"><div className="empty-icon"><Clock3 size={21}/></div><h3>No feasible schedule to display</h3><p>Generate at least one feasible schedule to see its operations here.</p></div>;
  return <div className="gantt-card">
    <div className="gantt-toolbar"><div className="gantt-selects"><label>Algorithm<select className="control control-sm" value={current.algorithm_name} onChange={e => setAlgorithm(e.target.value as AlgorithmName)}>{feasible.map(x => <option key={x.algorithm_name} value={x.algorithm_name}>{x.algorithm_name}</option>)}</select></label><label>Machine<select className="control control-sm" value={machineFilter} onChange={e => setMachineFilter(e.target.value)}><option value="all">All machines</option>{machines.map(m => <option key={m.id} value={m.id}>{m.id} · {m.name}</option>)}</select></label><label>Job<select className="control control-sm" value={jobFilter} onChange={e => setJobFilter(e.target.value)}><option value="all">All jobs</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.id} · {j.name}</option>)}</select></label></div><div className="zoom-controls"><span>TIME SCALE</span><button className="icon-button" aria-label="Zoom out" onClick={() => setZoom(x => Math.max(3, x - 2))}><ZoomOut size={16}/></button><input aria-label="Gantt zoom" type="range" min="3" max="32" value={zoom} onChange={e => setZoom(Number(e.target.value))}/><button className="icon-button" aria-label="Zoom in" onClick={() => setZoom(x => Math.min(32, x + 2))}><ZoomIn size={16}/></button></div></div>
    <div className="chart-legend">{jobs.filter(job => operations.some(op => op.job_id === job.id)).map(job => <span key={job.id} title={`${job.id} · ${componentLabel(job.component_type)}`}><i style={{ backgroundColor: jobMap.get(job.id)?.color }}/>{job.id}<small>{componentLabel(job.component_type)}</small></span>)}<span className="gantt-due-legend"><i/>Due date</span></div>
    <div className="gantt-scroll" role="region" aria-label="Interactive machine schedule timeline" tabIndex={0}><svg width={chartWidth} height={chartHeight} role="img" aria-label={`${current.algorithm_name} schedule Gantt chart`}>
      <rect width={chartWidth} height="100%" fill="#fff"/><text x="18" y="27" className="svg-head">MACHINE / OPERATION</text><text x="154" y="27" className="svg-head">LOCAL DATE / TIME</text>
      {ticks.map(point => { const x = 154 + (point - start) * zoom; return <g key={point}><line x1={x} x2={x} y1="46" y2={chartHeight} stroke="#e7edf4" strokeDasharray="3 4"/><text x={x + 3} y="43" className="svg-tick">{clockLabel(point, originMs, span)}</text></g>; })}
      {rows.map((machine, rowIndex) => { const y = 60 + rowIndex * 66; const rowOps = visible.filter(op => op.machine_id === machine.id); return <g key={machine.id}><rect x="0" y={y} width={chartWidth} height="66" fill={rowIndex % 2 ? '#fbfcfe' : '#fff'}/><line x1="0" x2={chartWidth} y1={y + 65} y2={y + 65} stroke="#edf1f6"/><text x="18" y={y + 25} className="svg-machine-id">{machine.id}</text><text x="18" y={y + 43} className="svg-machine-name">{machine.name}</text>
        {rowOps.filter(op => lastSequence.get(op.job_id) === op.sequence).map(op => { const due = dueByJob.get(op.job_id); if (due === undefined || due < start || due > end) return null; const x = 154 + (due - start) * zoom; return <g key={`due-${op.job_id}`} pointerEvents="none"><line x1={x} x2={x} y1={y + 6} y2={y + 58} stroke="#c2683c" strokeWidth="2" strokeDasharray="4 3"/><title>{`${op.job_id} due ${jobMap.get(op.job_id)?.due_at}`}</title></g>; })}
        {rowOps.map(op => { const x = 154 + (op.start_minute - start) * zoom; const w = Math.max(4, (op.end_minute - op.start_minute) * zoom); const color = jobMap.get(op.job_id)?.color ?? palette[0]; return <g key={op.operation_id} onClick={() => setSelectedId(op.operation_id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedId(op.operation_id); } }} role="button" tabIndex={0} aria-label={`${op.job_id} ${op.operation_name}, ${machine.name}, ${op.start_at} to ${op.end_at}, ${op.duration_minutes} minutes`} style={{ cursor: 'pointer' }}><rect x={x} y={y + 11} width={w} height="42" rx="5" fill={color} opacity=".93" stroke={selectedId === op.operation_id ? '#0f172a' : 'transparent'} strokeWidth="2"/><text x={x + 8} y={y + 29} className="svg-bar-title" pointerEvents="none">{w > 75 ? `${op.job_id} · ${op.operation_name}` : op.job_id}</text><text x={x + 8} y={y + 44} className="svg-bar-detail" pointerEvents="none">{w > 105 ? `${op.duration_minutes} min` : ''}</text><title>{`${op.job_id} / ${op.operation_name} · ${machine.name}\nStart ${op.start_at} · Finish ${op.end_at}\n${op.duration_minutes} minutes (processing ${op.processing_time_minutes} + setup ${op.setup_time_minutes})`}</title></g>; })}</g>; })}
    </svg></div>
    <div className="gantt-footer">{visible.length} scheduled operation{visible.length === 1 ? '' : 's'} <span>·</span> {clockLabel(start, originMs, span)}–{clockLabel(end, originMs, span)} local time <span>·</span> Idle gaps are left blank</div>
    {task && <aside className="task-detail" aria-live="polite"><div><div className="eyebrow">SELECTED OPERATION</div><strong>{task.job_id} · {task.operation_name}</strong><button className="icon-button close-detail" aria-label="Close operation details" onClick={() => setSelectedId(null)}>×</button></div><dl><dt>Automotive component</dt><dd>{componentLabel(jobMap.get(task.job_id)?.component_type)}</dd><dt>Machine</dt><dd>{task.machine_id} · {machines.find(m => m.id === task.machine_id)?.name}</dd><dt>Start</dt><dd>{new Date(task.start_at).toLocaleString()}</dd><dt>Finish</dt><dd>{new Date(task.end_at).toLocaleString()}</dd><dt>Duration</dt><dd>{task.duration_minutes} min ({task.processing_time_minutes} processing + {task.setup_time_minutes} setup)</dd><dt>Waiting</dt><dd>{task.waiting_time_minutes} min</dd><dt>Due</dt><dd>{new Date(task.due_at).toLocaleString()}</dd></dl></aside>}
  </div>;
}
