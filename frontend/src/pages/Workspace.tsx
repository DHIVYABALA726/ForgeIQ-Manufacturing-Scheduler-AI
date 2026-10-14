import { ArrowRight, Clock3, Factory, Layers3, Plus, RefreshCw, Sparkles } from 'lucide-react';
import type { ApiCollections, Section } from '../types';
import { useLocale } from '../i18n';

const steps = [
  ['01', 'Set up machines', 'Define real availability and eligible equipment.'],
  ['02', 'Enter jobs & operations', 'Add release times, due dates and process order.'],
  ['03', 'Compare schedules', 'Measure feasible plans against your production objective.'],
];

export default function Workspace({ data, online, staleCount, onNavigate, onLoadSample, onLoadAutomotiveSample, onRemoveSample, loading }: {
  data: ApiCollections; online: boolean; staleCount: number; onNavigate: (section: Section) => void;
  onLoadSample: () => void; onLoadAutomotiveSample: () => void; onRemoveSample: () => void; loading: boolean;
}) {
  const { t } = useLocale();
  const latestRun = data.schedules[0];
  const hasFeasibleResult = latestRun?.results.some(result => result.feasible) ?? false;
  const operationCount = latestRun?.results.find(r => r.algorithm_name === (latestRun.selected_algorithm_name || latestRun.recommended_algorithm_name))?.scheduled_operations.length ?? 0;
  const manuallyEnteredJobs = data.jobs.filter(job => !job.is_sample).length;
  const status = !online ? 'Offline' : latestRun?.is_stale ? 'Outdated' : latestRun ? (hasFeasibleResult ? 'Scheduled' : 'No feasible schedule') : 'Not scheduled';
  const availableMachines = data.machines.filter(m => m.is_available).length;
  const hasSample = data.jobs.some(j => j.is_sample) || data.machines.some(m => m.is_sample) || data.operations.some(o => o.is_sample);
  const hasData = data.jobs.length + data.machines.length + data.operations.length > 0;
  return <div className="page-shell">
    <header className="page-heading"><div><div className="eyebrow">{t('MANUFACTURING CONTROL TOWER')}</div><h1>{t('Production workspace')}</h1><p className="page-subtitle">{t('Build feasible plans from the jobs, machines and constraints you enter.')}</p></div>
      <div className="top-actions">{hasSample && <button className="button button-outline" onClick={onRemoveSample} disabled={loading}>{t('Remove sample data')}</button>}<span className={`connection-pill ${online ? 'online' : 'offline'}`}><span />{t(online ? 'API connected' : 'API unavailable')}</span></div></header>
    {!online && <div className="alert alert-error" role="alert"><strong>Backend not connected.</strong> Start FastAPI and retry; existing database data cannot be loaded until the service is available.</div>}
    {staleCount > 0 && <div className="alert alert-warning" role="status"><strong>{staleCount} saved schedule{staleCount === 1 ? '' : 's'} outdated.</strong> Manufacturing inputs changed after these runs. Generate a new schedule to compare current data.</div>}
    <section className="stat-strip" aria-label="Workspace summary">
      <div className="stat-cell"><span>{t('MANUALLY ENTERED JOBS')}</span><strong>{manuallyEnteredJobs}</strong><small>{data.jobs.length - manuallyEnteredJobs} {t('labelled sample jobs')} · {data.jobs.length} {t('total')}</small></div>
      <div className="stat-cell"><span>{t('AVAILABLE MACHINES')}</span><strong>{availableMachines}</strong><small>{data.machines.length} {t('recorded total')}</small></div>
      <div className="stat-cell"><span>{t('SCHEDULED OPERATIONS')}</span><strong>{operationCount}</strong><small>{t('Latest selected / recommended result')}</small></div>
      <div className="stat-cell"><span>{t('CURRENT STATUS')}</span><strong className={`status-text ${hasData ? 'has-data' : ''}`} style={status === 'No feasible schedule' ? { color: '#b42318' } : undefined}>{t(status)}</strong><small>{data.schedules.length ? `${data.schedules.length} ${t('saved runs')}` : t('No current schedule')}</small></div>
    </section>
    {!hasData && !online ? <section className="empty-workspace"><div className="empty-icon"><Factory size={24} /></div><div className="eyebrow">WORKSPACE UNAVAILABLE</div><h2>Manufacturing data could not be loaded.</h2><p>Reconnect the FastAPI backend to see the saved workspace. ForgeIQ will not assume that the database is empty.</p><button className="button button-outline" onClick={() => window.dispatchEvent(new CustomEvent('forgeiq:refresh'))}><RefreshCw size={15}/> Retry connection</button></section> : !hasData ? <section className="empty-workspace">
      <div className="empty-icon"><Factory size={24} /></div><div className="eyebrow">{t('EMPTY WORKSPACE')}</div>
      <h2>{t('No manufacturing data available. Add jobs and machines to begin scheduling.')}</h2>
      <p>{t('ForgeIQ only schedules data you enter. Start with machine availability, then add jobs and their ordered operations.')}</p>
      <div className="empty-actions"><button className="button button-primary" onClick={() => onNavigate('data')} disabled={!online}><Plus size={16} /> {t('Enter manufacturing data')}</button><button className="button button-quiet" onClick={onLoadSample} disabled={!online || loading}><Sparkles size={15} /> {t('Load Sample Dataset')}</button><button className="button button-outline" onClick={onLoadAutomotiveSample} disabled={!online || loading}><Factory size={15}/> {t('Load automotive demo')}</button></div>
      <div className="sample-note">{t('Either dataset is deterministic, explicitly loaded, visibly labelled as sample, simulated and removable.')}</div>
    </section> : <section className="overview-content">
      <div className="section-title-row"><div><div className="eyebrow">{t('CURRENT DATASET')}</div><h2>{t('Ready for scheduling')}</h2></div><button className="button button-primary" onClick={() => onNavigate('scheduling')}><Layers3 size={16} /> {t('Configure a schedule')} <ArrowRight size={14} /></button></div>
      <div className="workflow-strip">{steps.map(([num, title, text]) => <div className="workflow-step" key={num}><span className="workflow-number">{num}</span><div><strong>{t(title)}</strong><p>{t(text)}</p></div></div>)}</div>
      <div className="quick-summary"><div className="quick-summary-icon"><Clock3 size={18} /></div><div><strong>Latest schedule run</strong><span>{data.schedules[0] ? new Date(data.schedules[0].created_at).toLocaleString() : 'No schedules yet'}</span></div>{data.schedules[0]?.is_stale && <span className="tag tag-amber">Outdated</span>}<button className="icon-button" aria-label="Open scheduling" onClick={() => onNavigate(data.schedules.length ? 'gantt' : 'scheduling')}><RefreshCw size={16} /></button></div>
    </section>}
  </div>;
}
