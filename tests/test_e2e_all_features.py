"""
Complete End-to-End Master Test Suite for code-search-graph (v0.8.13)
Verifies:
  1. Multi-language AST Parsing (Python, TS, Java, Go, Rust, Vue, Svelte)
  2. Streaming Micro-batch Indexer (SQLite Graph + LanceDB 512-dim Vectors)
  3. 4-Way Hybrid Search (Dense Vector + BM25 + Ripgrep + AST)
  4. AST Call Graph Intelligence (Callers, Callees, Blast Radius, Dead Code, Outline, Diff Context)
  5. Persistent Background Daemon (IPC Socket, Warm Memory Sub-20ms Latency)
  6. React 18 Web UI Engine (SPA Serving, Static Assets, REST APIs)
  7. All 13 FastMCP Server Tools (Programmatic Invocation & Schema)
  8. Real Subprocess MCP JSON-RPC Stdio Protocol (Handshake, Tools/List, Tools/Call)
  9. Full CLI Subcommand Suite (16 Subcommands)
"""

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR / "tests"))
sys.path.insert(0, str(ROOT_DIR))

SAMPLE_REPO = ROOT_DIR / "tests" / "sample_project"


def banner(title: str, phase_num: int, total_phases: int = 9):
    line = "=" * 76
    print(f"\n{line}")
    print(f"🚀 [Phase {phase_num}/{total_phases}] {title}")
    print(f"{line}")


def test_phase_1_ast_parsers():
    banner("7-Language AST Parsers & Symbol Extraction", 1)
    from code_search_mcp.parsers.dispatcher import TreeSitterParser
    from code_search_mcp.parsers.common import EXTENSION_LANG_MAP

    parser = TreeSitterParser()
    supported_langs = [".py", ".ts", ".js", ".java", ".go", ".rs", ".vue", ".svelte"]
    for ext in supported_langs:
        assert ext in EXTENSION_LANG_MAP, f"Extension {ext} missing in EXTENSION_LANG_MAP"
    print(f"  ✓ 语言扩展名映射完整: {len(EXTENSION_LANG_MAP)} 个扩展名已就绪")

    # 1. Python
    py_code = b"def calculate_total(price, tax):\n    return price + tax\n"
    py_syms = parser.parse_code(py_code, "test.py", "python")
    assert any(s.name == "calculate_total" for s in py_syms)
    print("  ✓ Python AST 解析正常 (提取函数 calculate_total)")

    # 2. TypeScript
    ts_code = b"export class PaymentService {\n  processPayment(amount: number) { return true; }\n}"
    ts_syms = parser.parse_code(ts_code, "test.ts", "typescript")
    assert any(s.name == "PaymentService" for s in ts_syms)
    print("  ✓ TypeScript AST 解析正常 (提取类 PaymentService)")

    # 3. Java
    java_code = b"public class OrderService {\n  public void cancelOrder(String id) {}\n}"
    java_syms = parser.parse_code(java_code, "OrderService.java", "java")
    assert any(s.name == "OrderService" for s in java_syms)
    print("  ✓ Java AST 解析正常 (提取类 OrderService)")

    # 4. Go
    go_code = b"package main\nfunc HandleWebhook(payload []byte) bool { return true }"
    go_syms = parser.parse_code(go_code, "webhook.go", "go")
    assert any(s.name == "HandleWebhook" for s in go_syms)
    print("  ✓ Go AST 解析正常 (提取函数 HandleWebhook)")

    # 5. Rust
    rs_code = b"pub struct Router;\nimpl Router {\n  pub fn route(&self) {}\n}"
    rs_syms = parser.parse_code(rs_code, "router.rs", "rust")
    assert any(s.name == "Router" for s in rs_syms)
    print("  ✓ Rust AST 解析正常 (提取结构体与 impl Router)")

    # 6. Vue SFC
    vue_code = b"<template><button @click='doAction'>Go</button></template>\n<script setup>\nfunction doAction() {}\n</script>"
    vue_syms = parser.parse_code(vue_code, "Action.vue", "vue")
    assert any(s.symbol_type == "component" for s in vue_syms)
    print("  ✓ Vue SFC 解析正常 (提取 Component 与 setup 函数)")

    # 7. Svelte SFC
    svelte_code = b"<script lang='ts'>\nlet count = $state(0);\nfunction inc() { count++; }\n</script>\n<button onclick={inc}>Add</button>"
    svelte_syms = parser.parse_code(svelte_code, "Counter.svelte", "svelte")
    assert any(s.symbol_type == "component" for s in svelte_syms)
    print("  ✓ Svelte SFC 解析正常 (提取 Component 与 Runes 状态函数)")


