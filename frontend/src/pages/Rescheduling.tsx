import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, Plus, RefreshCw, Wrench, X } from 'lucide-react';
import GanttChart from '../components/GanttChart';
import { ApiError, applyRescheduleEvent, fetchRescheduleHistory, getSchedule } from '../services/api';
import { useLocale } from '../i18n';
import type { AlgorithmName, ApiCollections, ComponentType, DisruptionEvent, DisruptionType, DynamicRescheduleInput, Machine, ScheduleRun, SearchOptions } from '../types';

interface OperationDraft {
  name: string;
  machineIds: string[];
  processingMinutes: string;
  setupMinutes: string;
  requiredCapability: string;
}
interface Props {
  run: ScheduleRun | null;
  allRuns: ScheduleRun[];
  data: ApiCollections;
  onRescheduled: (run: ScheduleRun) => void;
  onLoadSchedule: (id: string) => Promise<void> | void;
  onNavigate: () => void;
}

const eventLabels: Record<DisruptionType, string> = {
  machine_breakdown: 'Machine breakdown',
  urgent_order: 'Urgent order',
  processing_delay: 'Processing delay',
  maintenance: 'Scheduled maintenance',
  machine_risk: 'Operator-reported high machine risk',
};
const initialSearchOptions: SearchOptions = { max_expansions: 2500, max_seconds: 2, weights: { makespan: 1, total_tardiness: 1, idle_time: 0, setup_time: 0, machine_risk: 0 } };
const componentTypes: { id: ComponentType; label: string }[] = [{ id: 'engine_block', label: 'Engine block' }, { id: 'crankshaft', label: 'Crankshaft' }, { id: 'brake_disc', label: 'Brake disc' }, { id: 'other', label: 'Other / generic manufacturing' }];
const localDateTime = (value?: string | Date) => {
  const date = value ? new Date(value) : new Date();
  if (!Number.isFinite(date.getTime())) return '';
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};
const utcIso = (value: string) => new Date(value).toISOString();
const plusMinutes = (value: string, minutes: number) => {
  const date = new Date(value);
  date.setMinutes(date.getMinutes() + minutes);
  return localDateTime(date);
};
const numeric = (value: number | null | undefined, suffix = ' min') => value == null || !Number.isFinite(value) ? 'N/A' : `${Number(value.toFixed(2)).toLocaleString()}${suffix}`;
const readableDate = (value: string) => new Date(value).toLocaleString();
const isStale = (schedule: ScheduleRun) => schedule.is_stale || schedule.current_dataset_version !== schedule.dataset_version;

function MetricCompare({ before, after }: { before: ScheduleRun; after: ScheduleRun }) {
  const algorithm = after.selected_algorithm_name || after.results.find(item => item.feasible)?.algorithm_name;
  const oldMetrics = before.results.find(item => item.algorithm_name === algorithm)?.metrics;
  const newMetrics = after.results.find(item => item.algorithm_name === algorithm)?.metrics;
  const metrics: { label: string; key: 'makespan' | 'total_tardiness' | 'machine_utilization' | 'idle_time_minutes' | 'setup_time_minutes'; percent?: boolean }[] = [
    { label: 'Makespan', key: 'makespan' },
    { label: 'Total tardiness', key: 'total_tardiness' },
    { label: 'Machine utilization', key: 'machine_utilization', percent: true },
    { label: 'Available-machine idle time', key: 'idle_time_minutes' },
    { label: 'Total setup time', key: 'setup_time_minutes' },
  ];
  return <div className="dynamic-metric-table" role="table" aria-label="Before and after production metrics">
    <div className="dynamic-metric-row dynamic-metric-head" role="row"><span>Measured metric</span><span>Before</span><span>After</span></div>
    {metrics.map(metric => <div className="dynamic-metric-row" role="row" key={metric.key}>
      <span>{metric.label}</span>
      <span>{numeric(oldMetrics?.[metric.key], metric.percent ? '%' : undefined)}</span>
      <strong>{numeric(newMetrics?.[metric.key], metric.percent ? '%' : undefined)}</strong>
    </div>)}
  </div>;
}

