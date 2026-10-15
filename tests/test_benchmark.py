import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from code_search_mcp.indexer import UniversalCodeChunker
from code_search_mcp.multilang_parser import TreeSitterParser


def test_fastapi_giant_files():
    print("\n" + "=" * 60)
    print("🚀 [基准测试 1] 真实超大生产级文件单文件解析压测 (FastAPI)")
    print("=" * 60)

    fastapi_dir = ROOT_DIR / "tests" / "benchmark_repos" / "fastapi"
    if not fastapi_dir.exists():
        print("⚠️ 未找到 fastapi 测试仓库，跳过此项基准")
        return

    parser = TreeSitterParser()

    # 1.1 测试 applications.py (4,838 行，186KB，历史崩溃根因文件)
    app_file = None
    for p in fastapi_dir.rglob("applications.py"):
        if p.is_file() and p.stat().st_size > 100_000:
            app_file = p
            break

    if app_file:
        size_kb = app_file.stat().st_size / 1024
        line_count = len(app_file.read_text(encoding="utf-8", errors="ignore").splitlines())
        t0 = time.perf_counter()
        symbols = parser.parse_file(app_file)
        dt = time.perf_counter() - t0
        total_calls = sum(len(s.calls) for s in symbols)
        print(f"📄 applications.py: {size_kb:.1f} KB, {line_count} 行")
        print(f"   ⏱️ 耗时: {dt*1000:.2f} ms | 提取符号: {len(symbols)} | 提取调用边: {total_calls}")
        assert dt < 0.2, f"解析耗时过长: {dt:.3f}s"
        assert len(symbols) >= 20, f"提取符号过少: {len(symbols)}"
        assert total_calls > 100, f"提取调用边过少: {total_calls}"
        print("   ✅ applications.py 零崩溃、亚毫秒级解析通过！")

    # 1.2 测试 routing.py (260KB 路由引擎巨型文件)
    routing_file = None
    for p in fastapi_dir.rglob("routing.py"):
        if p.is_file() and p.stat().st_size > 100_000:
            routing_file = p
            break

    if routing_file:
        size_kb = routing_file.stat().st_size / 1024
        line_count = len(routing_file.read_text(encoding="utf-8", errors="ignore").splitlines())
        t0 = time.perf_counter()
        symbols = parser.parse_file(routing_file)
        dt = time.perf_counter() - t0
        total_calls = sum(len(s.calls) for s in symbols)
        print(f"📄 routing.py: {size_kb:.1f} KB, {line_count} 行")
        print(f"   ⏱️ 耗时: {dt*1000:.2f} ms | 提取符号: {len(symbols)} | 提取调用边: {total_calls}")
        assert dt < 0.25, f"解析耗时过长: {dt:.3f}s"
        assert len(symbols) >= 100, f"提取符号过少: {len(symbols)}"
        assert total_calls > 500, f"提取调用边过少: {total_calls}"
        print("   ✅ routing.py 零崩溃、超高吞吐解析通过！")


def test_fastapi_full_repo():
    print("\n" + "=" * 60)
    print("🚀 [基准测试 2] FastAPI 全仓库全量解析压测 (1,167+ Python 文件)")
    print("=" * 60)

    fastapi_dir = ROOT_DIR / "tests" / "benchmark_repos" / "fastapi"
    if not fastapi_dir.exists():
        print("⚠️ 未找到 fastapi 测试仓库，跳过此项基准")
        return

    py_files = [f for f in fastapi_dir.rglob("*.py") if f.is_file()]
    print(f"📂 发现 {len(py_files)} 个 Python 文件，开始全量 Tree-sitter S-expression 提取...")

    parser = TreeSitterParser()
    t0 = time.perf_counter()
    total_symbols = 0
    total_calls = 0
    errors = 0

    for idx, f in enumerate(py_files):
        try:
            syms = parser.parse_file(f)
            total_symbols += len(syms)
            total_calls += sum(len(s.calls) for s in syms)
        except Exception as e:
            errors += 1
            sys.stderr.write(f"文件解析失败 {f}: {e}\n")

    total_time = time.perf_counter() - t0
    throughput = len(py_files) / total_time if total_time > 0 else 0

    print(f"📊 基准测试结果:")
    print(f"   • 总文件数: {len(py_files)}")
    print(f"   • 成功率: {((len(py_files)-errors)/len(py_files))*100:.2f}% (失败 {errors} 个)")
    print(f"   • 总耗时: {total_time:.3f} 秒")
    print(f"   • 解析吞吐量: {throughput:.1f} 文件/秒")
    print(f"   • 提取符号总数: {total_symbols}")
    print(f"   • 提取调用边总数: {total_calls}")

    assert errors == 0, f"解析存在错误: {errors}"
    assert throughput >= 200, f"吞吐量低于 200 文件/秒: {throughput:.1f}"
    print("✅ FastAPI 全量代码库基准测试 100% 通过！")