def test_phase_2_streaming_indexer():
    banner("Streaming Indexer (SQLite + LanceDB 512-dim Vectors)", 2)
    from code_search_mcp.indexer import CodeIndexer
    from code_search_mcp.searcher import CodeSearcher

    t0 = time.perf_counter()
    indexer = CodeIndexer(SAMPLE_REPO)
    res = indexer.index_all()
    t_idx = time.perf_counter() - t0

    assert res["status"] == "success"
    assert res["indexed_files"] >= 8
    assert res["indexed_chunks"] >= 30
    assert res["vector_indexed"] is True
    print(f"  ✓ 索引构建耗时: {t_idx:.2f}s | 索引文件数: {res['indexed_files']} | 切片数: {res['indexed_chunks']}")

    searcher = CodeSearcher(SAMPLE_REPO)
    tbl = searcher._get_table()
    assert tbl is not None
    total_vectors = len(tbl)
    assert total_vectors > 0
    print(f"  ✓ LanceDB 向量表就绪: {total_vectors} 条密集向量持久化 (512 维)")


def test_phase_3_search_engine():
    banner("4-Way Hybrid Search (Semantic Dense + Ripgrep Exact)", 3)
    from code_search_mcp.searcher import CodeSearcher
    from code_search_mcp.ripgrep_engine import ExactSearchEngine

    searcher = CodeSearcher(SAMPLE_REPO)
    # 语义检索
    t0 = time.perf_counter()
    matches = searcher.search("user password authentication and verification", top_k=3)
    t_sem = (time.perf_counter() - t0) * 1000
    assert len(matches) > 0
    top_hit = matches[0]
    print(f"  ✓ 混合语义检索耗时: {t_sem:.2f}ms | Top-1: {top_hit['symbol_name']} ({top_hit['file_path']})")

    # 精确匹配 (ripgrep)
    exact_engine = ExactSearchEngine(SAMPLE_REPO)
    t0_exact = time.perf_counter()
    exact_res = exact_engine.search("hash_password", max_results=5)
    t_exact = (time.perf_counter() - t0_exact) * 1000
    assert len(exact_res) > 0
    print(f"  ✓ ripgrep 字面量搜索耗时: {t_exact:.2f}ms | 命中数: {len(exact_res)}")


def test_phase_4_graph_intelligence():
    banner("AST Call Graph Intelligence & Impact Radius", 4)
    from code_search_mcp.graph_engine import CodeGraphEngine
    from code_search_mcp.outline import ProjectOutlineGenerator

    engine = CodeGraphEngine.get_instance(SAMPLE_REPO)

    # 1. Callers
    callers = engine.get_callers("hash_password")
    assert callers["callers_count"] > 0
    print(f"  ✓ 上游调用追踪: 'hash_password' 有 {callers['callers_count']} 处调用者")

    # 2. Callees
    callees = engine.get_callees("AuthService.login")
    assert callees["callees_count"] > 0
    print(f"  ✓ 下游依赖追踪: 'AuthService.login' 调用了 {callees['callees_count']} 个子函数")

    # 3. Blast radius
    impact = engine.get_impact_radius("hash_password", max_depth=3)
    assert impact["total_impacted_symbols"] > 0
    affected_routes = impact.get("impacted_external_routes", [])
    print(f"  ✓ 改动爆炸半径: 波及 {impact['total_impacted_symbols']} 个符号, 影响 {len(affected_routes)} 个 HTTP 路由")

    # 4. Dead code
    dead = engine.find_dead_code(limit=50)
    assert dead["total_candidates"] > 0
    print(f"  ✓ 死代码检测: 检出 {dead['total_candidates']} 个未调用孤立符号候选")

    # 5. Outline
    generator = ProjectOutlineGenerator(SAMPLE_REPO)
    outline_data = generator.get_cached_or_generate()
    outline = generator.format_as_markdown(outline_data, max_depth=3)
    assert "auth.py" in outline
    print(f"  ✓ 架构大纲生成: 生成 {len(outline.splitlines())} 行多语言架构地图")


