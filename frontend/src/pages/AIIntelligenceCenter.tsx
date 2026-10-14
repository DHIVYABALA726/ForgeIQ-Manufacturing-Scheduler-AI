import { useEffect, useState } from 'react';
import { getAIOverview } from '../services/api';

export default function AIIntelligenceCenter({ onNavigate }: { onNavigate:(section:any)=>void }) {
  const [data,setData]=useState<Record<string,any>|null>(null); const [error,setError]=useState('');
  useEffect(()=>{ getAIOverview().then(setData).catch(e=>setError(e.message)); },[]);
  const counts=data?.counts ?? {};
  return <div className="ai-page"><header className="ai-page-header"><div><span className="ai-eyebrow">FORGEIQ · INTELLIGENCE</span><h1>AI Intelligence Center</h1><p>Measured scheduling insights, bounded search traces and deterministic decision support.</p></div><span className="ai-badge">Deterministic · operator-controlled</span></header>
    {error&&<div className="ai-warning">{error}</div>}
    <div className="ai-stat-grid">{[['Jobs',counts.jobs??'—'],['Machines',counts.machines??'—'],['Operations',counts.operations??'—']].map(([name,value])=><article className="ai-stat" key={name}><small>{name}</small><strong>{value}</strong></article>)}</div>
    <div className="ai-grid"><article className="ai-card"><h2>Latest schedule evidence</h2>{data?.latest_schedule?<><p><strong>{data.latest_schedule.recommended_algorithm_name??'No recommendation'}</strong> · {data.latest_schedule.scenario} · objective {data.latest_schedule.objective}</p><p>{data.latest_schedule.result?.feasible?'A feasible schedule is available.':'No selected feasible schedule was recorded.'}</p></>:<p className="ai-muted">No saved schedule yet. Generate one from the Scheduling workspace to populate evidence.</p>}<button onClick={()=>onNavigate('intelligence')}>Compare scheduling methods</button></article>
    <article className="ai-card"><h2>Available analysis</h2><div className="ai-shortcuts"><button onClick={()=>onNavigate('ai-search')}>Run a search experiment</button><button onClick={()=>onNavigate('agents')}>Inspect deterministic agents</button><button onClick={()=>onNavigate('risk')}>Explore Bayesian risk</button></div></article></div>
    <article className="ai-card"><h2>Honest boundaries</h2><ul>{(data?.boundaries??['Search traces and agent activity are process-local and bounded.','Bayesian CPT assumptions are illustrative, not validated factory predictions.']).map((x:string)=><li key={x}>{x}</li>)}</ul>{data?.latest_reschedule_event&&<p>Latest saved disruption: {data.latest_reschedule_event.event_type} · {data.latest_reschedule_event.explanation}</p>}</article>
  </div>;
}