function GanttPair({ before, after, machines }: { before: ScheduleRun; after: ScheduleRun; machines: Machine[] }) {
  const details = after.dynamic_reschedule || after.input_snapshot?.dynamic_reschedule;
  const selected = details?.algorithm_name || after.selected_algorithm_name || after.results.find(item => item.feasible)?.algorithm_name;
  const beforeSnapshot = before.input_snapshot;
  const afterSnapshot = after.input_snapshot;
  const oldJobs = beforeSnapshot?.jobs || [];
  const newJobs = afterSnapshot?.jobs || [];
  const oldMachines = beforeSnapshot?.machines || machines;
  const newMachines = afterSnapshot?.machines || machines;
  const beforeResults = before.results.filter(item => item.algorithm_name === selected && item.feasible);
  const afterResults = after.results.filter(item => item.algorithm_name === selected && item.feasible);
  return <div className="dynamic-gantt-grid">
    <section className="dynamic-gantt-panel"><div className="dynamic-subheading"><div><span className="eyebrow">BEFORE THE EVENT</span><h3>Original schedule</h3></div><span className="tag tag-blue">{selected || 'Algorithm'}</span></div>
      <GanttChart key={`${before.id}-before-${selected}`} results={beforeResults} machines={oldMachines} jobs={oldJobs} initialAlgorithm={selected as AlgorithmName} />
    </section>
    <section className="dynamic-gantt-panel"><div className="dynamic-subheading"><div><span className="eyebrow">AFTER RE-OPTIMIZATION</span><h3>Revised schedule</h3></div><span className="tag tag-blue">{selected || 'Algorithm'}</span></div>
      <GanttChart key={`${after.id}-after-${selected}`} results={afterResults} machines={newMachines} jobs={newJobs} initialAlgorithm={selected as AlgorithmName} />
    </section>
  </div>;
}

