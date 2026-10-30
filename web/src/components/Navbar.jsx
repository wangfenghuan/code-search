import React from 'react';
import { Network, Skull, Route, Compass, RefreshCw, FolderGit2 } from 'lucide-react';

export default function Navbar({ activeTab, setActiveTab, stats, repoName, repoPath, onRefresh, loading }) {
  const tabs = [
    { id: 'map', label: 'Code Map', icon: Network, count: stats?.total_nodes },
    { id: 'deadcode', label: 'Dead Code', icon: Skull, count: stats?.dead_code_count, highlight: stats?.dead_code_count > 0 },
    { id: 'routes', label: 'API Routes', icon: Route, count: stats?.routes_count },
    { id: 'symbols', label: 'Symbols', icon: Compass, count: stats?.total_nodes },
  ];

  return (
    <header className="glass-panel" style={{ padding: '0.75rem 1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', zIndex: 30, borderBottom: '1px solid var(--border-color)' }}>
      {/* Brand & Repo Info */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '1.25rem', lineHeight: 1 }}>⚡</span>
          <div>
            <h1 style={{ fontSize: '0.95rem', fontWeight: 700, letterSpacing: '-0.02em', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              code-search-graph
              <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)', fontWeight: 600 }}>REACT UI</span>
            </h1>
          </div>
        </div>

        <div style={{ height: '1.2rem', width: '1px', background: 'rgba(51, 65, 85, 0.5)' }}></div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: '#94a3b8', fontSize: '0.8rem' }}>
          <FolderGit2 size={14} color="#38bdf8" />
          <span style={{ fontWeight: 600, color: '#e2e8f0' }}>{repoName || 'Workspace'}</span>
          <span style={{ color: '#64748b', fontSize: '0.75rem' }}>({repoPath || '.'})</span>
        </div>
      </div>

      {/* Tabs */}
      <nav style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', background: 'rgba(15, 23, 42, 0.6)', padding: '0.25rem', borderRadius: '8px', border: '1px solid rgba(51, 65, 85, 0.4)' }}>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.4rem 0.75rem',
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer',
                fontSize: '0.82rem',
                fontWeight: isActive ? 600 : 500,
                color: isActive ? '#f8fafc' : '#94a3b8',
                background: isActive ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                outline: isActive ? '1px solid rgba(56, 189, 248, 0.4)' : 'none',
                transition: 'all 0.15s ease',
              }}
            >
              <Icon size={14} color={isActive ? '#38bdf8' : (tab.highlight ? '#f43f5e' : '#94a3b8')} />
              <span>{tab.label}</span>
              {typeof tab.count === 'number' && (
                <span
                  style={{
                    fontSize: '0.7rem',
                    padding: '0.05rem 0.35rem',
                    borderRadius: '9999px',
                    background: tab.highlight && tab.count > 0 ? 'rgba(244, 63, 94, 0.2)' : 'rgba(51, 65, 85, 0.4)',
                    color: tab.highlight && tab.count > 0 ? '#fb7185' : '#94a3b8',
                    fontWeight: 600,
                  }}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Stats Summary & Refresh */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.75rem' }}>
          <span className="badge badge-func">{stats?.total_files || 0} Files</span>
          <span className="badge badge-class">{stats?.total_nodes || 0} Nodes</span>
          <span className="badge badge-route">{stats?.total_edges || 0} Calls</span>
        </div>

        <button
          onClick={onRefresh}
          disabled={loading}
          title="Refresh Graph Data"
          style={{
            background: 'rgba(30, 41, 59, 0.6)',
            border: '1px solid rgba(51, 65, 85, 0.5)',
            color: '#94a3b8',
            cursor: 'pointer',
            padding: '0.4rem 0.5rem',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
    </header>
  );
}
