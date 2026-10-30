import React, { useEffect, useState } from 'react';
import Navbar from './components/Navbar';
import CodeMapView from './components/CodeMapView';
import DeadCodeView from './components/DeadCodeView';
import RoutesView from './components/RoutesView';
import SymbolCatalogView from './components/SymbolCatalogView';
import SymbolDrawer from './components/SymbolDrawer';
import { Loader2, AlertCircle } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('map');
  const [graphData, setGraphData] = useState(null);
  const [deadCodeData, setDeadCodeData] = useState(null);
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [graphRes, deadRes] = await Promise.all([
        fetch('/api/graph').then((r) => {
          if (!r.ok) throw new Error(`Graph HTTP ${r.status}`);
          return r.json();
        }),
        fetch('/api/deadcode').then((r) => {
          if (!r.ok) throw new Error(`Deadcode HTTP ${r.status}`);
          return r.json();
        }),
      ]);

      if (graphRes.error) throw new Error(graphRes.error);
      setGraphData(graphRes);
      setDeadCodeData(deadRes.dead_code || []);
    } catch (err) {
      setError(err.message || 'Failed to load graph data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* Top Navbar */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        stats={graphData?.stats}
        repoName={graphData?.repo_name}
        repoPath={graphData?.repo_path}
        onRefresh={fetchData}
        loading={loading}
      />

      {/* Main Content Area */}
      <main style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {loading && !graphData && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '0.75rem', color: '#94a3b8' }}>
            <Loader2 size={28} className="animate-spin" color="#38bdf8" />
            <div style={{ fontSize: '0.9rem', fontWeight: 500 }}>Connecting to local Code Graph...</div>
          </div>
        )}

        {error && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '1rem', color: '#fb7185', padding: '2rem' }}>
            <AlertCircle size={32} />
            <div style={{ fontSize: '1rem', fontWeight: 600 }}>Error loading graph data: {error}</div>
            <button
              onClick={fetchData}
              style={{
                background: '#38bdf8',
                color: '#090d16',
                border: 'none',
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Retry Connection
            </button>
          </div>
        )}

        {!loading && graphData && (
          <>
            {activeTab === 'map' && (
              <CodeMapView
                nodes={graphData.nodes}
                edges={graphData.edges}
                onSelectSymbol={setSelectedSymbol}
                selectedSymbol={selectedSymbol}
              />
            )}

            {activeTab === 'deadcode' && (
              <DeadCodeView
                deadCodeList={deadCodeData}
                nodes={graphData.nodes}
                onSelectSymbol={setSelectedSymbol}
              />
            )}

            {activeTab === 'routes' && (
              <RoutesView
                nodes={graphData.nodes}
                onSelectSymbol={setSelectedSymbol}
              />
            )}

            {activeTab === 'symbols' && (
              <SymbolCatalogView
                nodes={graphData.nodes}
                onSelectSymbol={setSelectedSymbol}
              />
            )}
          </>
        )}

        {/* Selected Symbol Detail Drawer */}
        {selectedSymbol && (
          <SymbolDrawer
            symbol={selectedSymbol}
            onClose={() => setSelectedSymbol(null)}
            onSelectSymbol={setSelectedSymbol}
            allEdges={graphData?.edges}
            allNodes={graphData?.nodes}
          />
        )}
      </main>
    </div>
  );
}
