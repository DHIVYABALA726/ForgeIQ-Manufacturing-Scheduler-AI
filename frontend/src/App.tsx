import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import { loadAutomotiveSample, loadCollections, loadSample, removeSample } from './services/api';
import { reconcileScheduleRuns } from './services/run-history';
import type { ApiCollections, ScheduleRun, Section } from './types';
import { getSchedule } from './services/api';

const Workspace = lazy(() => import('./pages/Workspace'));
const Scheduling = lazy(() => import('./pages/Scheduling'));
const ManufacturingData = lazy(() => import('./pages/ManufacturingData'));
const Results = lazy(() => import('./pages/Results'));
const Rescheduling = lazy(() => import('./pages/Rescheduling'));
const KnowledgePlanning = lazy(() => import('./pages/KnowledgePlanning'));
const AIIntelligenceCenter = lazy(() => import('./pages/AIIntelligenceCenter'));
const AISearchLab = lazy(() => import('./pages/AISearchLab'));
const StateSpaceExplorer = lazy(() => import('./pages/StateSpaceExplorer'));
const SchedulingIntelligence = lazy(() => import('./pages/SchedulingIntelligence'));
const IntelligentAgents = lazy(() => import('./pages/IntelligentAgents'));
const BayesianRisk = lazy(() => import('./pages/BayesianRisk'));

const empty: ApiCollections = { jobs: [], machines: [], operations: [], schedules: [] };

