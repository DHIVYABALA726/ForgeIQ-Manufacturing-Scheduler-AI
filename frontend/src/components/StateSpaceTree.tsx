import { useEffect, useMemo, useState } from 'react';
import type { AITrace } from '../services/api';

export default function StateSpaceTree({ trace }: { trace: AITrace | null }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const [playing, setPlaying] = useState(false);
  const nodes = trace?.nodes ?? [];
  const positions = useMemo(() => {
    const byDepth = new Map<number, number>();
    return nodes.map(node => {
      const slot = byDepth.get(node.depth) ?? 0; byDepth.set(node.depth, slot + 1);
      return { node, x: 48 + slot * 132, y: 38 + node.depth * 84 };
    });
  }, [nodes]);
  const pos = new Map(positions.map(p => [p.node.id, p]));
  const active = positions.find(p => p.node.id === selected)?.node ?? nodes[0] ?? null;
  useEffect(() => { if (!playing || !nodes.length) return; const timer = window.setInterval(() => setSelected(old => { const i = nodes.findIndex(n => n.id === old); if (i >= nodes.length - 1) { setPlaying(false); return nodes[0]?.id ?? null; } return nodes[i + 1].id; }), 650); return () => window.clearInterval(timer); }, [playing, nodes]);
  if (!trace) return <section className="ai-card"><h3>State-space trace</h3><p>Run a search experiment to inspect real generated states.</p></section>;
  return <section className="ai-card"><div className="ai-card-heading"><div><h3>State-space trace · {trace.algorithm}</h3><p>Captured from the actual search; selecting a node never reruns it.</p></div><div className="ai-tools"><button onClick={() => setZoom(v => Math.max(.5, v - .15))} aria-label="Zoom out">−</button><button onClick={() => setZoom(v => Math.min(2, v + .15))} aria-label="Zoom in">+</button><button onClick={() => { setPlaying(v => !v); if (!playing) setSelected(nodes[0]?.id ?? null); }}>{playing ? 'Pause' : 'Play'}</button></div></div>
    {trace.truncated && <p className="ai-warning" role="status">Trace truncated at {nodes.length} displayed nodes; search execution remained bounded.</p>}
    <div className="ai-tree-scroll"><svg className="ai-tree" width={Math.max(520, (Math.max(...positions.map(p => p.x), 500) + 100) * zoom)} height={Math.max(240, (Math.max(...positions.map(p => p.y), 180) + 60) * zoom)} viewBox={`0 0 ${Math.max(520, Math.max(...positions.map(p => p.x), 500) + 100)} ${Math.max(240, Math.max(...positions.map(p => p.y), 180) + 60)}`}>
      {trace.edges.map((edge,i) => { const a=pos.get(edge.source), b=pos.get(edge.target); return a&&b?<line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="ai-edge"/>:null; })}
      {positions.map(({node,x,y}) => <g key={node.id} role="button" tabIndex={0} aria-label={`${node.event} node ${node.id}`} onClick={() => setSelected(node.id)} onKeyDown={e => e.key === 'Enter' && setSelected(node.id)} className={`ai-node ai-node-${node.event} ${selected===node.id?'selected':''}`}><circle cx={x} cy={y} r="17"/><text x={x} y={y+4} textAnchor="middle">{node.id}</text><text x={x} y={y+31} textAnchor="middle" className="ai-node-label">{node.event}</text></g>)}
    </svg></div>
    <div className="ai-legend"><span>Root</span><span>Generated</span><span>Expanded</span><span>Duplicate / infeasible</span><span>Goal</span></div>
    {active && <div className="ai-node-detail"><strong>Node {active.id} · {active.event}</strong><div>Depth {active.depth} · g(n) {active.g ?? '—'} · h(n) {active.h ?? '—'} · f(n) {active.f ?? '—'}</div>{active.action && <p>Action: {active.action.operation_id} → {active.action.machine_id} ({active.action.start_minute}–{active.action.end_minute} min)</p>}{active.reason && <p>{active.reason}</p>}<small>{active.placements.length} placements in captured state</small></div>}
  </section>;
}