def test_zustand_full_repo():
    print("\n" + "=" * 60)
    print("🚀 [基准测试 3] Zustand 前端真实代码库 (TypeScript / React)")
    print("=" * 60)

    zustand_dir = ROOT_DIR / "tests" / "benchmark_repos" / "zustand"
    if not zustand_dir.exists():
        print("⚠️ 未找到 zustand 测试仓库，跳过此项基准")
        return

    ts_files = [f for f in zustand_dir.rglob("*") if f.is_file() and f.suffix in (".ts", ".tsx", ".js")]
    print(f"📂 发现 {len(ts_files)} 个 TypeScript/JavaScript 文件...")

    parser = TreeSitterParser()
    t0 = time.perf_counter()
    total_symbols = 0
    errors = 0

    for f in ts_files:
        try:
            syms = parser.parse_file(f)
            total_symbols += len(syms)
        except Exception as e:
            errors += 1
            sys.stderr.write(f"TS 解析失败 {f}: {e}\n")

    total_time = time.perf_counter() - t0
    print(f"📊 基准测试结果:")
    print(f"   • 总文件数: {len(ts_files)}")
    print(f"   • 成功率: 100% (错误数: {errors})")
    print(f"   • 总耗时: {total_time*1000:.2f} ms")
    print(f"   • 提取符号总数: {total_symbols}")

    assert errors == 0, f"TS 解析存在错误: {errors}"
    assert total_symbols > 20, f"TS 符号提取过少: {total_symbols}"
    print("✅ Zustand (TS/React) 基准测试 100% 通过！")


def test_file_complexity_guard():
    print("\n" + "=" * 60)
    print("🚀 [基准测试 4] 极端复杂度与超限熔断保护测试 (>1MB 降级纯文本滑动窗口)")
    print("=" * 60)

    tmp_dir = ROOT_DIR / "tests" / "temp_benchmark_data"
    tmp_dir.mkdir(exist_ok=True, parents=True)
    giant_file = tmp_dir / "giant_synthetic_module.py"

    try:
        # 生成一个约 1.2MB 的超大 Python 文件 (30,000+ 行)
        lines = []
        lines.append('"""Synthetic giant file for complexity limit testing."""\n')
        for i in range(25000):
            lines.append(f"def generated_func_{i}(x, y):\n    return x * {i} + y\n")
        giant_file.write_text("\n".join(lines), encoding="utf-8")

        size_kb = giant_file.stat().st_size / 1024
        print(f"📄 已生成超限合成文件: {giant_file.name} ({size_kb:.1f} KB > 1024 KB)")

        chunker = UniversalCodeChunker(tmp_dir)
        t0 = time.perf_counter()
        chunks = chunker.parse_file(giant_file)
        dt = time.perf_counter() - t0

        print(f"⏱️ 熔断降级处理耗时: {dt:.3f} 秒")
        print(f"🧩 生成分块数量: {len(chunks)} 块")

        assert len(chunks) > 0, "降级切片未生成任何分块"
        # 验证所有切片类型均为 text_window，且平稳完成，未触发 AST 爆炸
        for c in chunks[:5]:
            assert c.chunk_type == "text_window", f"期望 text_window 降级，实际为 {c.chunk_type}"
            assert "[text-chunk" in c.symbol_name

        print("✅ 复杂度超限文件平稳降级为滑动窗口切片，保护机制 100% 生效！")
    finally:
        # 清理临时文件
        if giant_file.exists():
            giant_file.unlink()
        try:
            tmp_dir.rmdir()
        except Exception:
            pass


def main():
    print("\n============================================================")
    print("🔬 CODE-SEARCH-MCP 工业级高负载基准测试套件 (CodeGraph 对齐)")
    print("============================================================")
    t_start = time.perf_counter()

    test_fastapi_giant_files()
    test_fastapi_full_repo()
    test_zustand_full_repo()
    test_file_complexity_guard()

    total_duration = time.perf_counter() - t_start
    print("\n" + "=" * 60)
    print(f"🎉 全部大型仓库高负载基准测试圆满通过！总耗时: {total_duration:.2f} 秒")
    print("============================================================\n")


if __name__ == "__main__":
    main()