export default function Rescheduling({ run, allRuns, data, onRescheduled, onLoadSchedule, onNavigate }: Props) {
  const { t } = useLocale();
  const [baseId, setBaseId] = useState(run?.id || allRuns[0]?.id || '');
  const [loadedRun, setLoadedRun] = useState<ScheduleRun | null>(run);
  const [eventType, setEventType] = useState<DisruptionType>('machine_breakdown');
  const [algorithm, setAlgorithm] = useState<AlgorithmName>('FCFS');
  const [searchOptions, setSearchOptions] = useState<SearchOptions>(initialSearchOptions);
  const [effectiveAt, setEffectiveAt] = useState(localDateTime());
  const [machineId, setMachineId] = useState('');
  const [repairUntil, setRepairUntil] = useState(plusMinutes(localDateTime(), 60));
  const [operationId, setOperationId] = useState('');
  const [delayMinutes, setDelayMinutes] = useState('30');
  const [riskNote, setRiskNote] = useState('');
  const [urgentId, setUrgentId] = useState('');
  const [urgentName, setUrgentName] = useState('');
  const [urgentProduct, setUrgentProduct] = useState('');
  const [urgentComponentType, setUrgentComponentType] = useState<ComponentType>('engine_block');
  const [urgentQuantity, setUrgentQuantity] = useState('1');
  const [urgentDue, setUrgentDue] = useState(plusMinutes(localDateTime(), 240));
  const [urgentOperations, setUrgentOperations] = useState<OperationDraft[]>([{ name: '', machineIds: [], processingMinutes: '30', setupMinutes: '0', requiredCapability: '' }]);
  const [history, setHistory] = useState<DisruptionEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [comparison, setComparison] = useState<{ before: ScheduleRun; after: ScheduleRun; event: DisruptionEvent } | null>(null);

  useEffect(() => {
    if (run?.id) {
      setLoadedRun(run);
      setBaseId(run.id);
    }
  }, [run?.id]);

  const listedRun = allRuns.find(item => item.id === baseId) || null;
  const baseRun = loadedRun?.id === baseId ? loadedRun : listedRun;

  useEffect(() => {
    if (!baseId || baseRun?.input_snapshot) return;
    let active = true;
    getSchedule(baseId).then(detail => { if (active) setLoadedRun(detail); }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : 'The selected saved run could not be loaded.');
    });
    return () => { active = false; };
  }, [baseId, baseRun?.input_snapshot]);

  useEffect(() => {
    if (!baseId) { setHistory([]); return; }
    let active = true;
    setHistoryError('');
    fetchRescheduleHistory(baseId).then(response => { if (active) setHistory(response.items); }).catch(reason => {
      if (active) setHistoryError(reason instanceof Error ? reason.message : 'Event history could not be loaded.');
    });
    return () => { active = false; };
  }, [baseId, run?.id]);

  const supportedAlgorithms = (baseRun?.results || []).filter(result => result.feasible && result.algorithm_name !== 'NEH').map(result => result.algorithm_name);
  const selectedResult = baseRun?.results.find(result => result.algorithm_name === algorithm && result.feasible) || baseRun?.results.find(result => result.feasible && result.algorithm_name !== 'NEH');
  const scheduleOperations = selectedResult?.scheduled_operations || [];
  const snapshotMachines = baseRun?.input_snapshot?.machines || data.machines;
  const snapshotJobs = baseRun?.input_snapshot?.jobs || data.jobs;
  const baseStale = baseRun ? isStale(baseRun) : false;
  const eventMinute = effectiveAt ? new Date(effectiveAt).getTime() : NaN;
  const operationsInProgress = scheduleOperations.filter(item => Date.parse(item.start_at) <= eventMinute && eventMinute < Date.parse(item.end_at));
  const completedAtEvent = scheduleOperations.filter(item => Date.parse(item.end_at) <= eventMinute);
  const existingJobIds = useMemo(() => new Set(snapshotJobs.map(job => job.id)), [snapshotJobs]);

  useEffect(() => {
    if (!baseRun) return;
    const best = baseRun.selected_algorithm_name || baseRun.recommended_algorithm_name || baseRun.results.find(item => item.feasible && item.algorithm_name !== 'NEH')?.algorithm_name;
    if (best) setAlgorithm(best);
    setSearchOptions(baseRun.input_snapshot?.search_options || initialSearchOptions);
    const result = baseRun.results.find(item => item.algorithm_name === best) || baseRun.results.find(item => item.feasible);
    const rows = result?.scheduled_operations || [];
    const reference = rows[Math.min(rows.length - 1, Math.floor(rows.length / 3))] || rows[0];
    const nextTime = localDateTime(reference?.start_at);
    if (nextTime) {
      setEffectiveAt(nextTime);
      setRepairUntil(plusMinutes(nextTime, 60));
      setUrgentDue(plusMinutes(nextTime, 240));
    }
    setMachineId(reference?.machine_id || snapshotMachines[0]?.id || '');
    setOperationId(rows.find(item => item.start_at <= nextTime && item.end_at > nextTime)?.operation_id || rows[0]?.operation_id || '');
  }, [baseId, baseRun?.id]);

  const machinesInSchedule = [...new Set(scheduleOperations.map(item => item.machine_id))]
    .map(id => snapshotMachines.find(machine => machine.id === id)).filter((machine): machine is Machine => Boolean(machine));

  const selectBaseRun = async (id: string) => {
    setBaseId(id);
    setComparison(null);
    setNotice('');
    setError('');
    const listed = allRuns.find(item => item.id === id);
    if (listed) setLoadedRun(listed);
    try {
      const detail = await getSchedule(id);
      setLoadedRun(detail);
      await onLoadSchedule(id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The saved schedule could not be loaded.');
    }
  };

  const setEffectiveTime = (value: string) => {
    setEffectiveAt(value);
    if (!repairUntil || new Date(repairUntil).getTime() <= new Date(value).getTime()) setRepairUntil(plusMinutes(value, 60));
    if (!urgentDue || new Date(urgentDue).getTime() <= new Date(value).getTime()) setUrgentDue(plusMinutes(value, 240));
  };

  const updateUrgentOperation = (index: number, patch: Partial<OperationDraft>) => {
    setUrgentOperations(current => current.map((item, position) => position === index ? { ...item, ...patch } : item));
  };

  const applyEvent = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!baseRun) { setError('Select a saved schedule before applying a production event.'); return; }
    if (baseStale) { setError('This schedule is outdated. Generate a fresh schedule from current manufacturing data first.'); return; }
    if (!baseRun.input_snapshot) { setError('The complete schedule input snapshot is unavailable. Reload the run before rescheduling.'); return; }
    if (!supportedAlgorithms.includes(algorithm)) { setError('Choose a feasible supported dispatch or state-space search result from this saved run.'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      const payload: DynamicRescheduleInput = {
        event_type: eventType,
        effective_at: utcIso(effectiveAt),
        algorithm_name: algorithm,
        search_options: searchOptions,
        completed_operation_ids: completedAtEvent.map(item => item.operation_id),
      };
      if (eventType === 'machine_breakdown' || eventType === 'maintenance') {
        payload.machine_id = machineId;
        payload.repair_until = utcIso(repairUntil);
      } else if (eventType === 'processing_delay') {
        payload.operation_id = operationId;
        payload.delay_minutes = Number(delayMinutes);
      } else if (eventType === 'machine_risk') {
        payload.machine_id = machineId;
        payload.risk_note = riskNote.trim() || 'Operator-reported high machine risk.';
      } else {
        const jobId = urgentId.trim();
        if (existingJobIds.has(jobId)) throw new Error(`Urgent Job ID ${jobId} already exists in this saved schedule.`);
        const opPayload = urgentOperations.map((operation, index) => ({
          id: `${jobId.slice(0, 66)}-op-${index + 1}`.slice(0, 80),
          job_id: jobId,
          name: operation.name.trim(),
          sequence: index + 1,
          eligible_machine_ids: operation.machineIds,
          processing_time_minutes: Number(operation.processingMinutes),
          setup_time_minutes: Number(operation.setupMinutes),
          required_capability: operation.requiredCapability.trim().toLowerCase() || null,
          predecessor_id: index ? `${jobId.slice(0, 66)}-op-${index}`.slice(0, 80) : null,
        }));
        if (opPayload.some(item => !item.name || item.eligible_machine_ids.length < 1 || item.processing_time_minutes <= 0 || item.setup_time_minutes < 0)) {
          throw new Error('Complete each urgent-order operation with a name, at least one eligible machine, positive processing minutes, and non-negative setup minutes.');
        }
        if (new Date(urgentDue).getTime() <= new Date(effectiveAt).getTime()) throw new Error('The urgent job due time must be later than its event time.');
        payload.urgent_job = {
          id: jobId, name: urgentName.trim(), product_name: urgentProduct.trim(), quantity: Number(urgentQuantity), priority: 'Critical', component_type: urgentComponentType, status: 'queued',
          release_at: utcIso(effectiveAt), due_at: utcIso(urgentDue), notes: 'Added during dynamic rescheduling.',
        };
        payload.urgent_operations = opPayload;
      }
      const response = await applyRescheduleEvent(baseRun.id, payload);
      setComparison({ before: baseRun, after: response.run, event: response.event });
      setLoadedRun(response.run);
      setBaseId(response.run.id);
      setNotice(`${eventLabels[eventType]} applied. Revised schedule ${response.run.id.slice(0, 8)} is saved; the original run is unchanged.`);
      onRescheduled(response.run);
    } catch (reason) {
      const message = reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : 'The event could not be applied. No partial revised schedule was saved.';
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  const openHistory = async (event: DisruptionEvent) => {
    setError('');
    setBusy(true);
    try {
      const [before, after] = await Promise.all([getSchedule(event.parent_schedule_id), getSchedule(event.revised_schedule_id)]);
      setComparison({ before, after, event });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The saved before/after schedules could not be loaded.');
    } finally { setBusy(false); }
  };

  const completedCount = completedAtEvent.length;
  const urgentValid = eventType !== 'urgent_order' || Boolean(urgentId.trim() && urgentName.trim() && urgentProduct.trim() && Number(urgentQuantity) > 0 && urgentOperations.length && new Date(urgentDue).getTime() > new Date(effectiveAt).getTime());
  const canApply = Boolean(baseRun && !baseStale && selectedResult?.feasible && supportedAlgorithms.length && effectiveAt && urgentValid && (eventType === 'processing_delay' ? operationsInProgress.some(item => item.operation_id === operationId) && Number(delayMinutes) > 0 : eventType === 'urgent_order' ? true : machineId));

  return <div className="page-shell rescheduling-page">
    <div className="page-heading"><div><div className="eyebrow">{t('EVENT RESPONSE / SCHEDULE REVISION')}</div><h1>{t('Dynamic rescheduling')}</h1><p className="page-subtitle">{t('Apply a production event to a saved run and inspect the measured before/after plan.')}</p></div>
      <div className="top-actions"><span className="connection-pill"><span/>{t('Operator-triggered simulation')}</span></div>
    </div>

    <div className="dynamic-disclaimer"><AlertTriangle size={17}/><span><strong>Event scope:</strong> These are operator-entered simulations, not live machine sensors or ML risk predictions. Revisions can use a feasible saved dispatch rule or state-space search result; no Genetic Algorithm is claimed. An interrupted non-preemptive operation on a failed/maintained machine is conservatively restarted at full duration after recovery.</span></div>

    {notice && <div className="alert alert-success" role="status"><CheckCircle2 size={16}/><span>{notice}</span></div>}
    {error && <div className="alert alert-error" role="alert"><AlertTriangle size={16}/><span>{error}</span></div>}

    <div className="dynamic-layout">
      <section className="form-panel dynamic-form-panel">
        <div className="panel-heading"><div className="dynamic-icon"><RefreshCw size={17}/></div><div><div className="eyebrow">{t('RESCHEDULING CONTROL')}</div><h2>{t('Describe the event')}</h2><p>{t('Completed operations are inferred from the chosen event time and kept fixed.')}</p></div></div>
        {allRuns.length === 0 ? <div className="dynamic-empty"><Clock3 size={21}/><h3>No saved schedule yet</h3><p>Generate and save at least one feasible schedule before simulating a disruption.</p><button className="button button-outline button-sm" onClick={onNavigate}>Open scheduling</button></div> : <form className="entry-form dynamic-entry-form" onSubmit={applyEvent}>
          <label className="field-label">Source schedule<select className="control" value={baseId} onChange={event => void selectBaseRun(event.target.value)}>
            {allRuns.map(item => <option key={item.id} value={item.id}>{item.created_at ? readableDate(item.created_at) : item.id.slice(0, 8)} · {item.scenario.replaceAll('_', ' ')} · {item.recommended_algorithm_name || 'No recommendation'}{item.is_stale ? ' · outdated' : ''}</option>)}
          </select></label>
          {baseStale && <p className="field-error">This run is outdated. Generate a current schedule before rescheduling.</p>}
          <div className="dynamic-form-grid">
            <label className="field-label">{t('Event type')}<select className="control" value={eventType} onChange={event => setEventType(event.target.value as DisruptionType)}>
              {Object.entries(eventLabels).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </select></label>
            <label className="field-label">Algorithm for revised schedule<select className="control" value={algorithm} onChange={event => setAlgorithm(event.target.value as AlgorithmName)} disabled={!supportedAlgorithms.length}>
              {supportedAlgorithms.length ? supportedAlgorithms.map(name => <option key={name} value={name}>{name}</option>) : <option value="FCFS">No supported feasible rule</option>}
            </select></label>
            <label className="field-label">Event effective time (local)<input className="control" type="datetime-local" value={effectiveAt} onChange={event => setEffectiveTime(event.target.value)} required/></label>
            <div className="dynamic-progress-box"><strong>{completedCount}</strong><span>operation{completedCount === 1 ? '' : 's'} complete by event time</span><small>{operationsInProgress.length} in progress · unaffected active work stays fixed</small></div>

            {(eventType === 'machine_breakdown' || eventType === 'maintenance' || eventType === 'machine_risk') && <>
              <label className="field-label">Affected machine<select className="control" value={machineId} onChange={event => setMachineId(event.target.value)} required>
                <option value="">Choose a machine</option>{machinesInSchedule.map(machine => <option key={machine.id} value={machine.id}>{machine.id} · {machine.name}</option>)}
              </select></label>
              {eventType !== 'machine_risk' && <label className="field-label">Repair / maintenance ends (local)<input className="control" type="datetime-local" min={effectiveAt} value={repairUntil} onChange={event => setRepairUntil(event.target.value)} required/></label>}
              {eventType === 'machine_risk' && <label className="field-label">Operator note<input className="control" value={riskNote} onChange={event => setRiskNote(event.target.value)} placeholder="e.g. vibration alert observed"/></label>}
            </>}

            {eventType === 'processing_delay' && <>
              <label className="field-label">Running operation<select className="control" value={operationId} onChange={event => setOperationId(event.target.value)} required>
                <option value="">Choose an in-progress operation</option>{operationsInProgress.map(item => <option key={item.operation_id} value={item.operation_id}>{item.operation_id} · {item.job_id} · {item.operation_name} on {item.machine_id}</option>)}
              </select></label>
              <label className="field-label">Additional processing delay (minutes)<input className="control" type="number" min="1" max="1000000" step="1" value={delayMinutes} onChange={event => setDelayMinutes(event.target.value)} required/></label>
            </>}

            {eventType === 'urgent_order' && <div className="dynamic-urgent-fields">
              <div className="dynamic-subheading"><div><span className="eyebrow">NEW ORDER</span><h3>Urgent job details</h3></div><span className="priority-tag priority-critical">Critical</span></div>
              <div className="dynamic-form-grid">
                <label className="field-label">Job ID<input className="control" value={urgentId} onChange={event => setUrgentId(event.target.value)} maxLength={80} required/></label>
                <label className="field-label">Job name<input className="control" value={urgentName} onChange={event => setUrgentName(event.target.value)} maxLength={160} required/></label>
                <label className="field-label">Product<input className="control" value={urgentProduct} onChange={event => setUrgentProduct(event.target.value)} maxLength={160} required/></label>
                <label className="field-label">{t('Automotive component type')}<select className="control" value={urgentComponentType} onChange={event => setUrgentComponentType(event.target.value as ComponentType)}>{componentTypes.map(item => <option key={item.id} value={item.id}>{t(item.label)}</option>)}</select></label>
                <label className="field-label">Quantity<input className="control" type="number" min="1" step="1" value={urgentQuantity} onChange={event => setUrgentQuantity(event.target.value)} required/></label>
                <label className="field-label dynamic-full-field">Urgent due time (local)<input className="control" type="datetime-local" min={effectiveAt} value={urgentDue} onChange={event => setUrgentDue(event.target.value)} required/></label>
              </div>
              <div className="dynamic-subheading dynamic-operations-title"><div><span className="eyebrow">{t('ORDER ROUTING')}</span><h3>{t('Ordered operations')}</h3></div><button className="button button-outline button-sm" type="button" onClick={() => setUrgentOperations(items => [...items, { name: '', machineIds: [], processingMinutes: '30', setupMinutes: '0', requiredCapability: '' }])}><Plus size={14}/>{t('Add an operation')}</button></div>
              {urgentOperations.map((operation, index) => <div className="urgent-operation-card" key={index}>
                <div className="urgent-operation-head"><strong>Operation {index + 1}</strong>{urgentOperations.length > 1 && <button className="icon-button" type="button" aria-label={`Remove operation ${index + 1}`} onClick={() => setUrgentOperations(items => items.filter((_, i) => i !== index))}><X size={15}/></button>}</div>
                <div className="dynamic-form-grid">
                  <label className="field-label">Operation name<input className="control" value={operation.name} onChange={event => updateUrgentOperation(index, { name: event.target.value })} maxLength={160} required/></label>
                  <label className="field-label">Eligible machine(s)<select className="control" multiple size={Math.min(3, Math.max(2, snapshotMachines.length))} value={operation.machineIds} onChange={event => updateUrgentOperation(index, { machineIds: Array.from(event.target.selectedOptions, option => option.value) })} required>
                    {snapshotMachines.map(machine => <option key={machine.id} value={machine.id}>{machine.id} · {machine.name}{!machine.is_available ? ' · unavailable' : ''}</option>)}
                  </select><small className="dynamic-field-help">Hold Ctrl (Windows) to select alternatives.</small></label>
                  <label className="field-label">Processing (minutes)<input className="control" type="number" min="1" step="1" value={operation.processingMinutes} onChange={event => updateUrgentOperation(index, { processingMinutes: event.target.value })} required/></label>
                  <label className="field-label">Setup (minutes)<input className="control" type="number" min="0" step="1" value={operation.setupMinutes} onChange={event => updateUrgentOperation(index, { setupMinutes: event.target.value })} required/></label>
                  <label className="field-label dynamic-full-field">{t('Required capability (optional)')}<input className="control" maxLength={80} placeholder="cnc_milling" value={operation.requiredCapability} onChange={event => updateUrgentOperation(index, { requiredCapability: event.target.value })}/></label>
                </div>
              </div>)}
              <p className="dynamic-field-help">Operations are stored in this order; each later operation depends on the previous one. The urgent job is released at event time and added to manufacturing data only if the revised schedule is feasible.</p>
            </div>}
          </div>
          {selectedResult?.search_stats && <div className="search-controls dynamic-search-controls"><div className="search-controls-heading"><strong>Bounded search settings</strong><span>Backend uses these on the revised schedule</span></div><div className="search-limit-grid"><label>Maximum state expansions<input className="control" type="number" min="1" max="100000" step="1" value={searchOptions.max_expansions} onChange={event => setSearchOptions(current => ({ ...current, max_expansions: Number(event.target.value) }))}/></label><label>Time limit (seconds)<input className="control" type="number" min="0.01" max="30" step="0.1" value={searchOptions.max_seconds} onChange={event => setSearchOptions(current => ({ ...current, max_seconds: Number(event.target.value) }))}/></label></div><div className="search-weight-grid">{(['makespan', 'total_tardiness', 'idle_time', 'setup_time', 'machine_risk'] as const).map(key => <label key={key}>{({ makespan: 'Makespan', total_tardiness: 'Tardiness', idle_time: 'Idle gaps', setup_time: 'Setup time', machine_risk: 'Risk penalty' })[key]}<input className="control" type="number" min="0" max="1000" step="0.1" value={searchOptions.weights[key]} onChange={event => setSearchOptions(current => ({ ...current, weights: { ...current.weights, [key]: Math.max(0, Number(event.target.value)) } }))}/></label>)}</div><small className="dynamic-field-help">If the new search reaches its bound, a complete feasible result is kept when available and is clearly marked as unproven. No partial schedule is returned.</small></div>}
          <div className="dynamic-preview-note"><Wrench size={15}/><span>The selected saved run is not edited. A new run and disruption-history record are created only if the revised schedule passes its constraints.</span></div>
          <div className="form-actions"><span>NEH / permutation-flow-shop rescheduling is not yet supported.</span><button className="button button-primary" type="submit" disabled={busy || !canApply}><RefreshCw size={15} className={busy ? 'dynamic-spin' : ''}/>{busy ? 'Re-optimizing…' : 'Apply event & reschedule'}</button></div>
        </form>}
      </section>

      <section className="records-panel dynamic-history-panel">
        <div className="records-heading"><div><div className="eyebrow">AUDIT TRAIL</div><h2>Disruption history</h2></div><span className="tag tag-blue">{history.length}</span></div>
        {historyError && <div className="field-error">{historyError}</div>}
        {history.length ? <div className="dynamic-event-list">{history.map(item => <article className="dynamic-event-item" key={item.id}>
          <div className="dynamic-event-main"><span className="priority-tag priority-high">{eventLabels[item.event_type]}</span><time>{readableDate(item.effective_at)}</time><p>{item.explanation}</p><small>Run {item.parent_schedule_id.slice(0, 8)} → {item.revised_schedule_id.slice(0, 8)} · {item.impact.moved_operation_ids.length} moved · {item.impact.stability_percent}% stable</small></div>
          <button className="button button-outline button-sm" type="button" onClick={() => void openHistory(item)} disabled={busy}>Compare</button>
        </article>)}</div> : <div className="mini-empty">No disruption events have been recorded for this saved schedule.</div>}
      </section>
    </div>

    {comparison && <section className="dynamic-results-section">
      <div className="section-title-row dynamic-results-title"><div><div className="eyebrow">SAVED RESCHEDULE / {comparison.event.id.slice(0, 8)}</div><h2>{eventLabels[comparison.event.event_type]} · measured impact</h2><p>{comparison.event.explanation}</p></div><span className="dynamic-stability"><strong>{comparison.event.impact.stability_percent}%</strong><small>schedule stability</small></span></div>
      <div className="dynamic-result-summary"><span><strong>Effective:</strong> {readableDate(comparison.event.effective_at)}</span><span><strong>Affected jobs:</strong> {comparison.event.impact.affected_job_ids.join(', ') || 'None identified'}</span><span><strong>Operations completed by event time:</strong> {comparison.event.impact.completed_operation_ids.join(', ') || 'None'}</span></div>
      {comparison.event.impact.restarted_operation_ids.length > 0 && <div className="alert alert-warning"><AlertTriangle size={15}/><span>Restarted from full duration after recovery: {comparison.event.impact.restarted_operation_ids.join(', ')}. This is a conservative, non-preemptive simulation assumption.</span></div>}
      {comparison.event.impact.risk_fallback_operation_ids.length > 0 && <div className="alert alert-warning"><AlertTriangle size={15}/><span>Risky-machine fallback was required for: {comparison.event.impact.risk_fallback_operation_ids.join(', ')}.</span></div>}
      <MetricCompare before={comparison.before} after={comparison.after}/>
      {comparison.event.impact.moved_operations.length > 0 && <div className="dynamic-moved-list"><div className="dynamic-subheading"><div><span className="eyebrow">CHANGED ASSIGNMENTS</span><h3>{comparison.event.impact.moved_operations.length} operation(s) moved or extended</h3></div></div><div className="dynamic-table-scroll"><table><thead><tr><th>Operation / job</th><th>Machine</th><th>Start time</th><th>Finish time</th></tr></thead><tbody>{comparison.event.impact.moved_operations.map(item => <tr key={item.operation_id}><td><strong>{item.operation_id}</strong><small>{item.job_id} · {item.operation_name}</small></td><td>{item.machine_before} <ArrowRight size={13}/> {item.machine_after}</td><td>{readableDate(item.start_before)}<small>→ {readableDate(item.start_after)}</small></td><td>{readableDate(item.end_before)}<small>→ {readableDate(item.end_after)}</small></td></tr>)}</tbody></table></div></div>}
      {comparison.event.impact.added_operation_ids.length > 0 && <p className="dynamic-added-note">Added with urgent order: {comparison.event.impact.added_operation_ids.join(', ')}.</p>}
      <GanttPair before={comparison.before} after={comparison.after} machines={snapshotMachines}/>
      <p className="dynamic-stability-note">Stability = {comparison.event.impact.stability_definition}</p>
    </section>}
  </div>;
}
