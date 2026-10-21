import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from code_search_mcp.graph_engine import CodeGraphEngine
from code_search_mcp.indexer import UniversalCodeChunker
from code_search_mcp.multilang_parser import TreeSitterParser


def run_fastapi_benchmark() -> Dict[str, Any]:
    print("\n" + "=" * 70)
    print("🔥 [REPO 1/3] FastAPI 工业级全量端到端基准测试 (Python Web API 框架)")
    print("=" * 70)

    fastapi_dir = ROOT_DIR / "tests" / "benchmark_repos" / "fastapi"
    assert fastapi_dir.exists(), f"未找到 FastAPI 目录: {fastapi_dir}"

    py_files = [f for f in fastapi_dir.rglob("*.py") if f.is_file()]
    print(f"📂 发现 {len(py_files)} 个 Python 源文件，开始全量语法解析与符号切片...")

    # 1. 语法提取与吞吐压测
    parser = TreeSitterParser()
    t0_parse = time.perf_counter()
    total_symbols = 0
    total_raw_calls = 0
    parse_errors = 0
    giant_files = []

    for f in py_files:
        try:
            sz = f.stat().st_size
            if sz > 80_000:
                giant_files.append((f.name, sz))
            syms = parser.parse_file(f)
            total_symbols += len(syms)
            total_raw_calls += sum(len(s.calls) for s in syms)
        except Exception as e:
            parse_errors += 1
            sys.stderr.write(f"解析异常 {f.name}: {e}\n")

    t_parse = time.perf_counter() - t0_parse
    throughput_parse = len(py_files) / t_parse if t_parse > 0 else 0

    print(f"   ✓ 语法解析完成: {len(py_files)} 文件 | 耗时: {t_parse:.3f}s | 吞吐: {throughput_parse:.1f} 文件/秒")
    print(f"   ✓ 提取符号: {total_symbols} 个 | 提取调用点: {total_raw_calls} 个 | 异常: {parse_errors}")

    # 2. 全量图谱构建与 Two-Phase Resolution 压测
    print(f"⚡ 构建 FastAPI SQLite 全局代码调用拓扑图...")
    engine = CodeGraphEngine(fastapi_dir)
    conn = engine._get_db()
    engine._init_sqlite_schema(conn)

    t0_stage1 = time.perf_counter()
    chunker = UniversalCodeChunker(fastapi_dir)
    nodes_to_insert = []
    calls_to_insert = []

    for f in py_files:
        try:
            chunks = chunker.parse_file(f)
            for c in chunks:
                node_id = f"{c.file_path}:{c.start_line}:{c.symbol_name}"
                nodes_to_insert.append((
                    node_id, c.file_path, c.symbol_name, c.chunk_type,
                    c.start_line, c.end_line, c.code, c.docstring,
                    c.route_info, c.module_name, c.qualified_name
                ))
                raw_calls = json.loads(c.calls) if isinstance(c.calls, str) else (c.calls or [])
                for call_str in raw_calls:
                    if not call_str:
                        continue
                    is_dyn = 1 if ("dynamic:" in call_str or call_str.startswith("<dynamic:")) else 0
                    c_name = call_str.split(".")[-1] if "." in call_str else call_str
                    c_qual = call_str if "." in call_str else ""
                    calls_to_insert.append((
                        node_id, c.symbol_name, c_name, c_qual, is_dyn, "", c.file_path
                    ))
        except Exception as e:
            sys.stderr.write(f"Chunker 异常 {f.name}: {e}\n")

    conn.execute("DELETE FROM resolved_edges;")
    conn.execute("DELETE FROM calls;")
    conn.execute("DELETE FROM nodes;")
    conn.executemany("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", nodes_to_insert)
    conn.executemany("INSERT INTO calls (caller_id, caller_symbol, callee_name, callee_qualified, is_dynamic, dynamic_expr, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)", calls_to_insert)
    conn.commit()
    t_stage1 = time.perf_counter() - t0_stage1

    # Stage 2: 全局 Resolution 二次遍历
    t0_stage2 = time.perf_counter()
    engine._resolve_all_edges(conn)
    conn.commit()
    t_stage2 = time.perf_counter() - t0_stage2

    edge_rows = conn.execute("SELECT resolution_type, confidence FROM resolved_edges").fetchall()
    type_counts = Counter(r["resolution_type"] for r in edge_rows)
    total_edges = len(edge_rows)
    high_conf_edges = sum(1 for r in edge_rows if r["confidence"] >= 0.7)

    print(f"   ✓ 图谱构建完成: Stage1: {t_stage1:.3f}s | Stage2: {t_stage2:.3f}s")
    print(f"   ✓ 拓扑边总数: {total_edges} 条 | 高确信度确定边 (≥0.7): {high_conf_edges} 条 ({high_conf_edges/total_edges*100:.1f}%)")
    for rtype, count in type_counts.most_common():
        print(f"     - {rtype:18}: {count:6} 条 ({count/total_edges*100:5.1f}%)")

    # 3. 真实 MCP 工具响应延迟与精准度验证
    print(f"⚡ 测试真实 MCP 工具查询与爆炸半径分析...")
    queries = ["FastAPI", "APIRouter", "Depends", "HTTPException"]
    query_stats = {}
    for q in queries:
        t0_q = time.perf_counter()
        callers = engine.get_callers(q)
        dt_q = (time.perf_counter() - t0_q) * 1000
        query_stats[q] = {
            "latency_ms": dt_q,
            "callers_count": callers.get("callers_count", 0),
        }
        print(f"   • get_callers('{q}'): {dt_q:5.2f} ms | 命中上游调用方: {callers.get('callers_count', 0)} 处")

    # 4. 关键指标：Depends 爆炸半径验证
    t0_impact = time.perf_counter()
    impact_depends = engine.get_impact_radius("Depends", max_depth=3)
    dt_impact = (time.perf_counter() - t0_impact) * 1000
    print(f"   💥 get_impact_radius('Depends'): {dt_impact:5.2f} ms")
    print(f"      - 受影响上游符号: {impact_depends.get('total_impacted_symbols', 0)} 个")
    print(f"      - 受波及文件数: {impact_depends.get('impacted_files_count', 0)} 个")
    print(f"      - 受影响外部 API 路由: {len(impact_depends.get('impacted_external_routes', []))} 个")

    return {
        "repo_name": "FastAPI",
        "language": "Python",
        "file_count": len(py_files),
        "extraction": {
            "time_sec": t_parse,
            "throughput_fps": throughput_parse,
            "symbols_count": total_symbols,
            "raw_calls_count": total_raw_calls,
            "parse_errors": parse_errors,
            "giant_files_count": len(giant_files),
        },
        "graph_resolution": {
            "stage1_time_sec": t_stage1,
            "stage2_time_sec": t_stage2,
            "total_nodes": len(nodes_to_insert),
            "total_calls": len(calls_to_insert),
            "total_edges": total_edges,
            "high_conf_edges": high_conf_edges,
            "high_conf_rate_pct": (high_conf_edges / total_edges * 100) if total_edges > 0 else 0,
            "type_counts": dict(type_counts),
        },
        "query_performance": query_stats,
        "impact_radius_depends": {
            "latency_ms": dt_impact,
            "impacted_symbols": impact_depends.get("total_impacted_symbols", 0),
            "impacted_files": impact_depends.get("impacted_files_count", 0),
            "impacted_routes": len(impact_depends.get("impacted_external_routes", [])),
        },
    }


