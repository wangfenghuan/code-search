import React, { useState } from 'react';
import { Route as RouteIcon, Search, Globe, Eye } from 'lucide-react';

export default function RoutesView({ nodes, onSelectSymbol }) {
  const [query, setQuery] = useState('');

  const routeNodes = (nodes || []).filter((n) => n.is_route);

  const filtered = routeNodes.filter((n) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      n.name.toLowerCase().includes(q) ||
      (n.route || '').toLowerCase().includes(q) ||
      n.file.toLowerCase().includes(q)
    );
  });

  return (
    <div style={{ padding: '1.5rem', height: '100%', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <RouteIcon size={18} color="#10b981" />
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
            Discovered HTTP API Routes ({filtered.length})
          </h2>
        </div>

        <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <Search size={14} style={{ position: 'absolute', left: '0.6rem', color: '#64748b' }} />
          <input
            type="text"
            placeholder="Filter endpoints or paths..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{
              padding: '0.45rem 0.75rem 0.45rem 2.2rem',
              borderRadius: '6px',
              border: '1px solid rgba(51, 65, 85, 0.6)',
              background: 'rgba(15, 23, 42, 0.8)',
              color: '#f8fafc',
              fontSize: '0.82rem',
              width: '260px',
              outline: 'none',
            }}
          />
        </div>
      </div>

      {/* Routes Grid / Table */}
      <div className="glass-panel" style={{ borderRadius: '8px', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.82rem' }}>
          <thead>
            <tr style={{ background: 'rgba(30, 41, 59, 0.6)', borderBottom: '1px solid var(--border-color)', color: '#94a3b8' }}>
              <th style={{ padding: '0.75rem 1rem', width: '3rem' }}>#</th>
              <th style={{ padding: '0.75rem 1rem' }}>Route Path</th>
              <th style={{ padding: '0.75rem 1rem' }}>Handler Function</th>
              <th style={{ padding: '0.75rem 1rem' }}>File & Location</th>
              <th style={{ padding: '0.75rem 1rem', width: '6rem', textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="5" style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                  No HTTP routes found in this codebase
                </td>
              </tr>
            ) : (
              filtered.map((r, idx) => {
                const method = (r.route || '').split(' ')[0] || 'API';
                const pathStr = (r.route || '').replace(method, '').trim() || r.route;

                return (
                  <tr
                    key={idx}
                    style={{
                      borderBottom: '1px solid rgba(51, 65, 85, 0.3)',
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(16, 185, 129, 0.05)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td style={{ padding: '0.65rem 1rem', color: '#64748b' }}>{idx + 1}</td>
                    <td style={{ padding: '0.65rem 1rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="badge badge-route font-mono">{method}</span>
                        <span style={{ fontFamily: 'JetBrains Mono', fontWeight: 600, color: '#f8fafc' }}>
                          {pathStr}
                        </span>
                      </div>
                    </td>
                    <td style={{ padding: '0.65rem 1rem', fontFamily: 'JetBrains Mono', color: '#38bdf8' }}>
                      {r.name}
                    </td>
                    <td style={{ padding: '0.65rem 1rem', color: '#94a3b8' }}>
                      {r.file}:{r.line}
                    </td>
                    <td style={{ padding: '0.65rem 1rem', textAlign: 'center' }}>
                      <button
                        onClick={() => onSelectSymbol(r)}
                        style={{
                          background: 'rgba(16, 185, 129, 0.15)',
                          border: '1px solid rgba(16, 185, 129, 0.3)',
                          color: '#34d399',
                          padding: '0.25rem 0.6rem',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.25rem',
                        }}
                      >
                        <Eye size={12} /> Inspect
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
