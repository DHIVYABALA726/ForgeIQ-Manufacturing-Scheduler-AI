import { Activity, BarChart3, BookOpen, Factory, FileText, Gauge, RefreshCw, Settings2, Brain, GitBranch, Bot, ShieldAlert, Search } from 'lucide-react';
import type { Section } from '../types';
import { useLocale } from '../i18n';

const items: { id: Section; label: string; icon: typeof Activity }[] = [
  { id: 'workspace', label: 'Workspace', icon: Gauge },
  { id: 'data', label: 'Manufacturing data', icon: Factory },
  { id: 'scheduling', label: 'Scheduling', icon: Settings2 },
  { id: 'knowledge', label: 'Knowledge & planning', icon: BookOpen },
  { id: 'rescheduling', label: 'Dynamic rescheduling', icon: RefreshCw },
  { id: 'gantt', label: 'Gantt chart', icon: Activity },
  { id: 'comparison', label: 'Algorithm comparison', icon: BarChart3 },
  { id: 'report', label: 'Scheduling report', icon: FileText },
  { id: 'ai-center', label: 'AI Intelligence Center', icon: Brain },
  { id: 'ai-search', label: 'AI Search Lab', icon: Search },
  { id: 'ai-tree', label: 'State-Space Tree Explorer', icon: GitBranch },
  { id: 'intelligence', label: 'Scheduling Intelligence', icon: BarChart3 },
  { id: 'agents', label: 'Intelligent Agents', icon: Bot },
  { id: 'risk', label: 'Bayesian Risk Analysis', icon: ShieldAlert },
];

export default function Sidebar({ active, onNavigate, scheduleAvailable }: { active: Section; onNavigate: (section: Section) => void; scheduleAvailable: boolean }) {
  const { language, setLanguage, t } = useLocale();
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M6 8h9v7h11v9h-9v-7H6z" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round"/><path d="M6 8h6m14 16h-6" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round"/></svg></div><div><strong>Forge<span>IQ</span></strong><small>{t('Production scheduler')}</small></div></div>
    <div className="nav-label">{t('WORKSPACE')}</div>
    <nav aria-label="Main navigation">{items.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${active === id ? 'active' : ''}`} onClick={() => onNavigate(id)} aria-current={active === id ? 'page' : undefined}>
      <Icon size={17} strokeWidth={1.9} /><span>{t(label)}</span>{id !== 'workspace' && !scheduleAvailable && ['gantt', 'comparison', 'report'].includes(id) && <span className="nav-dot" aria-label="No schedule yet" />}
    </button>)}</nav>
    <div className="sidebar-foot"><div className="language-switch" role="group" aria-label="Language / மொழி"><button className={language === 'en' ? 'selected' : ''} aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>EN</button><button className={language === 'ta' ? 'selected' : ''} aria-pressed={language === 'ta'} onClick={() => setLanguage('ta')}>தமிழ்</button></div><div className="status-pulse" /><span>{t('Scheduling engine ready')}</span><small>Deterministic · Constraint-aware</small></div>
  </aside>;
}
