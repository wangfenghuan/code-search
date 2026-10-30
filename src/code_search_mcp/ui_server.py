"""code-search-graph Web UI Server & Interactive Code Map

Provides local web server and interactive code knowledge map:
- 3D/2D force-directed call graph visualization
- Symbol inspector & source code slice preview
- Real-time symbol search & module isolation
- Dead code & Web route highlights
- Zero external dependencies (Python standard library http.server)
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse

from code_search_mcp.graph_engine import CodeGraphEngine, is_test_node


def find_available_port(start_port: int = 8765, max_attempts: int = 30) -> int:
    """Find an available TCP port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>code-search-graph • Code Map & Intelligence Hub</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(15, 23, 42, 0.85);
      --card-border: rgba(51, 65, 85, 0.5);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --route-color: #10b981;
      --dead-color: #f43f5e;
      --class-color: #a855f7;
      --func-color: #38bdf8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }

    /* Top Navigation Bar */
    header {
      height: 60px;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand-icon {
      width: 32px;
      height: 32px;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 16px;
      color: #0f172a;
      box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
    }
    .brand-title {
      font-weight: 700;
      font-size: 16px;
      letter-spacing: -0.02em;
      color: #fff;
    }
    .brand-repo {
      font-size: 12px;
      color: var(--text-muted);
      background: rgba(30, 41, 59, 0.8);
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid var(--card-border);
      font-family: 'JetBrains Mono', monospace;
    }

    /* Stats & Controls Bar */
    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .search-box {
      position: relative;
    }
    .search-input {
      background: rgba(30, 41, 59, 0.9);
      border: 1px solid var(--card-border);
      color: #fff;
      padding: 7px 12px 7px 32px;
      border-radius: 8px;
      font-size: 13px;
      width: 240px;
      outline: none;
      transition: all 0.2s;
    }
    .search-input:focus {
      width: 300px;
      border-color: var(--primary);
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
    }
    .search-icon {
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      font-size: 12px;
      color: var(--text-muted);
    }

    .pill-btn {
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
      user-select: none;
    }
    .pill-btn:hover {
      background: rgba(51, 65, 85, 0.8);
      color: #fff;
    }
    .pill-btn.active {
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--primary);
      color: var(--primary);
    }
    .pill-btn.dead-active {
      background: rgba(244, 63, 94, 0.15);
      border-color: var(--dead-color);
      color: var(--dead-color);
    }
    .pill-btn.route-active {
      background: rgba(16, 185, 129, 0.15);
      border-color: var(--route-color);
      color: var(--route-color);
    }

    /* Main Container */
    main {
      flex: 1;
      position: relative;
      display: flex;
      height: calc(100vh - 60px);
    }
    #network-canvas {
      flex: 1;
      height: 100%;
      background: radial-gradient(circle at 50% 50%, rgba(30, 41, 59, 0.4) 0%, rgba(9, 13, 22, 1) 100%);
    }

    /* Floating Legend / Stats Badge */
    .floating-stats {
      position: absolute;
      bottom: 20px;
      left: 20px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(10px);
      padding: 12px 16px;
      border-radius: 12px;
      display: flex;
      gap: 16px;
      font-size: 12px;
      z-index: 50;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
    }
    .stat-item {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .stat-num {
      font-weight: 700;
      font-size: 15px;
      color: #fff;
    }
    .stat-label {
      color: var(--text-muted);
      font-size: 11px;
    }

    /* Right Sidebar Node Details */
    #sidebar {
      width: 420px;
      height: 100%;
      background: var(--card-bg);
      border-left: 1px solid var(--card-border);
      backdrop-filter: blur(16px);
      display: flex;
      flex-direction: column;
      transform: translateX(100%);
      transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      z-index: 90;
      position: absolute;
      right: 0;
      top: 0;
      box-shadow: -10px 0 30px rgba(0, 0, 0, 0.6);
    }
    #sidebar.open {
      transform: translateX(0);
    }
    .sidebar-header {
      padding: 18px 20px;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
    }
    .close-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 18px;
      cursor: pointer;
      padding: 4px;
      border-radius: 6px;
      line-height: 1;
    }
    .close-btn:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.1);
    }
    .sidebar-body {
      padding: 20px;
      overflow-y: auto;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .section-title {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 8px;
    }
    .meta-card {
      background: rgba(30, 41, 59, 0.6);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .tag-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      width: fit-content;
    }
    .tag-route { background: rgba(16, 185, 129, 0.2); color: var(--route-color); border: 1px solid var(--route-color); }
    .tag-dead { background: rgba(244, 63, 94, 0.2); color: var(--dead-color); border: 1px solid var(--dead-color); }
    .tag-func { background: rgba(56, 189, 248, 0.2); color: var(--func-color); border: 1px solid var(--func-color); }
    .tag-class { background: rgba(168, 85, 247, 0.2); color: var(--class-color); border: 1px solid var(--class-color); }

    .link-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .link-item {
      background: rgba(30, 41, 59, 0.5);
      border: 1px solid var(--card-border);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-family: 'JetBrains Mono', monospace;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: all 0.15s;
    }
    .link-item:hover {
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--primary);
      color: #fff;
    }

    .source-block {
      background: #050811;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 12px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      line-height: 1.6;
      max-height: 320px;
      overflow: auto;
      white-space: pre;
      color: #e2e8f0;
    }
    .source-line {
      display: flex;
      gap: 12px;
    }
    .source-ln {
      color: #475569;
      user-select: none;
      min-width: 32px;
      text-align: right;
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <div>
        <div class="brand-title">code-search-graph</div>
      </div>
      <div class="brand-repo" id="repo-name">Loading...</div>
    </div>

    <div class="controls">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="search-input" id="search-input" placeholder="Search symbols or files...">
      </div>
      <button class="pill-btn active" id="btn-all" onclick="filterGraph('all')">All</button>
      <button class="pill-btn" id="btn-routes" onclick="filterGraph('routes')">🌐 Web Routes</button>
      <button class="pill-btn" id="btn-dead" onclick="filterGraph('dead')">💀 Dead Code</button>
      <button class="pill-btn" id="btn-reset" onclick="resetLayout()">🎯 Fit</button>
      <button class="pill-btn" id="btn-physics" onclick="togglePhysics()">⏸️ Freeze</button>
    </div>
  </header>

  <main>
    <div id="network-canvas"></div>

    <div class="floating-stats">
      <div class="stat-item">
        <span class="stat-num" id="stat-symbols">0</span>
        <span class="stat-label">Symbols</span>
      </div>
      <div class="stat-item">
        <span class="stat-num" id="stat-edges">0</span>
        <span class="stat-label">Call Edges</span>
      </div>
      <div class="stat-item">
        <span class="stat-num" id="stat-routes">0</span>
        <span class="stat-label">API Routes</span>
      </div>
      <div class="stat-item">
        <span class="stat-num" id="stat-dead">0</span>
        <span class="stat-label">Dead Code</span>
      </div>
    </div>

    <!-- Details Sidebar -->
    <div id="sidebar">
      <div class="sidebar-header">
        <div>
          <h2 id="node-name" style="font-size: 17px; font-weight: 700; word-break: break-all;">Symbol</h2>
          <div id="node-tags" style="display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap;"></div>
        </div>
        <button class="close-btn" onclick="closeSidebar()">✕</button>
      </div>

      <div class="sidebar-body">
        <div>
          <div class="section-title">File Location</div>
          <div class="meta-card">
            <span id="node-location" style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--primary);"></span>
            <span id="node-doc" style="font-size: 12px; color: var(--text-muted); margin-top: 4px; font-style: italic;"></span>
          </div>
        </div>

        <div id="section-callers">
          <div class="section-title">Upstream Callers (<span id="count-callers">0</span>)</div>
          <div class="link-list" id="list-callers"></div>
        </div>

        <div id="section-callees">
          <div class="section-title">Downstream Callees (<span id="count-callees">0</span>)</div>
          <div class="link-list" id="list-callees"></div>
        </div>

        <div id="section-source">
          <div class="section-title">Source Code Preview</div>
          <div class="source-block" id="source-code">Loading...</div>
        </div>
      </div>
    </div>
  </main>

  <script>
    let network = null;
    let graphData = null;
    let allNodes = [];
    let allEdges = [];
    let activeFilter = 'all';
    let physicsEnabled = true;

    async function init() {
      try {
        const res = await fetch('/api/graph');
        graphData = await res.json();

        document.getElementById('repo-name').textContent = graphData.repo_name || 'Repository';
        document.getElementById('stat-symbols').textContent = graphData.stats.total_nodes;
        document.getElementById('stat-edges').textContent = graphData.stats.total_edges;
        document.getElementById('stat-routes').textContent = graphData.stats.routes_count;
        document.getElementById('stat-dead').textContent = graphData.stats.dead_code_count;

        allNodes = graphData.nodes;
        allEdges = graphData.edges;

        renderNetwork(allNodes, allEdges);
      } catch (err) {
        console.error('Failed to load graph data:', err);
      }
    }

    function renderNetwork(nodesList, edgesList) {
      const container = document.getElementById('network-canvas');

      const visNodes = new vis.DataSet(nodesList.map(n => {
        let color = { background: '#0284c7', border: '#38bdf8' };
        let shape = 'dot';
        let size = 16 + Math.min(25, (n.degree || 1) * 3);

        if (n.is_route) {
          color = { background: '#059669', border: '#10b981' };
          shape = 'diamond';
          size += 6;
        } else if (n.is_dead) {
          color = { background: '#e11d48', border: '#f43f5e' };
        } else if (n.type === 'class' || n.type === 'struct' || n.type === 'interface') {
          color = { background: '#7c3aed', border: '#a855f7' };
          shape = 'square';
          size += 4;
        }

        return {
          id: n.id,
          label: n.short_name || n.name,
          title: `${n.name}\n${n.file}:L${n.line}${n.route ? '\n' + n.route : ''}`,
          color: color,
          shape: shape,
          size: size,
          font: { color: '#f8fafc', size: 12, face: 'Plus Jakarta Sans' },
          raw: n,
        };
      }));

      const visEdges = new vis.DataSet(edgesList.map((e, idx) => ({
        id: 'e_' + idx,
        from: e.source,
        to: e.target,
        arrows: 'to',
        color: { color: 'rgba(100, 116, 139, 0.45)', highlight: '#38bdf8', hover: '#38bdf8' },
        width: 1.5,
        smooth: { type: 'continuous' },
      })));

      const data = { nodes: visNodes, edges: visEdges };
      const options = {
        physics: {
          solver: 'forceAtlas2Based',
          forceAtlas2Based: {
            gravitationalConstant: -40,
            centralGravity: 0.005,
            springLength: 85,
            springConstant: 0.18,
          },
          stabilization: { iterations: 120 },
        },
        interaction: {
          hover: true,
          tooltipDelay: 150,
          navigationButtons: false,
        },
      };

      if (network) network.destroy();
      network = new vis.Network(container, data, options);

      network.on('click', function(params) {
        if (params.nodes.length > 0) {
          const nodeId = params.nodes[0];
          const nodeObj = allNodes.find(n => n.id === nodeId);
          if (nodeObj) showNodeDetails(nodeObj);
        } else {
          closeSidebar();
        }
      });
    }

    function showNodeDetails(n) {
      document.getElementById('node-name').textContent = n.name;
      document.getElementById('node-location').textContent = `${n.file}:L${n.line}-${n.end_line || n.line}`;
      document.getElementById('node-doc').textContent = n.docstring || '';

      const tags = document.getElementById('node-tags');
      tags.innerHTML = '';
      tags.innerHTML += `<span class="tag-badge tag-func">${n.type}</span>`;
      if (n.is_route) {
        tags.innerHTML += `<span class="tag-badge tag-route">🌐 ${n.route}</span>`;
      }
      if (n.is_dead) {
        tags.innerHTML += `<span class="tag-badge tag-dead">💀 Uncalled</span>`;
      }

      // Callers
      const callers = allEdges.filter(e => e.target === n.id).map(e => allNodes.find(x => x.id === e.source)).filter(Boolean);
      document.getElementById('count-callers').textContent = callers.length;
      const callerList = document.getElementById('list-callers');
      callerList.innerHTML = callers.length === 0 ? '<div style="font-size:12px;color:#64748b;">No callers found</div>' :
        callers.map(c => `<div class="link-item" onclick="focusNode('${c.id}')">${c.name} <span>→</span></div>`).join('');

      // Callees
      const callees = allEdges.filter(e => e.source === n.id).map(e => allNodes.find(x => x.id === e.target)).filter(Boolean);
      document.getElementById('count-callees').textContent = callees.length;
      const calleeList = document.getElementById('list-callees');
      calleeList.innerHTML = callees.length === 0 ? '<div style="font-size:12px;color:#64748b;">No dependencies called</div>' :
        callees.map(c => `<div class="link-item" onclick="focusNode('${c.id}')">${c.name} <span>→</span></div>`).join('');

      // Fetch Source Code
      fetchSourceCode(n.file, n.line, n.end_line || (n.line + 20));

      document.getElementById('sidebar').classList.add('open');
    }

    async function fetchSourceCode(file, start, end) {
      const box = document.getElementById('source-code');
      box.textContent = 'Loading source...';
      try {
        const res = await fetch(`/api/source?file=${encodeURIComponent(file)}&start=${start}&end=${end}`);
        const data = await res.json();
        if (data.lines) {
          box.innerHTML = data.lines.map((l, i) =>
            `<div class="source-line"><span class="source-ln">${data.start_line + i}</span><span>${escapeHtml(l)}</span></div>`
          ).join('');
        } else {
          box.textContent = 'Source unavailable';
        }
      } catch (e) {
        box.textContent = 'Failed to load source snippet';
      }
    }

    function escapeHtml(str) {
      return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function focusNode(nodeId) {
      if (!network) return;
      network.focus(nodeId, { scale: 1.2, animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
      network.selectNodes([nodeId]);
      const nodeObj = allNodes.find(n => n.id === nodeId);
      if (nodeObj) showNodeDetails(nodeObj);
    }

    function closeSidebar() {
      document.getElementById('sidebar').classList.remove('open');
      if (network) network.unselectAll();
    }

    function filterGraph(mode) {
      activeFilter = mode;
      document.querySelectorAll('.pill-btn').forEach(b => b.classList.remove('active', 'dead-active', 'route-active'));

      if (mode === 'all') {
        document.getElementById('btn-all').classList.add('active');
        renderNetwork(allNodes, allEdges);
      } else if (mode === 'routes') {
        document.getElementById('btn-routes').classList.add('route-active');
        const routeNodeIds = new Set(allNodes.filter(n => n.is_route).map(n => n.id));
        // Include route nodes and their direct callees
        const relevantNodeIds = new Set(routeNodeIds);
        allEdges.forEach(e => {
          if (routeNodeIds.has(e.source)) relevantNodeIds.add(e.target);
        });
        const filteredNodes = allNodes.filter(n => relevantNodeIds.has(n.id));
        const filteredEdges = allEdges.filter(e => relevantNodeIds.has(e.source) && relevantNodeIds.has(e.target));
        renderNetwork(filteredNodes, filteredEdges);
      } else if (mode === 'dead') {
        document.getElementById('btn-dead').classList.add('dead-active');
        const filteredNodes = allNodes.filter(n => n.is_dead);
        renderNetwork(filteredNodes, []);
      }
    }

    function resetLayout() {
      if (network) network.fit({ animation: { duration: 500 } });
    }

    function togglePhysics() {
      physicsEnabled = !physicsEnabled;
      if (network) network.setOptions({ physics: { enabled: physicsEnabled } });
      document.getElementById('btn-physics').textContent = physicsEnabled ? '⏸️ Freeze' : '▶️ Physics';
    }

    // Search Box Listener
    document.getElementById('search-input').addEventListener('input', function(e) {
      const q = e.target.value.trim().toLowerCase();
      if (!q) return;
      const matched = allNodes.find(n => n.name.toLowerCase().includes(q) || n.file.toLowerCase().includes(q));
      if (matched) {
        focusNode(matched.id);
      }
    });

    window.addEventListener('DOMContentLoaded', init);
  </script>
</body>
</html>
"""


def get_web_dist_dir() -> Path:
    return Path(__file__).resolve().parent / "web_dist"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


class CodeGraphRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for React Code Graph Visualizer"""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/graph":
            self.handle_api_graph()
            return

        if path == "/api/deadcode":
            self.handle_api_deadcode()
            return

        if path == "/api/source":
            self.handle_api_source(query)
            return

        # Serve React production build from web_dist
        web_dist = get_web_dist_dir()
        if web_dist.exists():
            target_path = path.lstrip("/")
            if target_path:
                file_candidate = (web_dist / target_path).resolve()
                try:
                    file_candidate.relative_to(web_dist)
                    if file_candidate.is_file():
                        ext = file_candidate.suffix.lower()
                        mime = MIME_TYPES.get(ext, "application/octet-stream")
                        content = file_candidate.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", mime)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return
                except Exception:
                    pass

            # SPA route fallback to index.html
            index_file = web_dist / "index.html"
            if index_file.is_file():
                content = index_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        # Fallback to embedded HTML template
        if path == "/" or not path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        self.send_error(404, "Not Found")

    def handle_api_graph(self):
        engine: CodeGraphEngine = self.server.engine
        repo_path: Path = self.server.repo_path

        try:
            # 1. Fetch dead code candidate set first
            dead_info = engine.find_dead_code(limit=500)
            dead_ids = {d["id"] for d in dead_info.get("dead_code", [])}

            conn = engine._get_db()

            # 2. Fetch nodes
            node_rows = conn.execute(
                "SELECT id, symbol_name, chunk_type, file_path, start_line, end_line, route_info, docstring, qualified_name FROM nodes WHERE chunk_type != 'file'"
            ).fetchall()

            # 3. Fetch resolved edges
            edge_rows = conn.execute(
                "SELECT caller_id, callee_id, caller_symbol, callee_symbol, resolution_type, confidence "
                "FROM resolved_edges WHERE callee_id IS NOT NULL"
            ).fetchall()

            # Compute degree
            degree_map: Dict[str, int] = {}
            for r in edge_rows:
                c_in = r["caller_id"]
                c_out = r["callee_id"]
                degree_map[c_in] = degree_map.get(c_in, 0) + 1
                degree_map[c_out] = degree_map.get(c_out, 0) + 1

            nodes_data = []
            files_set = set()
            routes_count = 0

            for r in node_rows:
                nid = r["id"]
                sym = r["symbol_name"]
                ctype = r["chunk_type"]
                fpath = r["file_path"]
                sline = r["start_line"]
                eline = r["end_line"]
                route = r["route_info"]
                doc = r["docstring"]
                qual = r["qualified_name"]
                files_set.add(fpath)
                is_route = bool(route and route.strip())
                if is_route:
                    routes_count += 1

                nodes_data.append({
                    "id": nid,
                    "name": sym,
                    "short_name": sym.split(".")[-1],
                    "type": ctype,
                    "file": fpath,
                    "line": sline,
                    "end_line": eline,
                    "route": route or "",
                    "is_route": is_route,
                    "is_dead": nid in dead_ids,
                    "degree": degree_map.get(nid, 0),
                    "docstring": (doc or "").strip()[:80],
                })

            edges_data = []
            for r in edge_rows:
                edges_data.append({
                    "source": r["caller_id"],
                    "target": r["callee_id"],
                    "caller": r["caller_symbol"],
                    "callee": r["callee_symbol"],
                    "type": r["resolution_type"],
                    "confidence": float(r["confidence"]),
                })

            payload = {
                "repo_name": repo_path.name,
                "repo_path": str(repo_path),
                "nodes": nodes_data,
                "edges": edges_data,
                "stats": {
                    "total_nodes": len(nodes_data),
                    "total_edges": len(edges_data),
                    "total_files": len(files_set),
                    "routes_count": routes_count,
                    "dead_code_count": len(dead_ids),
                },
            }

            self.send_json(payload)
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_api_deadcode(self):
        engine: CodeGraphEngine = self.server.engine
        try:
            res = engine.find_dead_code(limit=200)
            self.send_json(res)
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_api_source(self, query: Dict[str, List[str]]):
        repo_path: Path = self.server.repo_path
        f_rel = query.get("file", [""])[0]
        s_line = int(query.get("start", [1])[0])
        e_line = int(query.get("end", [s_line + 30])[0])

        target_file = (repo_path / f_rel).resolve()
        if not target_file.exists() or not target_file.is_file():
            self.send_json({"error": f"File '{f_rel}' not found"}, status=404)
            return

        try:
            content = target_file.read_text(encoding="utf-8", errors="replace")
            all_lines = content.splitlines()
            s = max(1, s_line)
            e = min(len(all_lines), e_line)
            slice_lines = all_lines[s - 1 : e]
            self.send_json({
                "file": f_rel,
                "start_line": s,
                "end_line": e,
                "lines": slice_lines,
            })
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Silence access logs to keep stdio / terminal completely clean
        pass


def launch_web_ui(repo_path: Path | str, port: int = 8765, open_browser: bool = True) -> tuple[int, ThreadingHTTPServer]:
    """Launch local code-search-graph Web UI server."""
    repo = Path(repo_path).resolve()
    engine = CodeGraphEngine.get_instance(repo)
    if not engine.load():
        from code_search_mcp.indexer import CodeIndexer
        indexer = CodeIndexer(repo)
        indexer.index_all()
        engine.load()

    actual_port = find_available_port(port)
    server = ThreadingHTTPServer(("127.0.0.1", actual_port), CodeGraphRequestHandler)
    server.repo_path = repo
    server.engine = engine

    url = f"http://127.0.0.1:{actual_port}"

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    return actual_port, server