export default function App() {
  const [data, setData] = useState<ApiCollections>(empty);
  const [run, setRun] = useState<ScheduleRun | null>(null);
  const [section, setSection] = useState<Section>('workspace');
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [globalError, setGlobalError] = useState('');

  const reload = useCallback(async () => {
    try {
      const next = await loadCollections();
      setData(next); setOnline(true); setGlobalError('');
      if (next.schedules.length) {
        try { setRun(await getSchedule(next.schedules[0].id)); }
        catch { setRun(next.schedules[0]); }
      } else setRun(null);
    } catch (error) {
      setOnline(false); setGlobalError(error instanceof Error ? error.message : 'Could not load the manufacturing workspace.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const dataNav = () => setSection('data');
    const schedulingNav = () => setSection('scheduling');
    const refresh = () => { setLoading(true); void reload(); };
    window.addEventListener('forgeiq:navigate-data', dataNav);
    window.addEventListener('forgeiq:navigate-scheduling', schedulingNav);
    window.addEventListener('forgeiq:refresh', refresh);
    return () => { window.removeEventListener('forgeiq:navigate-data', dataNav); window.removeEventListener('forgeiq:navigate-scheduling', schedulingNav); window.removeEventListener('forgeiq:refresh', refresh); };
  }, [reload]);

  const handleSampleLoad = async () => {
    setNotice(''); setGlobalError('');
    try { const response = await loadSample(); setNotice(response.message); await reload(); }
    catch (error) { setGlobalError(error instanceof Error ? error.message : 'Sample dataset could not be loaded.'); }
  };
  const handleAutomotiveSampleLoad = async () => {
    setNotice(''); setGlobalError('');
    try { const response = await loadAutomotiveSample(); setNotice(response.message); await reload(); }
    catch (error) { setGlobalError(error instanceof Error ? error.message : 'The automotive learning example could not be loaded.'); }
  };
  const handleSampleRemove = async () => {
    if (!window.confirm('Remove only records labelled as sample data? Manually entered records will be kept.')) return;
    setNotice(''); setGlobalError('');
    try { const response = await removeSample(); setNotice(response.message); await reload(); }
    catch (error) { setGlobalError(error instanceof Error ? error.message : 'Sample dataset could not be removed.'); }
  };
  const onGenerated = (next: ScheduleRun) => { setRun(next); setData(current => ({ ...current, schedules: [next, ...current.schedules.filter(item => item.id !== next.id)] })); };
  const onRescheduled = (next: ScheduleRun) => {
    setRun(next);
    setData(current => ({
      jobs: next.input_snapshot?.jobs ?? current.jobs,
      machines: next.input_snapshot?.machines ?? current.machines,
      operations: next.input_snapshot?.operations ?? current.operations,
      schedules: reconcileScheduleRuns(current.schedules, next),
    }));
  };
  const onLoadSchedule = async (id: string) => { try { setRun(await getSchedule(id)); setGlobalError(''); } catch (error) { setGlobalError(error instanceof Error ? error.message : 'The saved schedule could not be loaded.'); } };
  const hasSchedule = Boolean(run || data.schedules.length);
  const staleCount = data.schedules.filter(item => item.is_stale).length;

  return <div className="app-shell">
    <Sidebar active={section} onNavigate={setSection} scheduleAvailable={hasSchedule}/>
    <main className="app-main">
      {notice && <div className="app-toast alert alert-success" role="status">{notice}<button className="toast-close" aria-label="Dismiss message" onClick={() => setNotice('')}>×</button></div>}
      {globalError && <div className="app-toast alert alert-error" role="alert"><span>{globalError}</span><button className="toast-close" aria-label="Dismiss error" onClick={() => setGlobalError('')}>×</button></div>}
      {loading && <div className="loading-screen"><span className="spinner"/> Loading manufacturing data…</div>}
      {!loading && section === 'workspace' && <Suspense fallback={<div className="loading-screen"><span className="spinner"/> Loading workspace…</div>}><Workspace data={data} online={online} staleCount={staleCount} onNavigate={setSection} onLoadSample={handleSampleLoad} onLoadAutomotiveSample={handleAutomotiveSampleLoad} onRemoveSample={handleSampleRemove} loading={loading}/></Suspense>}
      {!loading && section === 'data' && <Suspense fallback={<div className="loading-screen"><span className="spinner"/> Loading manufacturing records…</div>}><ManufacturingData data={data} online={online} onChanged={reload} onLoadSample={handleSampleLoad} onLoadAutomotiveSample={handleAutomotiveSampleLoad} onRemoveSample={handleSampleRemove}/></Suspense>}
      {!loading && section === 'scheduling' && <Suspense fallback={<div className="loading-screen"><span className="spinner"/> Loading scheduling controls…</div>}><Scheduling data={data} onGenerated={onGenerated} onNavigate={() => setSection('gantt')}/></Suspense>}
      {!loading && section === 'ai-center' && <Suspense fallback={<div className="loading-screen">Loading AI Intelligence Center…</div>}><AIIntelligenceCenter onNavigate={setSection}/></Suspense>}
      {!loading && section === 'ai-search' && <Suspense fallback={<div className="loading-screen">Loading search lab…</div>}><AISearchLab scheduleIds={data.schedules.map(item => item.id)}/></Suspense>}
      {!loading && section === 'ai-tree' && <Suspense fallback={<div className="loading-screen">Loading captured trace…</div>}><StateSpaceExplorer/></Suspense>}
      {!loading && section === 'intelligence' && <Suspense fallback={<div className="loading-screen">Loading scheduling intelligence…</div>}><SchedulingIntelligence/></Suspense>}
      {!loading && section === 'agents' && <Suspense fallback={<div className="loading-screen">Loading deterministic agents…</div>}><IntelligentAgents onNavigate={setSection}/></Suspense>}
      {!loading && section === 'risk' && <Suspense fallback={<div className="loading-screen">Loading risk analysis…</div>}><BayesianRisk/></Suspense>}
      {!loading && section === 'knowledge' && <Suspense fallback={<div className="loading-screen"><span className="spinner"/> Loading automotive knowledge…</div>}><KnowledgePlanning/></Suspense>}
      {!loading && section === 'rescheduling' && <Suspense fallback={<div className="loading-screen"><span className="spinner"/> Loading dynamic rescheduling…</div>}><Rescheduling run={run} allRuns={data.schedules} data={data} onRescheduled={onRescheduled} onLoadSchedule={onLoadSchedule} onNavigate={() => setSection('scheduling')}/></Suspense>}
      {!loading && ['gantt', 'comparison', 'report'].includes(section) && <Suspense fallback={<div className="loading-screen"><span className="spinner"/> Loading saved results…</div>}><Results key={run?.id || data.schedules[0]?.id || 'no-run'} run={run} allRuns={data.schedules} data={data} initialView={section as 'gantt' | 'comparison' | 'report'} onLoadSchedule={onLoadSchedule}/></Suspense>}
      <footer className="app-footer"><span>ForgeIQ</span><span>Actual schedules · Measured comparisons · Transparent recommendations</span><button onClick={() => void reload()} aria-label="Refresh data">Refresh data</button></footer>
    </main>
  </div>;
}
