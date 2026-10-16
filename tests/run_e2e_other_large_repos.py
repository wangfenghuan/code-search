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


def run_repo_benchmark(repo_path: Path, repo_name: str, language: str, file_pattern: str, test_queries: List[str], impact_target: str) -> Dict[str, Any]:
    print("\n" + "=" * 70)
    print(f"🚀 [{repo_name}] 全量端到端基准测试 ({language})")
    print("=" * 70)

    # 1. 扫描源文件
    files = [
        f for f in repo_path.rglob(file_pattern)
        if f.is_file() and not any(part.startswith(".") for part in f.parts)
    ]
    print(f"📂 发现 {len(files)} 个 {language} 源文件，开始全量语法解析与符号切片...")

    # 2. 语法解析压测
    parser = TreeSitterParser()
    t0_parse = time.perf_counter()
    total_symbols = 0
    total_raw_calls = 0
    parse_errors = 0
    giant_files = []

    for f in files:
        try:
            sz = f.stat().st_size
            if sz > 50_000:
                giant_files.append((f.name, sz))
            syms = parser.parse_file(f)
            total_symbols += len(syms)
            total_raw_calls += sum(len(s.calls) for s in syms)
        except Exception as e:
            parse_errors += 1
            sys.stderr.write(f"解析异常 {f.name}: {e}\n")

    t_parse = time.perf_counter() - t0_parse
    throughput_parse = len(files) / t_parse if t_parse > 0 else 0

    print(f"   ✓ 语法解析完成: {len(files)} 文件 | 耗时: {t_parse:.3f}s | 吞吐: {throughput_parse:.1f} 文件/秒")
    print(f"   ✓ 提取符号: {total_symbols} 个 | 提取调用点: {total_raw_calls} 个 | 异常: {parse_errors} 个")

    # 3. 构建 SQLite 拓扑图与 Two-Phase Resolution
    print(f"⚡ 构建 {repo_name} SQLite 全局代码拓扑图与全局消歧解析...")
    engine = CodeGraphEngine(repo_path)
    conn = engine._get_db()
    engine._init_sqlite_schema(conn)

    t0_stage1 = time.perf_counter()
    chunker = UniversalCodeChunker(repo_path)
    nodes_to_insert = []
    calls_to_insert = []

    for f in files:
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

    # Stage 2: 全局消歧与边解析
    t0_stage2 = time.perf_counter()
    engine._resolve_all_edges(conn)
    conn.commit()
    t_stage2 = time.perf_counter() - t0_stage2

    edge_rows = conn.execute("SELECT resolution_type, confidence FROM resolved_edges").fetchall()
    type_counts = Counter(r["resolution_type"] for r in edge_rows)
    total_edges = len(edge_rows)
    high_conf_edges = sum(1 for r in edge_rows if r["confidence"] >= 0.7)

    print(f"   ✓ 图谱构建完成: Stage1: {t_stage1:.3f}s | Stage2: {t_stage2:.3f}s")
    print(f"   ✓ 拓扑边总数: {total_edges} 条 | 高确信度确定边 (≥0.7): {high_conf_edges} 条 ({(high_conf_edges/total_edges*100) if total_edges else 0:.1f}%)")
    for rtype, count in type_counts.most_common():
        print(f"     - {rtype:18}: {count:6} 条 ({(count/total_edges*100) if total_edges else 0:5.1f}%)")

    # 4. 真实查询响应实测
    print(f"⚡ 测试 {repo_name} 关键符号实时检索延迟...")
    query_stats = {}
    latencies = []
    for q in test_queries:
        t0_q = time.perf_counter()
        callers = engine.get_callers(q)
        dt_q = (time.perf_counter() - t0_q) * 1000
        latencies.append(dt_q)
        cnt = callers.get("callers_count", 0)
        query_stats[q] = {"latency_ms": dt_q, "callers_count": cnt}
        print(f"   • get_callers('{q}'): {dt_q:5.2f} ms | 命中上游调用方: {cnt} 处")

    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    # 5. 爆炸半径实测
    t0_imp = time.perf_counter()
    impact_res = engine.get_impact_radius(impact_target, max_depth=3)
    dt_imp = (time.perf_counter() - t0_imp) * 1000
    impact_syms = impact_res.get("total_impacted_symbols", 0)
    impact_files = impact_res.get("impacted_files_count", 0)
    impact_routes = len(impact_res.get("impacted_external_routes", []))
    print(f"   💥 get_impact_radius('{impact_target}'): {dt_imp:5.2f} ms")
    print(f"      - 受影响上游符号: {impact_syms} 个")
    print(f"      - 受波及文件数: {impact_files} 个")
    print(f"      - 涉及外部路由: {impact_routes} 个")

    return {
        "repo_name": repo_name,
        "language": language,
        "file_count": len(files),
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
        "impact_radius": {
            "target": impact_target,
            "latency_ms": dt_imp,
            "impacted_symbols": impact_syms,
            "impacted_files": impact_files,
            "impacted_routes": impact_routes,
        },
    }