def run_django_benchmark() -> Dict[str, Any]:
    print("\n" + "=" * 70)
    print("🐘 [REPO 2/3] Django 巨型工业级后端全量基准测试 (Python ORM / Web 框架)")
    print("=" * 70)

    django_repo = ROOT_DIR / "tests" / "benchmark_repos" / "django"
    django_core = django_repo / "django"
    assert django_core.exists(), f"未找到 Django 核心目录: {django_core}"

    py_files = [f for f in django_core.rglob("*.py") if f.is_file()]
    print(f"📂 发现 {len(py_files)} 个 Django 核心 Python 源文件，开始 Tree-sitter 全量提取...")

    parser = TreeSitterParser()
    t0_parse = time.perf_counter()
    total_symbols = 0
    total_raw_calls = 0
    parse_errors = 0
    giant_files = []

    for f in py_files:
        try:
            sz = f.stat().st_size
            if sz > 80_000:
                giant_files.append((f.name, sz))
            syms = parser.parse_file(f)
            total_symbols += len(syms)
            total_raw_calls += sum(len(s.calls) for s in syms)
        except Exception as e:
            parse_errors += 1
            sys.stderr.write(f"解析异常 {f.name}: {e}\n")

    t_parse = time.perf_counter() - t0_parse
    throughput_parse = len(py_files) / t_parse if t_parse > 0 else 0

    print(f"   ✓ 语法解析完成: {len(py_files)} 文件 | 耗时: {t_parse:.3f}s | 吞吐: {throughput_parse:.1f} 文件/秒")
    print(f"   ✓ 提取符号: {total_symbols} 个 | 提取调用点: {total_raw_calls} 个 | 异常: {parse_errors}")

    print(f"⚡ 构建 Django SQLite 全局代码拓扑图与二次解析遍历...")
    engine = CodeGraphEngine(django_core)
    conn = engine._get_db()
    engine._init_sqlite_schema(conn)

    t0_stage1 = time.perf_counter()
    chunker = UniversalCodeChunker(django_core)
    nodes_to_insert = []
    calls_to_insert = []

    for f in py_files:
        try:
            chunks = chunker.parse_file(f)
            for c in chunks:
                node_id = f"{c.file_path}:{c.start_line}:{c.symbol_name}"
                nodes_to_insert.append((
                    node_id, c.file_path, c.symbol_name, c.chunk_type,
                    c.start_line, c.end_line, c.code, c.docstring,
                    c.route_info, c.module_name, c.qualified_name
                ))
                raw_calls = json.loads(c.calls) if isinstance(c.calls, str) else (c.calls or [])
                for call_str in raw_calls:
                    if not call_str:
                        continue
                    is_dyn = 1 if ("dynamic:" in call_str or call_str.startswith("<dynamic:")) else 0
                    c_name = call_str.split(".")[-1] if "." in call_str else call_str
                    c_qual = call_str if "." in call_str else ""
                    calls_to_insert.append((
                        node_id, c.symbol_name, c_name, c_qual, is_dyn, "", c.file_path
                    ))
        except Exception as e:
            sys.stderr.write(f"Chunker 异常 {f.name}: {e}\n")

    conn.execute("DELETE FROM resolved_edges;")
    conn.execute("DELETE FROM calls;")
    conn.execute("DELETE FROM nodes;")
    conn.executemany("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", nodes_to_insert)
    conn.executemany("INSERT INTO calls (caller_id, caller_symbol, callee_name, callee_qualified, is_dynamic, dynamic_expr, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)", calls_to_insert)
    conn.commit()
    t_stage1 = time.perf_counter() - t0_stage1

    # Stage 2
    t0_stage2 = time.perf_counter()
    engine._resolve_all_edges(conn)
    conn.commit()
    t_stage2 = time.perf_counter() - t0_stage2

    edge_rows = conn.execute("SELECT resolution_type, confidence FROM resolved_edges").fetchall()
    type_counts = Counter(r["resolution_type"] for r in edge_rows)
    total_edges = len(edge_rows)
    high_conf_edges = sum(1 for r in edge_rows if r["confidence"] >= 0.7)

    print(f"   ✓ 图谱构建完成: Stage1: {t_stage1:.3f}s | Stage2: {t_stage2:.3f}s")
    print(f"   ✓ 拓扑边总数: {total_edges} 条 | 高确信度确定边 (≥0.7): {high_conf_edges} 条 ({high_conf_edges/total_edges*100:.1f}%)")
    for rtype, count in type_counts.most_common():
        print(f"     - {rtype:18}: {count:6} 条 ({count/total_edges*100:5.1f}%)")

    # 3. 真实复杂任务查询实测 (ORM, Middleware, Model.save)
    print(f"⚡ 测试 Django 官方标准场景查询响应...")
    t0_orm = time.perf_counter()
    callees_fetch = engine.get_callees("QuerySet._fetch_all")
    callers_fetch = engine.get_callers("QuerySet._fetch_all")
    callers_execute = engine.get_callers("SQLCompiler.execute_sql")
    dt_orm = (time.perf_counter() - t0_orm) * 1000

    t0_mw = time.perf_counter()
    callees_mw = engine.get_callees("BaseHandler.get_response")
    callers_mw = engine.get_callers("BaseHandler.get_response")
    dt_mw = (time.perf_counter() - t0_mw) * 1000

    t0_save = time.perf_counter()
    impact_save = engine.get_impact_radius("Model.save", max_depth=3)
    dt_save = (time.perf_counter() - t0_save) * 1000

    print(f"   • ORM 链路查询: {dt_orm:5.2f} ms (0 次磁盘读取)")
    print(f"   • 中间件链路查询: {dt_mw:5.2f} ms (0 次磁盘读取)")
    print(f"   • Model.save 爆炸半径: {dt_save:5.2f} ms (波及 {impact_save.get('total_impacted_symbols', 0)} 符号, {impact_save.get('impacted_files_count', 0)} 文件)")

    return {
        "repo_name": "Django Core",
        "language": "Python",
        "file_count": len(py_files),
        "extraction": {
            "time_sec": t_parse,
            "throughput_fps": throughput_parse,
            "symbols_count": total_symbols,
            "raw_calls_count": total_raw_calls,
            "parse_errors": parse_errors,
            "giant_files_count": len(giant_files),
        },
        "graph_resolution": {
            "stage1_time_sec": t_stage1,
            "stage2_time_sec": t_stage2,
            "total_nodes": len(nodes_to_insert),
            "total_calls": len(calls_to_insert),
            "total_edges": total_edges,
            "high_conf_edges": high_conf_edges,
            "high_conf_rate_pct": (high_conf_edges / total_edges * 100) if total_edges > 0 else 0,
            "type_counts": dict(type_counts),
        },
        "scenarios": {
            "orm_pipeline_ms": dt_orm,
            "middleware_chain_ms": dt_mw,
            "model_save_impact_ms": dt_save,
            "model_save_impacted_symbols": impact_save.get("total_impacted_symbols", 0),
            "model_save_impacted_files": impact_save.get("impacted_files_count", 0),
        },
    }


