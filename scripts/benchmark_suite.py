"""Comprehensive Performance & Benchmark Suite for code-search-graph.
Evaluates all 10 core subsystems:
1. CLI Cold Startup & Module Import Overhead
2. Embedded Ripgrep Exact & Regex Search Engine
3. Multi-language Architecture Outline Generation
4. Repository Indexing Pipeline (AST Parallel Parsing, Embedding, DB Persistence)
5. SQLite Call Graph Queries (Cold vs Cached Latency: callers, callees, impact, BFS trace)
6. SQLite Native FTS5 BM25 Keyword Search
7. 4-Way Hybrid Semantic Search (RRF Fusion Channels Breakdown)
8. Surgical Feature Exploration (explore_codebase)
9. Incremental File Indexing & Live Sync (Add, Modify, Delete)
10. Memory Footprint & Peak RAM Profile
"""

import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import psutil

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
SAMPLE_REPO = ROOT_DIR / "tests" / "sample_project"


def time_callable(func: Callable[[], Any], iterations: int = 5) -> Tuple[float, float, float, Any]:
    """Execute a callable multiple times and return (min_ms, mean_ms, max_ms, last_result)"""
    times = []
    res = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = func()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return min(times), sum(times) / len(times), max(times), res


def time_subprocess(cmd: List[str], iterations: int = 3) -> Tuple[float, float, float, str]:
    """Execute a command in an isolated subprocess and return elapsed time in ms"""
    times = []
    out = ""
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
        out = res.stdout
    return min(times), sum(times) / len(times), max(times), out