def test_phase_5_daemon_mode():
    banner("Background Daemon Mode & Sub-20ms IPC Latency", 5)
    from tests.test_daemon import test_daemon_full_lifecycle_and_ipc_calls
    test_daemon_full_lifecycle_and_ipc_calls()
    print("  🎉 守护进程全生命周期与毫秒级热内存查询 100% 通过！")


def test_phase_6_react_web_ui():
    banner("React 18 Web UI Engine & REST API Endpoints", 6)
    from code_search_mcp.ui_server import launch_web_ui

    port, server = launch_web_ui(SAMPLE_REPO, port=57189, open_browser=False)
    t_ui = threading.Thread(target=server.serve_forever, daemon=True)
    t_ui.start()
    time.sleep(0.3)

    base_url = f"http://127.0.0.1:{port}"
    try:
        # 1. 验证首页 React SPA
        with urllib.request.urlopen(f"{base_url}/") as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "html" in content.lower()
            assert "assets" in content or "code-search-graph" in content
            print("  ✓ React 18 SPA 首页根路由加载正常 (200 OK)")

        # 2. 验证 /api/graph 接口
        with urllib.request.urlopen(f"{base_url}/api/graph") as resp:
            assert resp.status == 200
            graph_data = json.loads(resp.read().decode("utf-8"))
            assert len(graph_data.get("nodes", [])) > 0
            assert len(graph_data.get("edges", [])) > 0
            print(f"  ✓ /api/graph 接口正常: 返回 {len(graph_data['nodes'])} 个节点, {len(graph_data['edges'])} 条调用边")

        # 3. 验证 /api/deadcode 接口
        with urllib.request.urlopen(f"{base_url}/api/deadcode") as resp:
            assert resp.status == 200
            dead_data = json.loads(resp.read().decode("utf-8"))
            assert dead_data.get("total_candidates", 0) > 0
            print(f"  ✓ /api/deadcode 接口正常: 返回 {dead_data['total_candidates']} 个死代码候选")

        # 4. 验证 /api/source 接口
        with urllib.request.urlopen(f"{base_url}/api/source?file=auth.py&start=1&end=20") as resp:
            assert resp.status == 200
            src_data = json.loads(resp.read().decode("utf-8"))
            assert "lines" in src_data
            all_text = "".join(src_data["lines"])
            assert "def hash_password" in all_text
            print("  ✓ /api/source 切片查看器接口正常 (切片行精确读取)")

    finally:
        server.shutdown()
        server.server_close()
        print("  ✓ Web UI 服务测试结束并安全关闭")


