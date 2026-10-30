import React, { useEffect, useRef, useState } from 'react';
import { Network } from 'vis-network';
import { Search, ZoomIn, ZoomOut, Maximize2, Pause, Play, Filter } from 'lucide-react';

export default function CodeMapView({ nodes, edges, onSelectSymbol, selectedSymbol }) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const [filterQuery, setFilterQuery] = useState('');
  const [filterType, setFilterType] = useState('all');
  const [physicsEnabled, setPhysicsEnabled] = useState(true);

  // Initialize and update vis network
  useEffect(() => {
    if (!containerRef.current || !nodes || nodes.length === 0) return;

    // Filter nodes
    const filteredNodes = nodes.filter((n) => {
      const matchQuery = !filterQuery ||
        n.name.toLowerCase().includes(filterQuery.toLowerCase()) ||
        n.file.toLowerCase().includes(filterQuery.toLowerCase());

      if (!matchQuery) return false;

      if (filterType === 'all') return true;
      if (filterType === 'route') return n.is_route;
      if (filterType === 'dead') return n.is_dead;
      if (filterType === 'class') return n.type === 'class';
      if (filterType === 'component') return n.type === 'component';
      if (filterType === 'func') return n.type === 'function' || n.type === 'method';
      return true;
    });

    const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));

    // Filter edges
    const filteredEdges = (edges || []).filter(
      (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target)
    );

    // Map to Vis dataset
    const visNodes = filteredNodes.map((n) => {
      let bg = '#1e293b';
      let border = '#38bdf8';
      let fontColor = '#f8fafc';

      if (n.is_dead) {
        bg = 'rgba(244, 63, 94, 0.25)';
        border = '#f43f5e';
      } else if (n.is_route) {
        bg = 'rgba(16, 185, 129, 0.25)';
        border = '#10b981';
      } else if (n.type === 'class') {
        bg = 'rgba(168, 85, 247, 0.25)';
        border = '#a855f7';
      } else if (n.type === 'component') {
        bg = 'rgba(245, 158, 11, 0.25)';
        border = '#f59e0b';
      } else {
        bg = 'rgba(56, 189, 248, 0.2)';
        border = '#38bdf8';
      }

      const size = Math.min(36, Math.max(14, 14 + (n.degree || 0) * 2));

      return {
        id: n.id,
        label: n.short_name || n.name,
        title: `${n.name}\n${n.type} in ${n.file}:${n.line}`,
        value: n.degree,
        color: {
          background: bg,
          border: border,
          highlight: {
            background: border,
            border: '#ffffff',
          },
        },
        font: {
          color: fontColor,
          size: 11,
          face: 'JetBrains Mono, monospace',
        },
        shape: n.is_route ? 'diamond' : (n.type === 'class' ? 'box' : 'dot'),
        size: size,
        borderWidth: 2,
        rawNode: n,
      };
    });

    const visEdges = filteredEdges.map((e, idx) => ({
      id: `e_${idx}`,
      from: e.source,
      to: e.target,
      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      color: {
        color: 'rgba(148, 163, 184, 0.25)',
        highlight: '#38bdf8',
      },
      width: 1.2,
      smooth: { type: 'continuous' },
    }));

    const data = { nodes: visNodes, edges: visEdges };

    const options = {
      nodes: {
        scaling: { min: 14, max: 36 },
      },
      edges: {
        hoverWidth: 2,
      },
      physics: {
        enabled: physicsEnabled,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -35,
          centralGravity: 0.008,
          springLength: 85,
          springConstant: 0.12,
        },
        stabilization: { iterations: 120 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        hideEdgesOnDrag: true,
      },
    };

    const network = new Network(containerRef.current, data, options);
    networkRef.current = network;

    network.on('click', (params) => {
      if (params.nodes.length > 0) {
        const clickedId = params.nodes[0];
        const selected = nodes.find((n) => n.id === clickedId);
        if (selected) {
          onSelectSymbol(selected);
        }
      }
    });

    return () => {
      network.destroy();
    };
  }, [nodes, edges, filterQuery, filterType, physicsEnabled]);

  // Center on selected symbol if passed
  useEffect(() => {
    if (networkRef.current && selectedSymbol) {
      networkRef.current.selectNodes([selectedSymbol.id]);
      networkRef.current.focus(selectedSymbol.id, {
        scale: 1.2,
        animation: { duration: 500, easingFunction: 'easeInOutQuad' },
      });
    }
  }, [selectedSymbol]);

  const handleZoomIn = () => {
    if (!networkRef.current) return;
    const scale = networkRef.current.getScale();
    networkRef.current.moveTo({ scale: scale * 1.3 });
  };

  const handleZoomOut = () => {
    if (!networkRef.current) return;
    const scale = networkRef.current.getScale();
    networkRef.current.moveTo({ scale: scale / 1.3 });
  };

  const handleFit = () => {
    if (!networkRef.current) return;
    networkRef.current.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
  };

  const togglePhysics = () => {
    setPhysicsEnabled((prev) => !prev);
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      {/* Floating Toolbar */}
      <div
        className="glass-panel"
        style={{
          position: 'absolute',
          top: '1rem',
          left: '1rem',
          zIndex: 20,
          display: 'flex',
          alignItems: 'center',
          gap: '0.6rem',
          padding: '0.5rem 0.75rem',
          borderRadius: '8px',
          boxShadow: '0 10px 25px -5px rgba(0,0,0,0.5)',
        }}
      >
        {/* Search */}
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <Search size={14} style={{ position: 'absolute', left: '0.6rem', color: '#64748b' }} />
          <input
            type="text"
            placeholder="Search symbols or files..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            style={{
              padding: '0.4rem 0.6rem 0.4rem 2rem',
              borderRadius: '6px',
              border: '1px solid rgba(51, 65, 85, 0.6)',
              background: 'rgba(15, 23, 42, 0.8)',
              color: '#f8fafc',
              fontSize: '0.8rem',
              width: '200px',
              outline: 'none',
            }}
          />
        </div>

        {/* Filter Type */}
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          style={{
            padding: '0.4rem 0.6rem',
            borderRadius: '6px',
            border: '1px solid rgba(51, 65, 85, 0.6)',
            background: 'rgba(15, 23, 42, 0.8)',
            color: '#f8fafc',
            fontSize: '0.8rem',
            outline: 'none',
            cursor: 'pointer',
          }}
        >
          <option value="all">All Symbols</option>
          <option value="route">🚀 API Routes</option>
          <option value="dead">💀 Dead Code</option>
          <option value="class">📦 Classes</option>
          <option value="component">🧩 Components</option>
          <option value="func">⚙️ Functions</option>
        </select>

        <div style={{ height: '1.2rem', width: '1px', background: 'rgba(51, 65, 85, 0.5)' }}></div>

        {/* View actions */}
        <button onClick={handleZoomIn} title="Zoom In" style={btnStyle}><ZoomIn size={14} /></button>
        <button onClick={handleZoomOut} title="Zoom Out" style={btnStyle}><ZoomOut size={14} /></button>
        <button onClick={handleFit} title="Fit Graph" style={btnStyle}><Maximize2 size={14} /></button>
        <button onClick={togglePhysics} title={physicsEnabled ? "Freeze Layout" : "Enable Physics"} style={btnStyle}>
          {physicsEnabled ? <Pause size={14} color="#38bdf8" /> : <Play size={14} color="#10b981" />}
        </button>
      </div>

      {/* Network Canvas */}
      <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#0a0e17' }} />
    </div>
  );
}

const btnStyle = {
  background: 'rgba(30, 41, 59, 0.7)',
  border: '1px solid rgba(51, 65, 85, 0.5)',
  color: '#cbd5e1',
  cursor: 'pointer',
  padding: '0.4rem',
  borderRadius: '6px',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};