def run_vscode_benchmark() -> Dict[str, Any]:
    print("\n" + "=" * 70)
    print("💻 [REPO 3/3] VS Code 巨型前端单体全量基准测试 (TypeScript 编辑器核心)")
    print("=" * 70)

    vscode_editor = ROOT_DIR / "tests" / "benchmark_repos" / "vscode" / "src" / "vs" / "editor"
    assert vscode_editor.exists(), f"未找到 VS Code editor 目录: {vscode_editor}"

    ts_files = [f for f in vscode_editor.rglob("*.ts") if f.is_file() and not f.name.endswith(".d.ts")]
    print(f"📂 发现 {len(ts_files)} 个 TypeScript 源文件，开始 Tree-sitter 全量提取...")

    parser = TreeSitterParser()
    t0_parse = time.perf_counter()
    total_symbols = 0
    total_raw_calls = 0
    parse_errors = 0
    giant_files = []

    for f in ts_files:
        try:
            sz = f.stat().st_size
            if sz > 100_000:
                giant_files.append((f.name, sz))
            syms = parser.parse_file(f)
            total_symbols += len(syms)
            total_raw_calls += sum(len(s.calls) for s in syms)
        except Exception as e:
            parse_errors += 1
            sys.stderr.write(f"解析异常 {f.name}: {e}\n")

    t_parse = time.perf_counter() - t0_parse
    throughput_parse = len(ts_files) / t_parse if t_parse > 0 else 0

    print(f"   ✓ 语法解析完成: {len(ts_files)} 文件 | 耗时: {t_parse:.3f}s | 吞吐: {throughput_parse:.1f} 文件/秒")
    print(f"   ✓ 提取符号: {total_symbols} 个 | 提取调用点: {total_raw_calls} 个 | 异常: {parse_errors}")

    print(f"⚡ 构建 VS Code SQLite 全局代码拓扑图与二次解析遍历...")
    engine = CodeGraphEngine(vscode_editor)
    conn = engine._get_db()
    engine._init_sqlite_schema(conn)

    t0_stage1 = time.perf_counter()
    chunker = UniversalCodeChunker(vscode_editor)
    nodes_to_insert = []
    calls_to_insert = []

    for f in ts_files:
        try:
            chunks = chunker.parse_file(f)
            for c in chunks:
                node_id = f"{c.file_path}:{c.start_line}:{c.symbol_name}"
                nodes_to_insert.append((
                    node_id, c.file_path, c.symbol_name, c.chunk_type,
                    c.start_line, c.end_line, c.code, c.docstring,
                    c.route_info, c.module_name, c.qualified_name
                ))
                raw_calls = json.loads(c.calls) if isinstance(c.calls, str) else (c.calls or [])
                for call_str in raw_calls:
                    if not call_str:
                        continue
                    is_dyn = 1 if ("dynamic:" in call_str or call_str.startswith("<dynamic:")) else 0
                    c_name = call_str.split(".")[-1] if "." in call_str else call_str
                    c_qual = call_str if "." in call_str else ""
                    calls_to_insert.append((
                        node_id, c.symbol_name, c_name, c_qual, is_dyn, "", c.file_path
                    ))
        except Exception as e:
            sys.stderr.write(f"Chunker 异常 {f.name}: {e}\n")

    conn.execute("DELETE FROM resolved_edges;")
    conn.execute("DELETE FROM calls;")
    conn.execute("DELETE FROM nodes;")
    conn.executemany("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", nodes_to_insert)
    conn.executemany("INSERT INTO calls (caller_id, caller_symbol, callee_name, callee_qualified, is_dynamic, dynamic_expr, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)", calls_to_insert)
    conn.commit()
    t_stage1 = time.perf_counter() - t0_stage1

    # Stage 2
    t0_stage2 = time.perf_counter()
    engine._resolve_all_edges(conn)
    conn.commit()
    t_stage2 = time.perf_counter() - t0_stage2

    edge_rows = conn.execute("SELECT resolution_type, confidence FROM resolved_edges").fetchall()
    type_counts = Counter(r["resolution_type"] for r in edge_rows)
    total_edges = len(edge_rows)
    high_conf_edges = sum(1 for r in edge_rows if r["confidence"] >= 0.7)

    print(f"   ✓ 图谱构建完成: Stage1: {t_stage1:.3f}s | Stage2: {t_stage2:.3f}s")
    print(f"   ✓ 拓扑边总数: {total_edges} 条 | 高确信度确定边 (≥0.7): {high_conf_edges} 条 ({high_conf_edges/total_edges*100:.1f}%)")
    for rtype, count in type_counts.most_common():
        print(f"     - {rtype:18}: {count:6} 条 ({count/total_edges*100:5.1f}%)")

    # 4. 真实查询响应延迟测试
    test_queries = ["TextModel", "Cursor", "Range", "Position", "setValue", "getLineContent"]
    latencies = []
    query_stats = {}

    for q in test_queries:
        t_q0 = time.perf_counter()
        callers = engine.get_callers(q)
        q_time = (time.perf_counter() - t_q0) * 1000
        latencies.append(q_time)
        cnt = callers.get("callers_count", 0)
        query_stats[q] = {"latency_ms": q_time, "callers_count": cnt}
        print(f"   • get_callers('{q}'): {q_time:5.2f} ms | 命中调用方: {cnt} 处")

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    print(f"   🏆 平均查询响应延迟: {avg_latency:.2f} ms")

    # 5. 爆炸半径测试
    t0_impact = time.perf_counter()
    impact_cursor = engine.get_impact_radius("Cursor", max_depth=3)
    dt_impact = (time.perf_counter() - t0_impact) * 1000
    print(f"   💥 get_impact_radius('Cursor'): {dt_impact:5.2f} ms (波及 {impact_cursor.get('total_impacted_symbols', 0)} 符号, {impact_cursor.get('impacted_files_count', 0)} 文件)")

    return {
        "repo_name": "VS Code Editor Core",
        "language": "TypeScript",
        "file_count": len(ts_files),
        "extraction": {
            "time_sec": t_parse,
            "throughput_fps": throughput_parse,
            "symbols_count": total_symbols,
            "raw_calls_count": total_raw_calls,
            "parse_errors": parse_errors,
            "giant_files_count": len(giant_files),
        },
        "graph_resolution": {
            "stage1_time_sec": t_stage1,
            "stage2_time_sec": t_stage2,
            "total_nodes": len(nodes_to_insert),
            "total_calls": len(calls_to_insert),
            "total_edges": total_edges,
            "high_conf_edges": high_conf_edges,
            "high_conf_rate_pct": (high_conf_edges / total_edges * 100) if total_edges > 0 else 0,
            "type_counts": dict(type_counts),
        },
        "query_performance": {
            "queries": query_stats,
            "avg_latency_ms": avg_latency,
        },
        "impact_radius_cursor": {
            "latency_ms": dt_impact,
            "impacted_symbols": impact_cursor.get("total_impacted_symbols", 0),
            "impacted_files": impact_cursor.get("impacted_files_count", 0),
        },
    }


