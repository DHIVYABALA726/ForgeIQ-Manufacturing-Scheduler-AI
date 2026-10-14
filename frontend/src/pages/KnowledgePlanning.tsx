import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Database, Network, RefreshCw, ShieldCheck } from 'lucide-react';
import { fetchAutomotiveWorkflows, fetchKnowledgeBase, fetchPlanningModel } from '../services/api';
import { useLocale } from '../i18n';

interface Facts {
  predicates: string[];
  facts: {
    jobs: { job_id: string; component_type: string; priority: string; status: string; due_at: string }[];
    machines: { machine_id: string; type: string; available: boolean; capabilities: string[]; maintenance_schedule: { starts_at: string; ends_at: string; reason?: string | null }[] }[];
    operations: { operation_id: string; job_id: string; sequence: number; required_capability?: string | null }[];
    compatible: { operation_id: string; machine_id: string; required_capability?: string | null }[];
    precedes: { before: string; after: string }[];
    finished: { operation_id: string; at_minute: number }[];
  };
  rules: string[];
  counts: Record<string, number>;
  predicate_definitions: Record<string, string>;
}
interface Action {
  name: string; operation_id: string; machine_id: string; start_minute: number; end_minute: number;
  preconditions: string[]; effects: string[];
}
interface PlanningModel { valid: boolean; validation_errors: string[]; actions: Action[]; }
interface Workflows {
  is_simulated_learning_example: boolean; notice: string;
  workflows: Record<string, { label: string; steps: { sequence: number; name: string; required_capability: string; suggested_minutes: number }[] }>;
}
const emptyFacts: Facts = { predicates: [], facts: { jobs: [], machines: [], operations: [], compatible: [], precedes: [], finished: [] }, rules: [], counts: {}, predicate_definitions: {} };
const componentName = (value: string) => ({ engine_block: 'Engine block', crankshaft: 'Crankshaft', brake_disc: 'Brake disc', other: 'Other / unspecified' }[value] || value);

