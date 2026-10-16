import json
import shutil
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.graph_engine import CodeGraphEngine


def test_two_phase_resolution_pipeline():
    print("\n" + "=" * 60)
    print("🔬 [两阶段解析测试 1] 验证 Extraction 与 Resolution 两阶段解耦与 resolved_edges")
    print("=" * 60)

    test_dir = Path(tempfile.mkdtemp(prefix="test_twophase_"))
    try:
        # 创建多模块同名函数场景：彻底验证跨文件重名防串线
        pkg_a = test_dir / "pkg_a"
        pkg_b = test_dir / "pkg_b"
        pkg_c = test_dir / "pkg_c"
        pkg_a.mkdir(parents=True)
        pkg_b.mkdir(parents=True)
        pkg_c.mkdir(parents=True)

        # 3 个不同模块均定义了通用函数 handle()
        (pkg_a / "service.py").write_text("def handle(req):\n    return 'handled_by_A'\n", encoding="utf-8")
        (pkg_b / "service.py").write_text("def handle(req):\n    return 'handled_by_B'\n", encoding="utf-8")
        (pkg_c / "service.py").write_text("def handle(req):\n    return 'handled_by_C'\n", encoding="utf-8")

        # Caller 1: pkg_a 内同目录调用 handle() (应同目录就近唯一解析)
        (pkg_a / "controller.py").write_text(
            "def run_a():\n    return handle('data_a')\n",
            encoding="utf-8"
        )

        # Caller 2: 跨文件精确 Import 导入 pkg_b.service 的 handle 并调用
        (test_dir / "consumer_b.py").write_text(
            "from pkg_b.service import handle as handle_b\n"
            "def run_b():\n"
            "    return handle_b('data_b')\n",
            encoding="utf-8"
        )

        # Caller 3: 既无 import 处于独立根目录，裸调 handle() (全库 3 个同名定义，应标记歧义，绝不串线)
        (test_dir / "ambiguous_caller.py").write_text(
            "def run_ambiguous():\n    return handle('data_unknown')\n",
            encoding="utf-8"
        )

        # 执行索引构建
        indexer = CodeIndexer(test_dir)
        index_res = indexer.index_all()
        assert index_res["status"] == "success"

        # 加载图引擎并验证 SQLite 表结构
        graph = CodeGraphEngine.get_instance(test_dir)
        assert graph.load()

        conn = graph._get_db()
        nodes_cnt = conn.execute("SELECT count(*) as c FROM nodes").fetchone()["c"]
        calls_cnt = conn.execute("SELECT count(*) as c FROM calls").fetchone()["c"]
        edges_cnt = conn.execute("SELECT count(*) as c FROM resolved_edges").fetchone()["c"]

        print(f"📊 SQLite 统计: {nodes_cnt} 节点, {calls_cnt} 原始调用点, {edges_cnt} 条全局二次解析边")
        assert nodes_cnt >= 6
        assert calls_cnt >= 3
        assert edges_cnt >= 3

        # 1.1 检查 resolved_edges 表是否记录了高确信度的确定性边
        edges = conn.execute("""
            SELECT caller_symbol, caller_file, callee_symbol, callee_file, callee_qualified, call_name, resolution_type, confidence
            FROM resolved_edges
            WHERE resolution_type != 'EXTERNAL'
            ORDER BY caller_symbol
        """).fetchall()

        print("\n🔍 抽检 resolved_edges 确定性边:")
        for e in edges:
            print(f"  • {e['caller_symbol']} -> {e['callee_symbol']} ({e['callee_file']}) | 类型: {e['resolution_type']} | 确信度: {e['confidence']}")

        # 1.2 验证 Caller 1 (pkg_a/controller.py::run_a -> pkg_a/service.py::handle)
        callees_a = graph.get_callees("run_a")
        assert callees_a["status"] == "success"
        callee_a = callees_a["callees"][0]
        assert callee_a["target_symbol"] == "handle"
        assert not callee_a["ambiguous"], "同目录同包调用必须唯一消歧"
        assert "pkg_a" in callee_a["file_path"], f"期望指向 pkg_a，实际为: {callee_a['file_path']}"
        assert callee_a["resolution_type"] in ("SAME_DIR", "PACKAGE_EXPORT")
        assert callee_a["confidence"] >= 0.9
        print("✅ Caller 1 同包同目录就近确定性链接验证通过！")

        # 1.3 验证 Caller 2 (consumer_b.py::run_b -> pkg_b/service.py::handle)
        callees_b = graph.get_callees("run_b")
        assert callees_b["status"] == "success"
        callee_b = callees_b["callees"][0]
        assert not callee_b["ambiguous"], "显式跨模块 import 必须精确无歧义"
        assert "pkg_b" in callee_b["file_path"], f"期望精确指向 pkg_b，实际为: {callee_b['file_path']}"
        assert callee_b["resolution_type"] in ("EXACT_QUALIFIED", "SAME_MODULE")
        print("✅ Caller 2 跨文件精确 Import 跨模块确定性链接验证通过！")

        # 1.4 验证 Caller 3 (ambiguous_caller.py::run_ambiguous -> 跨 3 个模块重名歧义)
        callees_ambig = graph.get_callees("run_ambiguous")
        assert callees_ambig["status"] == "success"
        callee_ambig = callees_ambig["callees"][0]
        assert callee_ambig["ambiguous"], "无 import 且跨模块重名必须被标记为 ambiguous"
        assert len(callee_ambig["candidates"]) == 3, f"期望 3 个重名候选，实际: {callee_ambig['candidates']}"
        assert callee_ambig["resolution_type"] == "AMBIGUOUS"
        assert callee_ambig["confidence"] < 0.8
        print("✅ Caller 3 跨模块通用重名歧义拦截与防串线验证通过！")

        # 1.5 验证调用方反向查询 (get_callers 防串线隔离验证)
        # 查 pkg_a 的 handle: 只能被 run_a 调用，绝不能出现 run_b
        callers_a = graph.get_callers("pkg_a.service.handle")
        caller_syms_a = [c["caller_symbol"] for c in callers_a["callers"]]
        print(f"pkg_a.service.handle 的调用者: {caller_syms_a}")
        assert "run_a" in caller_syms_a
        assert "run_b" not in caller_syms_a, "严禁将 run_b 误串线至 pkg_a 的 handle"

        # 查 pkg_b 的 handle: 只能被 run_b 调用，绝不能出现 run_a
        callers_b = graph.get_callers("pkg_b.service.handle")
        caller_syms_b = [c["caller_symbol"] for c in callers_b["callers"]]
        print(f"pkg_b.service.handle 的调用者: {caller_syms_b}")
        assert "run_b" in caller_syms_b
        assert "run_a" not in caller_syms_b, "严禁将 run_a 误串线至 pkg_b 的 handle"
        print("✅ get_callers 跨文件精确反查 100% 隔离防串线通过！")

        # 1.6 验证改动影响面 / 爆炸半径 (Blast Radius 隔离验证)
        impact_a = graph.get_impact_radius("pkg_a.service.handle")
        impacted_syms_a = [i["symbol"] for i in impact_a["impact_propagation_chain"]]
        print(f"修改 pkg_a.service.handle 的波及符号链: {impacted_syms_a}")
        assert "run_a" in impacted_syms_a
        assert "run_b" not in impacted_syms_a, "严禁跨模块误传导至 pkg_b"
        print("✅ 爆炸半径分析验证通过，严禁跨模块误传导！")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    test_two_phase_resolution_pipeline()
    print("\n🎉 第一优先级: Two-Phase Extraction & Resolution 架构验证 100% 全部通过！\n")