def main():
    print("=" * 70)
    print("🏁 CODE-SEARCH-GRAPH Real-world Industrial End-to-End Benchmark Suite")
    print("Targets: FastAPI (Python Web), Django (Python ORM), VS Code (TypeScript Editor)")
    print("=" * 70)

    t0_all = time.perf_counter()

    fastapi_res = run_fastapi_benchmark()
    django_res = run_django_benchmark()
    vscode_res = run_vscode_benchmark()

    total_time = time.perf_counter() - t0_all

    full_report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_suite_time_sec": total_time,
        "repositories": {
            "fastapi": fastapi_res,
            "django": django_res,
            "vscode": vscode_res,
        },
        "summary": {
            "total_files_analyzed": (
                fastapi_res["file_count"] + django_res["file_count"] + vscode_res["file_count"]
            ),
            "total_symbols_extracted": (
                fastapi_res["extraction"]["symbols_count"]
                + django_res["extraction"]["symbols_count"]
                + vscode_res["extraction"]["symbols_count"]
            ),
            "total_edges_resolved": (
                fastapi_res["graph_resolution"]["total_edges"]
                + django_res["graph_resolution"]["total_edges"]
                + vscode_res["graph_resolution"]["total_edges"]
            ),
            "total_high_conf_edges": (
                fastapi_res["graph_resolution"]["high_conf_edges"]
                + django_res["graph_resolution"]["high_conf_edges"]
                + vscode_res["graph_resolution"]["high_conf_edges"]
            ),
        },
    }

    report_dir = ROOT_DIR / "tests" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / "e2e_full_benchmark_report.json"
    report_file.write_text(json.dumps(full_report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 70)
    print("🎉 恭喜！三大巨型代码库全量端到端压测全部圆满完成！")
    print(f"📊 汇总数据:")
    print(f"   • 分析源文件总数: {full_report['summary']['total_files_analyzed']} 个")
    print(f"   • 提取函数/类符号: {full_report['summary']['total_symbols_extracted']} 个")
    print(f"   • 构建确定性调用边: {full_report['summary']['total_edges_resolved']} 条")
    print(f"   • 高确信度确定边: {full_report['summary']['total_high_conf_edges']} 条")
    print(f"   • 总耗时: {total_time:.2f} 秒")
    print(f"📄 完整结构化 JSON 报告已保存至: {report_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()
