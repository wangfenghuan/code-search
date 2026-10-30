import React, { useMemo } from 'react';
import { X, ArrowUpRight, ArrowDownRight, Compass, ShieldAlert, Route as RouteIcon, FileCode } from 'lucide-react';
import SourceViewer from './SourceViewer';

export default function SymbolDrawer({ symbol, onClose, onSelectSymbol, allEdges, allNodes }) {
  if (!symbol) return null;

  // Compute callers and callees from allEdges
  const { callers, callees } = useMemo(() => {
    if (!symbol || !allEdges) return { callers: [], callees: [] };
    const myId = symbol.id;
    const callerList = [];
    const calleeList = [];

    const nodeMap = new Map();
    allNodes?.forEach((n) => nodeMap.set(n.id, n));

    allEdges.forEach((edge) => {
      if (edge.target === myId) {
        const callerNode = nodeMap.get(edge.source);
        callerList.push({
          id: edge.source,
          name: edge.caller,
          type: edge.type,
          node: callerNode,
        });
      }
      if (edge.source === myId) {
        const calleeNode = nodeMap.get(edge.target);
        calleeList.push({
          id: edge.target,
          name: edge.callee,
          type: edge.type,
          node: calleeNode,
        });
      }
    });

    return { callers: callerList, callees: calleeList };
  }, [symbol, allEdges, allNodes]);

  return (
    <aside
      className="glass-panel-elevated"
      style={{
        position: 'absolute',
        top: '3.75rem',
        right: '1rem',
        bottom: '1rem',
        width: '420px',
        maxWidth: 'calc(100vw - 2rem)',
        borderRadius: '12px',
        zIndex: 40,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        animation: 'fadeInRight 0.2s ease-out',
      }}
    >
      {/* Drawer Header */}
      <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
            <span className={`badge ${
              symbol.is_route ? 'badge-route' :
              symbol.is_dead ? 'badge-dead' :
              symbol.type === 'class' ? 'badge-class' :
              symbol.type === 'component' ? 'badge-comp' : 'badge-func'
            }`}>
              {symbol.type}
            </span>

            {symbol.is_route && (
              <span className="badge badge-route">
                <RouteIcon size={11} /> API Route
              </span>
            )}

            {symbol.is_dead && (
              <span className="badge badge-dead">
                <ShieldAlert size={11} /> Dead Code
              </span>
            )}
          </div>

          <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc', wordBreak: 'break-all' }}>
            {symbol.name}
          </h2>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: '#94a3b8', fontSize: '0.75rem' }}>
            <FileCode size={13} color="#38bdf8" />
            <span>{symbol.file}:{symbol.line}</span>
          </div>
        </div>

        <button
          onClick={onClose}
          style={{
            background: 'rgba(51, 65, 85, 0.4)',
            border: 'none',
            color: '#94a3b8',
            cursor: 'pointer',
            padding: '0.35rem',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Drawer Content */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', padding: '1rem' }}>
        {/* Route info if applicable */}
        {symbol.route && (
          <div style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.25)', borderRadius: '8px', padding: '0.6rem 0.8rem' }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 600, color: '#34d399', textTransform: 'uppercase', marginBottom: '0.2rem' }}>Exposed API Route</div>
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: '0.85rem', color: '#f8fafc', fontWeight: 600 }}>{symbol.route}</div>
          </div>
        )}

        {/* Docstring */}
        {symbol.docstring && (
          <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '0.6rem 0.8rem' }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '0.2rem' }}>Docstring / Description</div>
            <div style={{ fontSize: '0.8rem', color: '#cbd5e1', lineHeight: 1.4, whiteSpace: 'pre-wrap' }}>{symbol.docstring}</div>
          </div>
        )}

        {/* Callers & Callees */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
          {/* Callers */}
          <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '0.6rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.72rem', fontWeight: 600, color: '#38bdf8' }}>
              <ArrowDownRight size={13} />
              <span>Callers ({callers.length})</span>
            </div>
            {callers.length === 0 ? (
              <span style={{ fontSize: '0.72rem', color: '#64748b', fontStyle: 'italic' }}>No incoming callers</span>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', maxHeight: '120px', overflowY: 'auto' }}>
                {callers.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => c.node && onSelectSymbol(c.node)}
                    style={{
                      textAlign: 'left',
                      background: 'rgba(30, 41, 59, 0.6)',
                      border: '1px solid rgba(51, 65, 85, 0.3)',
                      color: '#cbd5e1',
                      borderRadius: '4px',
                      padding: '0.25rem 0.4rem',
                      fontSize: '0.75rem',
                      cursor: c.node ? 'pointer' : 'default',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {c.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Callees */}
          <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '0.6rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.72rem', fontWeight: 600, color: '#a855f7' }}>
              <ArrowUpRight size={13} />
              <span>Callees ({callees.length})</span>
            </div>
            {callees.length === 0 ? (
              <span style={{ fontSize: '0.72rem', color: '#64748b', fontStyle: 'italic' }}>No downstream calls</span>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', maxHeight: '120px', overflowY: 'auto' }}>
                {callees.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => c.node && onSelectSymbol(c.node)}
                    style={{
                      textAlign: 'left',
                      background: 'rgba(30, 41, 59, 0.6)',
                      border: '1px solid rgba(51, 65, 85, 0.3)',
                      color: '#cbd5e1',
                      borderRadius: '4px',
                      padding: '0.25rem 0.4rem',
                      fontSize: '0.75rem',
                      cursor: c.node ? 'pointer' : 'default',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {c.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Source Code Slice */}
        <div style={{ flex: 1, minHeight: '220px', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
          <SourceViewer file={symbol.file} startLine={symbol.line} endLine={symbol.end_line} />
        </div>
      </div>
    </aside>
  );
}