export default function KnowledgePlanning() {
  const { t } = useLocale();
  const [facts, setFacts] = useState<Facts>(emptyFacts);
  const [model, setModel] = useState<PlanningModel | null>(null);
  const [workflows, setWorkflows] = useState<Workflows | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [nextFacts, nextModel, nextWorkflows] = await Promise.all([fetchKnowledgeBase(), fetchPlanningModel(), fetchAutomotiveWorkflows()]);
      setFacts(nextFacts as unknown as Facts);
      setModel(nextModel as unknown as PlanningModel);
      setWorkflows(nextWorkflows as unknown as Workflows);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The knowledge and planning data could not be loaded.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const entries = Object.entries(facts.facts || {});
  return <div className="page-shell knowledge-page">
    <header className="page-heading">
      <div><div className="eyebrow">{t('SYMBOLIC MODEL / COURSE MAPPING')}</div><h1>{t('Automotive knowledge & planning')}</h1><p className="page-subtitle">{t('Inspect facts grounded in the entered dataset and the same executable actions that generate search successors.')}</p></div>
      <button className="button button-outline" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15}/>{loading ? t('Refreshing…') : t('Refresh facts')}</button>
    </header>

    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {loading && <div className="alert alert-warning" role="status">{t('Loading persisted manufacturing facts and applicable planning actions…')}</div>}
    {!loading && <>
      <section className="knowledge-summary" aria-label="Knowledge facts summary">
        <div><span>{t('JOBS')}</span><strong>{facts.counts?.jobs ?? facts.facts.jobs.length}</strong></div>
        <div><span>{t('MACHINES')}</span><strong>{facts.counts?.machines ?? facts.facts.machines.length}</strong></div>
        <div><span>{t('OPERATIONS')}</span><strong>{facts.counts?.operations ?? facts.facts.operations.length}</strong></div>
        <div><span>{t('COMPATIBLE PAIRS')}</span><strong>{facts.counts?.compatible_pairs ?? facts.facts.compatible.length}</strong></div>
        <div><span>{t('PRECEDENCE LINKS')}</span><strong>{facts.counts?.precedence_links ?? facts.facts.precedes.length}</strong></div>
      </section>
      {!facts.facts.jobs.length && <div className="alert alert-warning" role="status">No manufacturing facts are present yet. Add jobs, machines and operations, or explicitly load the removable automotive learning example.</div>}

      <section className="knowledge-panel">
        <div className="section-title-row"><div><div className="eyebrow">{t('GROUND FACTS')}</div><h2>{t('Predicate-based manufacturing state')}</h2></div><span className="tag tag-blue">{facts.predicates.join(' · ') || 'Compatible · Precedes · Available · Finished'}</span></div>
        <div className="predicate-definitions">{Object.entries(facts.predicate_definitions || {}).map(([predicate, definition]) => <div key={predicate}><code>{predicate}</code><span>{definition}</span></div>)}</div>
        <div className="knowledge-fact-grid">
          {entries.map(([name, values]) => <section className="knowledge-fact-card" key={name}><div className="knowledge-fact-heading"><h3>{name.replaceAll('_', ' ')}</h3><span>{Array.isArray(values) ? values.length : 0}</span></div>
            {!Array.isArray(values) || values.length === 0 ? <p className="mini-empty">No {name.replaceAll('_', ' ')} facts are currently derived.</p> : <div className="knowledge-table-scroll"><table className="knowledge-table"><thead><tr>{Object.keys(values[0] as object).map(key => <th key={key}>{key.replaceAll('_', ' ')}</th>)}</tr></thead><tbody>{(values as Record<string, unknown>[]).map((row, index) => <tr key={`${name}-${index}`}>{Object.values(row).map((value, column) => <td key={column}>{Array.isArray(value) ? value.join(', ') || '—' : typeof value === 'boolean' ? value ? 'Yes' : 'No' : String(value ?? '—')}</td>)}</tr>)}</tbody></table></div>}
          </section>)}
        </div>
      </section>

      <section className="knowledge-panel planning-actions-panel">
        <div className="section-title-row"><div><div className="eyebrow">{t('CLASSICAL PLANNING')}</div><h2>{t('Currently applicable actions')}</h2></div><span className={`feasible-pill ${model?.valid ? 'yes' : 'no'}`}>{model?.valid ? t('Model valid') : t('Input needed')}</span></div>
        <p className="knowledge-explainer">A <strong>Perform operation on machine</strong> action is offered only when its predecessor is complete, that machine is compatible and a valid time window is available. Effects record the finish, machine occupancy and job-route progress.</p>
        {model?.validation_errors?.map(message => <p className="field-error" key={message}>{message}</p>)}
        {!model?.actions?.length && !model?.validation_errors?.length && <p className="mini-empty">No action is currently applicable. Check machine capabilities, calendars and route prerequisites.</p>}
        <div className="planning-action-list">{model?.actions?.map(action => <article className="planning-action" key={`${action.operation_id}-${action.machine_id}`}>
          <div className="planning-action-title"><Network size={16}/><div><strong>{action.name}</strong><small>{action.operation_id} · {action.machine_id} · minute {action.start_minute.toFixed(2)}–{action.end_minute.toFixed(2)}</small></div></div>
          <div className="planning-preconditions"><div><strong>Preconditions</strong>{action.preconditions.map(item => <code key={item}>{item}</code>)}</div><div><strong>Effects</strong>{action.effects.map(item => <code key={item}>{item}</code>)}</div></div>
        </article>)}</div>
      </section>

      <section className="knowledge-panel">
        <div className="section-title-row"><div><div className="eyebrow">{t('AUTOMOTIVE ROUTE EXAMPLES')}</div><h2>{t('Editable learning templates')}</h2></div>{workflows?.is_simulated_learning_example && <span className="tag tag-sample">{t('SIMULATED EXAMPLES')}</span>}</div>
        <p className="knowledge-explainer">{workflows?.notice || 'Educational examples only; not certified process plans or real-company specifications.'}</p>
        <div className="workflow-template-list">{Object.entries(workflows?.workflows || {}).map(([key, workflow]) => <article key={key}><div><strong>{workflow.label}</strong><small>{componentName(key)}</small></div><ol>{workflow.steps.map(step => <li key={step.sequence}><span>{step.sequence}</span><strong>{step.name}</strong><code>{step.required_capability}</code><small>{step.suggested_minutes} min example</small></li>)}</ol></article>)}</div>
      </section>

      <section className="knowledge-syllabus">
        <div className="section-title-row"><div><div className="eyebrow">{t('AI SYLLABUS MAPPING')}</div><h2>{t('Search strategy → course concept')}</h2></div><BookOpen size={19}/></div>
        <div className="syllabus-grid">
          <p><code>A* Search</code><span><strong>f(n) = g(n) + h(n)</strong> — accumulated configured scheduling cost plus a documented remaining-work lower bound. Optimality is shown only when the complete A* search proves it.</span></p>
          <p><code>Uniform Cost Search</code><span>Expands the frontier with the lowest accumulated path cost <strong>g(n)</strong>.</span></p>
          <p><code>Greedy Best-First</code><span>Ranks states by the remaining-work heuristic estimate <strong>h(n)</strong>; it does not claim optimality.</span></p>
          <p><code>Breadth-First / Depth-First</code><span>Uninformed teaching demonstrations ordered by planning depth; no A* or UCS guarantees.</span></p>
          <p><ShieldCheck size={15}/><span>Search successors are generated from the preconditions/effects shown above. Completed schedules are checked against the knowledge rules before they are marked feasible.</span></p>
          <p><Database size={15}/><span>Counts, facts and actions are fetched from saved manufacturing inputs; this page does not invent or auto-seed a factory dataset.</span></p>
        </div>
      </section>
    </>}
  </div>;
}