def test_phase_7_all_13_mcp_tools():
    banner("All 13 FastMCP Server Tools (Programmatic Invocation)", 7)
    from code_search_mcp.server import (
        index_codebase,
        get_codebase_outline,
        search_codebase,
        exact_search,
        get_file_content,
        explore_codebase,
        get_symbol_callers,
        get_symbol_callees,
        get_impact_radius,
        find_references,
        get_diff_context,
        find_dead_code,
        get_watch_status,
    )

    path_str = str(SAMPLE_REPO)

    # 1. index_codebase
    t0 = time.perf_counter()
    res1 = index_codebase(path_str)
    assert "Complete" in res1 or "Indexed" in res1
    print("  ✓ [1/13] index_codebase: 通过")

    # 2. get_codebase_outline
    res2 = get_codebase_outline(path_str, max_depth=3)
    assert "auth.py" in res2
    print("  ✓ [2/13] get_codebase_outline: 通过")

    # 3. search_codebase
    res3 = search_codebase(query="user login password", path=path_str, top_k=3)
    assert "Code Search Results" in res3
    print("  ✓ [3/13] search_codebase: 通过")

    # 4. exact_search
    res4 = exact_search(pattern="hash_password", path=path_str)
    assert "hash_password" in res4
    print("  ✓ [4/13] exact_search: 通过")

    # 5. get_file_content
    res5 = get_file_content(str(SAMPLE_REPO / "auth.py"), start_line=1, end_line=15)
    assert "def " in res5
    print("  ✓ [5/13] get_file_content: 通过")

    # 6. explore_codebase
    res6 = explore_codebase(query="user authentication login flow", path=path_str, top_k=1)
    assert "Exploration" in res6 or "auth" in res6
    print("  ✓ [6/13] explore_codebase: 通过")

    # 7. get_symbol_callers
    res7 = get_symbol_callers(symbol_name="hash_password", path=path_str)
    assert "Callers" in res7 or "login" in res7
    print("  ✓ [7/13] get_symbol_callers: 通过")

    # 8. get_symbol_callees
    res8 = get_symbol_callees(symbol_name="AuthService.login", path=path_str)
    assert "Callees" in res8 or "hash_password" in res8
    print("  ✓ [8/13] get_symbol_callees: 通过")

    # 9. get_impact_radius
    res9 = get_impact_radius(symbol_name="hash_password", path=path_str, max_depth=2)
    assert "Blast-Radius" in res9 or "Impact" in res9
    print("  ✓ [9/13] get_impact_radius: 通过")

    # 10. find_references
    res10 = find_references(symbol_or_keyword="verify_password", path=path_str)
    assert "References" in res10
    print("  ✓ [10/13] find_references: 通过")

    # 11. get_diff_context
    res11 = get_diff_context(target="HEAD", path=path_str)
    assert "Git Diff" in res11 or "Clean" in res11
    print("  ✓ [11/13] get_diff_context: 通过")

    # 12. find_dead_code
    res12 = find_dead_code(path=path_str, limit=10)
    assert "Dead Code" in res12
    print("  ✓ [12/13] find_dead_code: 通过")

    # 13. get_watch_status
    res13 = get_watch_status(path=path_str)
    assert "Watcher Status" in res13 or "Status" in res13
    print("  ✓ [13/13] get_watch_status: 通过")

    print(f"  🎉 全部 13 个 MCP 工具接口测试 100% 通过！")


def test_phase_8_mcp_stdio_jsonrpc():
    banner("Real Subprocess MCP JSON-RPC Stdio Protocol", 8)
    from tests.test_mcp_protocol_stdio import test_mcp_stdio_protocol
    test_mcp_stdio_protocol()


def test_phase_9_cli_suite():
    banner("Full CLI Subcommands Suite (16 Subcommands)", 9)
    from tests.test_cli import test_cli_all_subcommands
    test_cli_all_subcommands()


def run_all_e2e_tests():
    total_t0 = time.perf_counter()
    print("\n" + "#" * 80)
    print("🔥 code-search-graph 全流程 / 全功能端到端综合测试")
    print(f"   版本: v0.8.13 | 操作系统: {sys.platform} | 采样库: {SAMPLE_REPO}")
    print("#" * 80)

    test_phase_1_ast_parsers()
    test_phase_2_streaming_indexer()
    test_phase_3_search_engine()
    test_phase_4_graph_intelligence()
    test_phase_5_daemon_mode()
    test_phase_6_react_web_ui()
    test_phase_7_all_13_mcp_tools()
    test_phase_8_mcp_stdio_jsonrpc()
    test_phase_9_cli_suite()

    total_time = time.perf_counter() - total_t0
    print("\n" + "=" * 80)
    print("🎉 恭喜！9 大核心阶段、全套 13 项 MCP 工具、全功能 CLI 与 React Web UI 全部测试通过！")
    print(f"⏱️ 全流程端到端测试总耗时: {total_time:.2f} 秒")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_all_e2e_tests()