def main():
    print("=" * 70)
    print("🏁 CODE-SEARCH-MCP 新一批大型工业级代码库全量端到端压测套件")
    print("涵盖生态: Gin (Go), Express (JavaScript), Flask (Python), Django Full Repo (2,933 Python files)")
    print("=" * 70)

    t0_suite = time.perf_counter()
    reports = {}

    # 1. Gin (Go, 78k stars)
    gin_dir = ROOT_DIR / "tests" / "benchmark_repos" / "gin"
    if gin_dir.exists():
        reports["gin"] = run_repo_benchmark(
            repo_path=gin_dir,
            repo_name="Gin Web Framework",
            language="Go",
            file_pattern="*.go",
            test_queries=["Engine", "Context", "RouterGroup", "Default"],
            impact_target="Context",
        )

    # 2. Express (JavaScript, 65k stars)
    express_dir = ROOT_DIR / "tests" / "benchmark_repos" / "express"
    if express_dir.exists():
        reports["express"] = run_repo_benchmark(
            repo_path=express_dir,
            repo_name="Express.js",
            language="JavaScript",
            file_pattern="*.js",
            test_queries=["createApplication", "Router", "handle", "use"],
            impact_target="createApplication",
        )

    # 3. Flask (Python, 67k stars)
    flask_dir = ROOT_DIR / "tests" / "benchmark_repos" / "flask"
    if flask_dir.exists():
        reports["flask"] = run_repo_benchmark(
            repo_path=flask_dir,
            repo_name="Flask",
            language="Python",
            file_pattern="*.py",
            test_queries=["Flask", "Blueprint", "current_app", "render_template"],
            impact_target="Blueprint",
        )

    # 4. Django Full Ecosystem (全部 2,933 个源文件，全量压测)
    django_full_dir = ROOT_DIR / "tests" / "benchmark_repos" / "django"
    if django_full_dir.exists():
        reports["django_full"] = run_repo_benchmark(
            repo_path=django_full_dir,
            repo_name="Django Full Ecosystem",
            language="Python",
            file_pattern="*.py",
            test_queries=["Model", "QuerySet", "ModelAdmin", "authenticate"],
            impact_target="Model",
        )

    t_suite = time.perf_counter() - t0_suite

    total_files = sum(r["file_count"] for r in reports.values())
    total_symbols = sum(r["extraction"]["symbols_count"] for r in reports.values())
    total_edges = sum(r["graph_resolution"]["total_edges"] for r in reports.values())
    total_high_conf = sum(r["graph_resolution"]["high_conf_edges"] for r in reports.values())

    full_output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_suite_time_sec": t_suite,
        "summary": {
            "total_repositories": len(reports),
            "total_files_analyzed": total_files,
            "total_symbols_extracted": total_symbols,
            "total_edges_resolved": total_edges,
            "total_high_conf_edges": total_high_conf,
            "overall_high_conf_pct": (total_high_conf / total_edges * 100) if total_edges else 0,
        },
        "repositories": reports,
    }

    report_dir = ROOT_DIR / "tests" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    out_file = report_dir / "e2e_other_large_repos_report.json"
    out_file.write_text(json.dumps(full_output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 70)
    print("🎉 新一批大型代码库全量端到端压测圆满完成！")
    print(f"📊 汇总数据:")
    print(f"   • 涉及代码库: {len(reports)} 个 (Gin, Express, Flask, Django 全量)")
    print(f"   • 分析源文件总数: {total_files} 个")
    print(f"   • 提取函数/类符号: {total_symbols} 个")
    print(f"   • 构建确定性调用边: {total_edges} 条")
    print(f"   • 高确信度确定边 (≥0.7): {total_high_conf} 条 ({(total_high_conf/total_edges*100) if total_edges else 0:.1f}%)")
    print(f"   • 压测总耗时: {t_suite:.2f} 秒")
    print(f"📄 报告已保存至: {out_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()
