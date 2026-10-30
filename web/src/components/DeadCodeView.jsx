import React, { useState } from 'react';
import { Skull, Search, AlertTriangle, Eye, ArrowUpRight } from 'lucide-react';

export default function DeadCodeView({ deadCodeList, onSelectSymbol, nodes }) {
  const [query, setQuery] = useState('');

  const nodeMap = new Map();
  nodes?.forEach((n) => nodeMap.set(n.name, n));

  const filtered = (deadCodeList || []).filter((item) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      item.symbol.toLowerCase().includes(q) ||
      item.file_path.toLowerCase().includes(q) ||
      (item.docstring || '').toLowerCase().includes(q)
    );
  });

  return (
    <div style={{ padding: '1.5rem', height: '100%', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Warning banner */}
      <div style={{ background: 'rgba(244, 63, 94, 0.1)', border: '1px solid rgba(244, 63, 94, 0.25)', borderRadius: '8px', padding: '0.85rem 1rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <AlertTriangle size={18} color="#f43f5e" style={{ flexShrink: 0 }} />
        <div style={{ fontSize: '0.82rem', color: '#fda4af', lineHeight: 1.5 }}>
          <strong>Dead Code Notice:</strong> These {deadCodeList?.length || 0} functions and methods have zero incoming call edges within the repository. Verify each candidate before deleting, as public APIs or dynamic reflection calls may not have in-repo call edges.
        </div>
      </div>

      {/* Search Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Skull size={18} color="#f43f5e" />
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
            Dead Code Candidates ({filtered.length})
          </h2>
        </div>

        <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <Search size={14} style={{ position: 'absolute', left: '0.6rem', color: '#64748b' }} />
          <input
            type="text"
            placeholder="Filter dead functions..."
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

      {/* Table */}
      <div className="glass-panel" style={{ borderRadius: '8px', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.82rem' }}>
          <thead>
            <tr style={{ background: 'rgba(30, 41, 59, 0.6)', borderBottom: '1px solid var(--border-color)', color: '#94a3b8' }}>
              <th style={{ padding: '0.75rem 1rem', width: '3rem' }}>#</th>
              <th style={{ padding: '0.75rem 1rem' }}>Symbol Name</th>
              <th style={{ padding: '0.75rem 1rem', width: '6rem' }}>Type</th>
              <th style={{ padding: '0.75rem 1rem' }}>File & Location</th>
              <th style={{ padding: '0.75rem 1rem', width: '5rem' }}>Lines</th>
              <th style={{ padding: '0.75rem 1rem' }}>Docstring / Summary</th>
              <th style={{ padding: '0.75rem 1rem', width: '6rem', textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item, idx) => {
              const matchedNode = nodeMap.get(item.symbol) || {
                id: item.id,
                name: item.symbol,
                type: item.type,
                file: item.file_path,
                line: item.start_line,
                end_line: item.end_line,
                docstring: item.docstring,
                is_dead: true,
              };

              return (
                <tr
                  key={idx}
                  style={{
                    borderBottom: '1px solid rgba(51, 65, 85, 0.3)',
                    transition: 'background 0.15s ease',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(56, 189, 248, 0.05)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={{ padding: '0.65rem 1rem', color: '#64748b' }}>{idx + 1}</td>
                  <td style={{ padding: '0.65rem 1rem', fontFamily: 'JetBrains Mono', fontWeight: 600, color: '#fb7185' }}>
                    {item.symbol}
                  </td>
                  <td style={{ padding: '0.65rem 1rem' }}>
                    <span className="badge badge-dead">{item.type}</span>
                  </td>
                  <td style={{ padding: '0.65rem 1rem', color: '#94a3b8' }}>
                    {item.file_path}:{item.start_line}
                  </td>
                  <td style={{ padding: '0.65rem 1rem', color: '#cbd5e1' }}>
                    {item.lines_count} lines
                  </td>
                  <td style={{ padding: '0.65rem 1rem', color: '#94a3b8', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.docstring ? item.docstring.replace(/\n/g, ' ') : '—'}
                  </td>
                  <td style={{ padding: '0.65rem 1rem', textAlign: 'center' }}>
                    <button
                      onClick={() => onSelectSymbol(matchedNode)}
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
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