def measure_import_time(mod_name: str) -> float:
    """Measure true cold import time of a module in a fresh Python process"""
    cmd = [
        sys.executable,
        "-c",
        f"import time; t0 = time.perf_counter(); import {mod_name}; t1 = time.perf_counter(); print((t1 - t0) * 1000.0)",
    ]
    res = subprocess.run(
        cmd,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def run_full_benchmark() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": f"{sys.platform} ({os.name})",
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count() or 4,
        "results": {},
    }

    print("=" * 75)
    print("🚀 code-search-graph Comprehensive Benchmark Suite")
    print(f"Platform: {report['platform']} • Python: {report['python_version']} • CPU Cores: {report['cpu_count']}")
    print("=" * 75)

    # -------------------------------------------------------------------------
    # 1. CLI Cold Startup & Module Import Overhead
    # -------------------------------------------------------------------------
    print("\n[1/10] Benchmarking CLI Startup & Module Import Overhead...")
    cli_bench = {}

    for subcmd, label in [
        (["--help"], "CLI Root --help"),
        (["--version"], "CLI --version"),
        (["exact", "--help"], "Subcommand 'exact --help'"),
        (["callers", "--help"], "Subcommand 'callers --help'"),
        (["search", "--help"], "Subcommand 'search --help'"),
        (["outline", "--help"], "Subcommand 'outline --help'"),
    ]:
        cmd = [sys.executable, "-m", "code_search_mcp.cli"] + subcmd
        min_t, mean_t, max_t, _ = time_subprocess(cmd, iterations=3)
        cli_bench[label] = {"min_ms": round(min_t, 2), "mean_ms": round(mean_t, 2), "max_ms": round(max_t, 2)}
        print(f"  • {label:30}: {mean_t:6.2f} ms (min: {min_t:6.2f} ms)")

    import_bench = {}
    modules_to_test = [
        ("code_search_mcp", "code_search_mcp (Root Package)"),
        ("code_search_mcp.config", "config"),
        ("code_search_mcp.ripgrep_engine", "ripgrep_engine"),
        ("code_search_mcp.outline", "outline"),
        ("code_search_mcp.graph_engine", "graph_engine"),
        ("code_search_mcp.searcher", "searcher"),
        ("code_search_mcp.indexer", "indexer"),
        ("code_search_mcp.embeddings", "embeddings"),
        ("fastembed", "fastembed (External Heavy)"),
        ("onnxruntime", "onnxruntime (External Heavy)"),
        ("lancedb", "lancedb (External Heavy)"),
        ("pyarrow", "pyarrow (External Heavy)"),
    ]
    for mod, label in modules_to_test:
        dur = measure_import_time(mod)
        import_bench[label] = round(dur, 2)
        print(f"  • Import {label:32}: {dur:6.2f} ms")

    report["results"]["cli_startup"] = cli_bench
    report["results"]["import_times"] = import_bench

    # -------------------------------------------------------------------------
    # 2. Embedded Ripgrep Exact & Regex Engine
    # -------------------------------------------------------------------------
    print("\n[2/10] Benchmarking Embedded Ripgrep Exact & Regex Engine...")
    from code_search_mcp.ripgrep_engine import ExactSearchEngine

    rg_engine = ExactSearchEngine(SAMPLE_REPO)
    rg_bench = {}

    queries = [
        ("Literal Exact: 'verify_password'", "verify_password", False, False),
        ("Literal Exact: 'AuthService'", "AuthService", False, False),
        ("Case-Insensitive: 'passwordhasher'", "passwordhasher", False, False),
        ("Regex: 'def [a-zA-Z0-9_]+_token'", r"def [a-zA-Z0-9_]+_token", True, False),
        ("Regex: 'class\\s+[A-Z][a-zA-Z0-9_]+'", r"class\s+[A-Z][a-zA-Z0-9_]+", True, False),
    ]

    for label, pat, is_reg, is_case in queries:
        min_t, mean_t, max_t, res = time_callable(
            lambda: rg_engine.search(pat, is_regex=is_reg, case_sensitive=is_case, max_results=50),
            iterations=10,
        )
        hits = len(res.get("matches", []))
        rg_bench[label] = {
            "mean_ms": round(mean_t, 3),
            "min_ms": round(min_t, 3),
            "max_ms": round(max_t, 3),
            "matches": hits,
        }
        print(f"  • {label:40}: {mean_t:6.3f} ms (matches: {hits})")

    report["results"]["ripgrep_engine"] = rg_bench

    # -------------------------------------------------------------------------
    # 3. Multi-Language Architecture Outline Generation
    # -------------------------------------------------------------------------
    print("\n[3/10] Benchmarking Architecture Outline Generator...")
    from code_search_mcp.outline import ProjectOutlineGenerator

    outline_gen = ProjectOutlineGenerator(SAMPLE_REPO)
    min_t, mean_t, max_t, out_res = time_callable(lambda: outline_gen.generate(), iterations=5)
    files_analyzed = len(out_res.get("files", []))
    symbols_extracted = sum(len(f.get("classes", [])) + len(f.get("functions", [])) for f in out_res.get("files", []))
    report["results"]["outline_generator"] = {
        "mean_ms": round(mean_t, 2),
        "min_ms": round(min_t, 2),
        "files_analyzed": files_analyzed,
        "symbols_extracted": symbols_extracted,
    }
    print(f"  • Outline Multi-Language AST Map: {mean_t:6.2f} ms ({files_analyzed} files, {symbols_extracted} structural symbols)")

    # -------------------------------------------------------------------------
    # 4. Codebase Indexing Pipeline (AST Parallel Parsing vs Serial & Embedding)
    # -------------------------------------------------------------------------
    print("\n[4/10] Benchmarking Repository Indexing Pipeline...")
    from code_search_mcp.indexer import CodeIndexer, UniversalCodeChunker

    # Compare Serial vs Multi-threaded AST parsing
    files = [p for p in SAMPLE_REPO.rglob("*") if p.is_file() and p.suffix in (".py", ".ts", ".vue", ".java", ".go", ".rs")]

    def run_serial_parse():
        chunker = UniversalCodeChunker(SAMPLE_REPO)
        chunks = []
        for f in files:
            chunks.extend(chunker.parse_file(f))
        return chunks

    import threading
    from concurrent.futures import ThreadPoolExecutor

    tl = threading.local()

    def parse_worker(f):
        if not hasattr(tl, "chunker"):
            tl.chunker = UniversalCodeChunker(SAMPLE_REPO)
        return tl.chunker.parse_file(f)

    def run_parallel_parse():
        chunks = []
        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as ex:
            for chs in ex.map(parse_worker, files):
                chunks.extend(chs)
        return chunks

    s_min, s_mean, s_max, s_chunks = time_callable(run_serial_parse, iterations=5)
    p_min, p_mean, p_max, p_chunks = time_callable(run_parallel_parse, iterations=5)
    speedup = s_mean / p_mean if p_mean > 0 else 1.0

    print(f"  • Serial AST Parsing          : {s_mean:6.2f} ms ({len(s_chunks)} chunks)")
    print(f"  • Parallel AST Parsing (4 Thr): {p_mean:6.2f} ms (Speedup: {speedup:.2f}x)")

    # Full End-to-End Indexing
    indexer = CodeIndexer(SAMPLE_REPO)
    proc = psutil.Process()
    mem_before = proc.memory_info().rss / (1024 * 1024)

    t0_idx = time.perf_counter()
    index_res = indexer.index_all()
    t1_idx = time.perf_counter()
    idx_total_ms = (t1_idx - t0_idx) * 1000.0

    mem_after = proc.memory_info().rss / (1024 * 1024)
    mem_delta = mem_after - mem_before

    files_cnt = index_res.get("indexed_files", len(files))
    chunks_cnt = index_res.get("indexed_chunks", len(s_chunks))
    throughput_chunks = chunks_cnt / ((t1_idx - t0_idx) or 0.001)

    report["results"]["indexing_pipeline"] = {
        "serial_ast_ms": round(s_mean, 2),
        "parallel_ast_ms": round(p_mean, 2),
        "ast_speedup": round(speedup, 2),
        "full_indexing_ms": round(idx_total_ms, 2),
        "files_indexed": files_cnt,
        "chunks_indexed": chunks_cnt,
        "throughput_chunks_sec": round(throughput_chunks, 1),
        "process_ram_mb": round(mem_after, 2),
    }
    print(f"  • Full Indexing & Vectorization: {idx_total_ms:6.2f} ms ({throughput_chunks:.1f} chunks/sec, RAM: {mem_after:.1f} MB)")

    # -------------------------------------------------------------------------
    # 5. SQLite Call Graph Engine (Cold vs Cached Latency)
    # -------------------------------------------------------------------------
    print("\n[5/10] Benchmarking SQLite Call Graph Engine (Cold vs Cached)...")
    from code_search_mcp.graph_engine import CodeGraphEngine

    graph = CodeGraphEngine.get_instance(SAMPLE_REPO)
    graph.load()
    graph_bench = {}

    graph_operations = [
        ("get_callers: 'verify_password'", lambda: graph.get_callers("verify_password"), "verify_password"),
        ("get_callers: 'hash_password'", lambda: graph.get_callers("hash_password"), "hash_password"),
        ("get_callees: 'AuthService.login'", lambda: graph.get_callees("AuthService.login"), "AuthService.login"),
        ("get_impact_radius: 'verify_password' (d=3)", lambda: graph.get_impact_radius("verify_password", max_depth=3), "verify_password:3"),
        ("get_impact_radius: 'hash_password' (d=3)", lambda: graph.get_impact_radius("hash_password", max_depth=3), "hash_password:3"),
        ("build_call_tree: 'AuthService' (d=3)", lambda: graph.build_call_tree("AuthService", max_depth=3), "AuthService:3"),
    ]

    for label, op, cache_key in graph_operations:
        # Clear specific cache key to test Cold
        graph._clear_query_cache()
        t0 = time.perf_counter()
        cold_res = op()
        t1 = time.perf_counter()
        cold_ms = (t1 - t0) * 1000.0

        # Now measure Cached execution (10 runs)
        c_min, c_mean, c_max, cached_res = time_callable(op, iterations=10)
        cache_speedup = cold_ms / c_mean if c_mean > 0 else 1.0

        graph_bench[label] = {
            "cold_ms": round(cold_ms, 2),
            "cached_mean_ms": round(c_mean, 3),
            "cached_min_ms": round(c_min, 3),
            "speedup": round(cache_speedup, 1),
        }
        print(f"  • {label:42}: Cold: {cold_ms:6.2f} ms | Cached: {c_mean:5.3f} ms ({cache_speedup:6.1f}x faster)")

    report["results"]["graph_engine"] = graph_bench

    # -------------------------------------------------------------------------
    # 6. SQLite Native FTS5 BM25 Keyword Search
    # -------------------------------------------------------------------------
    print("\n[6/10] Benchmarking SQLite Native FTS5 BM25 Search...")
    fts_bench = {}
    fts_queries = [
        "verify_password",
        "hash_password sha256",
        "user authentication login token",
        "password hasher salt",
        "user service spring controller",
    ]

    for q in fts_queries:
        min_t, mean_t, max_t, res = time_callable(lambda: graph.search_fts(q, top_k=5), iterations=10)
        hits = len(res)
        top1 = res[0]["symbol_name"] if res else "None"
        fts_bench[q] = {"mean_ms": round(mean_t, 3), "min_ms": round(min_t, 3), "hits": hits, "top1": top1}
        print(f"  • FTS5 BM25 '{q:30}': {mean_t:6.3f} ms (hits: {hits}, Top-1: {top1})")

    report["results"]["fts5_bm25"] = fts_bench

    # -------------------------------------------------------------------------
    # 7. 4-Way Hybrid Semantic Search (RRF Channels Breakdown)
    # -------------------------------------------------------------------------
    print("\n[7/10] Benchmarking 4-Way Hybrid Semantic Search & RRF...")
    from code_search_mcp.searcher import CodeSearcher

    searcher = CodeSearcher(SAMPLE_REPO)
    search_bench = {}

    search_queries = [
        "user login password verification",
        "hash password with sha256",
        "session token management",
        "user controller endpoint",
        "save user to database",
    ]

    for q in search_queries:
        min_t, mean_t, max_t, s_res = time_callable(lambda: searcher.search(q, top_k=5), iterations=5)
        top1 = f"{s_res[0]['symbol_name']} ({s_res[0]['file_path']})" if s_res else "None"
        top1_sim = s_res[0]["similarity"] if s_res else 0.0
        search_bench[q] = {
            "mean_ms": round(mean_t, 2),
            "min_ms": round(min_t, 2),
            "hits": len(s_res),
            "top1": top1,
            "top1_score": top1_sim,
        }
        print(f"  • Search '{q:32}': {mean_t:6.2f} ms | Top-1: {top1} (sim: {top1_sim})")

    report["results"]["hybrid_search"] = search_bench

    # -------------------------------------------------------------------------
    # 8. Surgical Feature Exploration (explore_feature)
    # -------------------------------------------------------------------------
    print("\n[8/10] Benchmarking Surgical Feature Exploration (explore_feature)...")
    explore_queries = [
        "user login and password verification flow",
        "password hashing with sha256",
    ]
    explore_bench = {}
    for eq in explore_queries:
        graph._clear_query_cache()
        t0 = time.perf_counter()
        cold_exp = graph.explore_feature(eq, top_k=2, max_depth=3)
        t1 = time.perf_counter()
        cold_ms = (t1 - t0) * 1000.0

        min_t, mean_t, max_t, warm_exp = time_callable(lambda: graph.explore_feature(eq, top_k=2, max_depth=3), iterations=5)
        routes_found = len(warm_exp.get("entry_routes", []))
        impl_symbols = len(warm_exp.get("core_implementations", []))
        explore_bench[eq] = {
            "cold_ms": round(cold_ms, 2),
            "warm_ms": round(mean_t, 2),
            "routes": routes_found,
            "core_impls": impl_symbols,
        }
        print(f"  • Explore '{eq:40}': Cold: {cold_ms:6.2f} ms | Warm: {mean_t:6.2f} ms (routes: {routes_found}, impls: {impl_symbols})")

    report["results"]["feature_exploration"] = explore_bench

    # -------------------------------------------------------------------------
    # 9. Incremental File Indexing (Add, Modify, Delete)
    # -------------------------------------------------------------------------
    print("\n[9/10] Benchmarking Incremental Indexing (Add, Modify, Delete)...")
    inc_bench = {}
    temp_test_file = SAMPLE_REPO / "temp_benchmark_coupon_service.py"

    try:
        # Step A: Add file
        add_code = (
            "def apply_coupon(order_id: str, coupon_code: str) -> float:\n"
            '    """Calculate coupon discount"""\n'
            '    if coupon_code == "VIP99":\n'
            "        return 99.0\n"
            "    return 0.0\n"
        )
        temp_test_file.write_text(add_code, encoding="utf-8")
        min_t, mean_t, max_t, res_add = time_callable(lambda: indexer.index_file_incremental(temp_test_file), iterations=1)
        inc_bench["incremental_add"] = {"latency_ms": round(mean_t, 2), "chunks": res_add.get("chunks_count", 0)}
        print(f"  • Incremental File Add   : {mean_t:6.2f} ms (chunks: {res_add.get('chunks_count', 0)})")

        # Step B: Modify file
        mod_code = (
            "def apply_coupon(order_id: str, coupon_code: str) -> float:\n"
            '    """Calculate updated coupon discount"""\n'
            "    return 50.0\n\n"
            "def validate_coupon(coupon_code: str) -> bool:\n"
            '    """Validate coupon expiration"""\n'
            "    return len(coupon_code) > 0\n"
        )
        temp_test_file.write_text(mod_code, encoding="utf-8")
        min_t, mean_t, max_t, res_mod = time_callable(lambda: indexer.index_file_incremental(temp_test_file), iterations=1)
        inc_bench["incremental_modify"] = {"latency_ms": round(mean_t, 2), "chunks": res_mod.get("chunks_count", 0)}
        print(f"  • Incremental File Modify: {mean_t:6.2f} ms (chunks: {res_mod.get('chunks_count', 0)})")

        # Step C: Delete file
        temp_test_file.unlink()
        min_t, mean_t, max_t, res_del = time_callable(lambda: indexer.index_file_incremental(temp_test_file), iterations=1)
        inc_bench["incremental_delete"] = {"latency_ms": round(mean_t, 2), "status": res_del.get("status")}
        print(f"  • Incremental File Delete: {mean_t:6.2f} ms (status: {res_del.get('status')})")

    finally:
        if temp_test_file.exists():
            temp_test_file.unlink()
            indexer.index_file_incremental(temp_test_file)

    report["results"]["incremental_sync"] = inc_bench

    # -------------------------------------------------------------------------
    # 10. Memory Footprint & Peak RAM Profile
    # -------------------------------------------------------------------------
    print("\n[10/10] Measuring Process Working Set & Memory Profile...")
    gc.collect()
    mem_info = proc.memory_info()
    mem_report = {
        "rss_mb": round(mem_info.rss / (1024 * 1024), 2),
        "vms_mb": round(mem_info.vms / (1024 * 1024), 2),
        "peak_wset_mb": round(getattr(mem_info, "peak_wset", mem_info.rss) / (1024 * 1024), 2),
    }
    report["results"]["memory_profile"] = mem_report
    print(f"  • Resident Set Size (RSS) : {mem_report['rss_mb']} MB")
    print(f"  • Peak Working Set (Peak): {mem_report['peak_wset_mb']} MB")
    print(f"  • Memory Invariant Check : {'PASSED (< 160MB)' if mem_report['rss_mb'] < 160 else 'WARNING'}")

    print("\n" + "=" * 75)
    print("✅ All 10 Subsystems Benchmarked Successfully!")
    print("=" * 75)

    # Save benchmark report json
    out_json = ROOT_DIR / "benchmark_results.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved to: {out_json}")
    return report


if __name__ == "__main__":
    run_full_benchmark()
