import React, { useState } from 'react';
import { Compass, Search, Eye, Filter } from 'lucide-react';

export default function SymbolCatalogView({ nodes, onSelectSymbol }) {
  const [query, setQuery] = useState('');
  const [selectedType, setSelectedType] = useState('all');

  const types = ['all', 'class', 'function', 'method', 'component'];

  const filtered = (nodes || []).filter((n) => {
    if (selectedType !== 'all') {
      if (selectedType === 'class' && n.type !== 'class') return false;
      if (selectedType === 'component' && n.type !== 'component') return false;
      if (selectedType === 'function' && n.type !== 'function') return false;
      if (selectedType === 'method' && n.type !== 'method') return false;
    }
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      n.name.toLowerCase().includes(q) ||
      n.file.toLowerCase().includes(q) ||
      (n.docstring || '').toLowerCase().includes(q)
    );
  });

  return (
    <div style={{ padding: '1.5rem', height: '100%', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Compass size={18} color="#a855f7" />
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
            Symbol Catalog ({filtered.length})
          </h2>
        </div>

        {/* Filter pills & search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: '0.35rem', background: 'rgba(15, 23, 42, 0.6)', padding: '0.2rem', borderRadius: '6px', border: '1px solid rgba(51, 65, 85, 0.4)' }}>
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setSelectedType(t)}
                style={{
                  padding: '0.25rem 0.6rem',
                  borderRadius: '4px',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: '0.75rem',
                  textTransform: 'capitalize',
                  fontWeight: selectedType === t ? 600 : 500,
                  color: selectedType === t ? '#f8fafc' : '#94a3b8',
                  background: selectedType === t ? 'rgba(56, 189, 248, 0.2)' : 'transparent',
                }}
              >
                {t}
              </button>
            ))}
          </div>

          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={14} style={{ position: 'absolute', left: '0.6rem', color: '#64748b' }} />
            <input
              type="text"
              placeholder="Search symbols..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{
                padding: '0.45rem 0.75rem 0.45rem 2.2rem',
                borderRadius: '6px',
                border: '1px solid rgba(51, 65, 85, 0.6)',
                background: 'rgba(15, 23, 42, 0.8)',
                color: '#f8fafc',
                fontSize: '0.82rem',
                width: '240px',
                outline: 'none',
              }}
            />
          </div>
        </div>
      </div>

      {/* Catalog Table */}
      <div className="glass-panel" style={{ borderRadius: '8px', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.82rem' }}>
          <thead>
            <tr style={{ background: 'rgba(30, 41, 59, 0.6)', borderBottom: '1px solid var(--border-color)', color: '#94a3b8' }}>
              <th style={{ padding: '0.75rem 1rem', width: '3rem' }}>#</th>
              <th style={{ padding: '0.75rem 1rem' }}>Symbol Name</th>
              <th style={{ padding: '0.75rem 1rem', width: '6rem' }}>Type</th>
              <th style={{ padding: '0.75rem 1rem' }}>File Location</th>
              <th style={{ padding: '0.75rem 1rem', width: '5rem' }}>Degree</th>
              <th style={{ padding: '0.75rem 1rem' }}>Docstring</th>
              <th style={{ padding: '0.75rem 1rem', width: '6rem', textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 150).map((n, idx) => (
              <tr
                key={n.id || idx}
                style={{
                  borderBottom: '1px solid rgba(51, 65, 85, 0.3)',
                  transition: 'background 0.15s ease',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(56, 189, 248, 0.05)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <td style={{ padding: '0.65rem 1rem', color: '#64748b' }}>{idx + 1}</td>
                <td style={{ padding: '0.65rem 1rem', fontFamily: 'JetBrains Mono', fontWeight: 600, color: '#f8fafc' }}>
                  {n.name}
                </td>
                <td style={{ padding: '0.65rem 1rem' }}>
                  <span className={`badge ${
                    n.is_route ? 'badge-route' :
                    n.is_dead ? 'badge-dead' :
                    n.type === 'class' ? 'badge-class' :
                    n.type === 'component' ? 'badge-comp' : 'badge-func'
                  }`}>
                    {n.type}
                  </span>
                </td>
                <td style={{ padding: '0.65rem 1rem', color: '#94a3b8' }}>
                  {n.file}:{n.line}
                </td>
                <td style={{ padding: '0.65rem 1rem', color: '#cbd5e1' }}>
                  {n.degree || 0}
                </td>
                <td style={{ padding: '0.65rem 1rem', color: '#94a3b8', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {n.docstring || '—'}
                </td>
                <td style={{ padding: '0.65rem 1rem', textAlign: 'center' }}>
                  <button
                    onClick={() => onSelectSymbol(n)}
                    style={{
                      background: 'rgba(56, 189, 248, 0.15)',
                      border: '1px solid rgba(56, 189, 248, 0.3)',
                      color: '#38bdf8',
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
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
