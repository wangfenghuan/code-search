import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 添加 src 到路径
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from code_search_mcp.indexer import CodeIndexer, UniversalCodeChunker
from code_search_mcp.multilang_parser import TreeSitterParser
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine
from code_search_mcp.searcher import CodeSearcher
from code_search_mcp.server import (
    exact_search,
    get_codebase_outline,
    get_file_content,
    get_watch_status,
    index_codebase,
    search_codebase,
)


def test_multilang_tree_sitter():
    print("\n--- 1. 测试 Tree-sitter 多语言解析 (Python, TS, Go) ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    parser = TreeSitterParser()

    # 1.1 Python 测试
    py_symbols = parser.parse_file(sample_dir / "auth_router.py")
    py_names = [s.name for s in py_symbols]
    print(f"Python 提取符号: {py_names}")
    assert "login_api" in py_names

    # 1.2 TypeScript 测试
    ts_symbols = parser.parse_file(sample_dir / "payment_service.ts")
    ts_names = [s.name for s in ts_symbols]
    print(f"TypeScript 提取符号: {ts_names}")
    assert "PaymentGateway" in ts_names
    assert "PaymentGateway.processPayment" in ts_names
    assert "PaymentGateway.refundOrder" in ts_names

    # 1.3 Go 测试
    go_symbols = parser.parse_file(sample_dir / "order_handler.go")
    go_names = [s.name for s in go_symbols]
    print(f"Go 提取符号: {go_names}")
    assert "OrderManager" in go_names
    assert "OrderManager.CreateOrder" in go_names
    assert "OrderManager.CancelOrder" in go_names

    print("✅ Tree-sitter 多语言语法解析 100% 通过！")


def test_outline_generation():
    print("\n--- 2. 测试项目全局多语言架构大纲 (Outline) ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    gen = ProjectOutlineGenerator(sample_dir)
    outline = gen.generate()
    md = gen.format_as_markdown(outline)
    print("多语言项目大纲 Markdown 预览:")
    print(md[:450] + "\n...")

    assert outline["total_modules"] >= 4
    assert "[typescript]" in md
    assert "[go]" in md
    assert "[python]" in md
    assert "PaymentGateway" in md
    assert "OrderManager" in md
    print("✅ 多语言架构大纲生成通过！")


def test_indexing_and_multilang_search():
    print("\n--- 3. 测试多语言全量索引与跨语言语义搜索 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"

    # 执行全量多语言索引
    indexer = CodeIndexer(sample_dir)
    res = indexer.index_all()
    print(f"索引结果: {res}")
    assert res["status"] == "success"
    assert res["indexed_files"] >= 5

    searcher = CodeSearcher(sample_dir)

    # 测试 A: 检索 TypeScript 支付业务
    q_ts = "在线支付交易与退款处理"
    res_ts = searcher.search(q_ts, top_k=2)
    print(f"\n查询: '{q_ts}'")
    for r in res_ts:
        print(f"  命中: [{r['language']}] {r['file_path']} -> {r['symbol_name']} (得分: {r['similarity']})")
    assert any("payment_service.ts" in r["file_path"] for r in res_ts), "未能命中 TypeScript 支付模块"
    print("✅ TypeScript 跨语言语义检索通过！")

    # 测试 B: 检索 Go 订单履约
    q_go = "订单流转创建与库存冻结"
    res_go = searcher.search(q_go, top_k=2)
    print(f"\n查询: '{q_go}'")
    for r in res_go:
        print(f"  命中: [{r['language']}] {r['file_path']} -> {r['symbol_name']} (得分: {r['similarity']})")
    assert any("order_handler.go" in r["file_path"] for r in res_go), "未能命中 Go 订单模块"
    print("✅ Go 跨语言语义检索通过！")


def test_exact_ripgrep_search():
    print("\n--- 4. 测试 ripgrep 跨语言精准字面量与证据检索 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    engine = ExactSearchEngine(sample_dir)

    # 跨语言检索 TS 里的 pay.example.com
    res_ts = engine.search("pay.example.com")
    print(f"ripgrep 命中 TS 字面量: {len(res_ts['matches'])} 处")
    assert len(res_ts["matches"]) >= 1
    assert any("payment_service.ts" in m.file_path for m in res_ts["matches"])

    # 跨语言检索 Go 里的 ORD_20261015
    res_go = engine.search("ORD_20261015")
    print(f"ripgrep 命中 Go 字面量: {len(res_go['matches'])} 处")
    assert len(res_go["matches"]) >= 1
    assert any("order_handler.go" in m.file_path for m in res_go["matches"])

    print("✅ ripgrep 跨语言精准证据检索通过！")


def test_mcp_tools():
    print("\n--- 5. 测试全部 5 个 FastMCP 工具接口（多语言支持） ---")
    sample_dir = str(ROOT_DIR / "tests" / "sample_project")

    # 工具 1: get_codebase_outline
    outline_res = get_codebase_outline(sample_dir)
    assert "[typescript]" in outline_res
    assert "[go]" in outline_res

    # 工具 2: search_codebase (跨语言)
    search_res = search_codebase("退款逻辑在哪里", path=sample_dir, top_k=2, compact=True)
    assert "refundOrder" in search_res or "PaymentGateway" in search_res

    # 工具 3: exact_search
    exact_res = exact_search("CreateOrder", path=sample_dir)
    assert "order_handler.go" in exact_res

    # 工具 4: get_file_content (读取 Go 文件片段)
    go_file_path = str(ROOT_DIR / "tests" / "sample_project" / "order_handler.go")
    file_content = get_file_content(go_file_path, start_line=1, end_line=15)
    assert "OrderManager" in file_content

    # 工具 5: 新增 CodeGraph 图谱工具
    # 5.1 explore_codebase
    from code_search_mcp.server import (
        explore_codebase,
        get_impact_radius,
        get_symbol_callers,
        get_symbol_callees,
    )
    explore_res = explore_codebase("用户登录认证与密码校验", path=sample_dir, top_k=2)
    assert "login_api" in explore_res or "AuthService" in explore_res
    assert "HTTP POST /api/v1/auth/login" in explore_res

    # 5.2 get_symbol_callers
    callers_res = get_symbol_callers("verify_password", path=sample_dir)
    assert "AuthService.login" in callers_res

    # 5.3 get_symbol_callees
    callees_res = get_symbol_callees("login_api", path=sample_dir)
    assert "login" in callees_res

    # 5.4 get_impact_radius
    impact_res = get_impact_radius("hash_password", path=sample_dir)
    assert "HTTP POST /api/v1/auth/login" in impact_res
    assert "login_api" in impact_res

    print("✅ 全部 FastMCP 工具（包含 4 个 CodeGraph 图谱能力）端到端验证通过！")


def test_codegraph_graph_engine():
    print("\n--- 6. 测试 CodeGraph 代码知识图谱引擎核心能力 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    from code_search_mcp.graph_engine import CodeGraphEngine

    graph = CodeGraphEngine(sample_dir)
    assert graph.load()

    # 6.1 测试上游 Caller 追踪
    callers = graph.get_callers("hash_password")
    caller_symbols = [c["caller_symbol"] for c in callers["callers"]]
    print(f"hash_password 的调用方: {caller_symbols}")
    assert "PasswordHasher.verify_password" in caller_symbols
    assert "AuthService.login" in caller_symbols
    print("✅ Caller 上游调用链追踪通过！")

    # 6.2 测试下游 Callee 依赖追踪
    callees = graph.get_callees("AuthService.login")
    callee_symbols = [c["target_symbol"] for c in callees["callees"]]
    print(f"AuthService.login 调用的下级依赖: {callee_symbols}")
    assert "hash_password" in callee_symbols
    assert "verify_password" in callee_symbols
    print("✅ Callee 下游依赖追踪通过！")

    # 6.3 测试改动爆炸半径 / 影响面分析 (Blast Radius)
    impact = graph.get_impact_radius("hash_password", max_depth=3)
    impacted_symbols = [item["symbol"] for item in impact["impact_propagation_chain"]]
    impacted_routes = [r["route"] for r in impact["impacted_external_routes"]]
    print(f"hash_password 影响符号链: {impacted_symbols}")
    print(f"hash_password 受波及外部路由: {impacted_routes}")
    assert "PasswordHasher.verify_password" in impacted_symbols
    assert "AuthService.login" in impacted_symbols
    assert "login_api" in impacted_symbols
    assert "HTTP POST /api/v1/auth/login" in impacted_routes
    print("✅ Blast Radius 影响面与受波及路由分析通过！")

    # 6.4 测试一键全链路探索 (explore_feature)
    explore = graph.explore_feature("用户登录认证与密码加密校验", top_k=2)
    md = explore["surgical_context_markdown"]
    print("一键探索 Markdown 摘要预览:")
    print(md[:400] + "\n...")
    assert "HTTP POST /api/v1/auth/login" in md
    assert "login_api" in md
    print("✅ 一键直达手术级探索 (explore_feature) 验证通过！")


def test_incremental_indexing_and_watcher():
    print("\n--- 7. 测试路线A：毫秒级增量热索引与文件热监听器 (Watcher) ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    temp_file = sample_dir / "temp_coupon_service.py"

    indexer = CodeIndexer(sample_dir)
    searcher = CodeSearcher(sample_dir)

    # 1. 确保初始全量索引已就绪
    if not searcher.is_indexed():
        indexer.index_all()

    # 清理遗留文件（如果有）
    if temp_file.exists():
        temp_file.unlink()
        indexer.index_file_incremental(temp_file)

    # 2. 模拟开发者新增一个 Python 文件
    temp_file.write_text(
        'def apply_coupon(order_id: str, coupon_code: str) -> float:\n'
        '    """计算优惠券抵扣金额并应用至订单"""\n'
        '    if coupon_code == "VIP99":\n'
        '        return 99.0\n'
        '    return 0.0\n',
        encoding="utf-8",
    )

    # 执行增量热索引
    res_add = indexer.index_file_incremental(temp_file)
    print(f"新增文件增量更新结果: {res_add}")
    assert res_add["status"] == "updated"
    assert res_add["chunks_count"] >= 1

    # 语义检索新增的函数
    search_res = searcher.search("优惠券抵扣与折扣计算", top_k=2)
    print("检索新增优惠券逻辑命中项:")
    for r in search_res:
        print(f"  [{r['language']}] {r['file_path']} -> {r['symbol_name']}")
    assert any("temp_coupon_service.py" in r["file_path"] for r in search_res)
    print("✅ 增量新增文件秒级索引与检索通过！")

    # 3. 模拟开发者修改该文件（增加新接口）
    temp_file.write_text(
        'def apply_coupon(order_id: str, coupon_code: str) -> float:\n'
        '    """计算优惠券抵扣金额并应用至订单"""\n'
        '    return 50.0\n\n'
        'def validate_coupon(coupon_code: str) -> bool:\n'
        '    """验证优惠券有效性与过期时间"""\n'
        '    return len(coupon_code) > 0\n',
        encoding="utf-8",
    )
    res_mod = indexer.index_file_incremental(temp_file)
    print(f"修改文件增量更新结果: {res_mod}")
    assert res_mod["status"] == "updated"
    assert res_mod["chunks_count"] >= 2

    # 检索新接口
    search_res_mod = searcher.search("验证优惠券有效性", top_k=2)
    assert any("validate_coupon" in r["symbol_name"] for r in search_res_mod)
    print("✅ 增量修改文件热更新与重新索引通过！")

    # 4. 模拟开发者删除该文件
    temp_file.unlink()
    res_del = indexer.index_file_incremental(temp_file)
    print(f"删除文件增量索引结果: {res_del}")
    assert res_del["status"] == "deleted"

    # 再次检索，应不再出现已删除文件
    search_res_del = searcher.search("优惠券抵扣与折扣计算", top_k=5)
    assert not any("temp_coupon_service.py" in r["file_path"] for r in search_res_del)
    print("✅ 增量删除文件热更新与旧索引清除通过！")

    # 5. 测试 RepoWatcher 与 get_watch_status MCP 工具
    from code_search_mcp.watcher import get_or_create_watcher

    status_inactive = get_watch_status(str(sample_dir))
    assert "代码库实时热监听状态" in status_inactive

    watcher = get_or_create_watcher(sample_dir, auto_start=True)
    assert watcher.is_running
    status_active = get_watch_status(str(sample_dir))
    assert "正在运行" in status_active
    watcher.stop()
    assert not watcher.is_running
    print("✅ 后台热监听器 (Watcher) 启停与 MCP 工具 get_watch_status 端到端通过！")


if __name__ == "__main__":
    test_multilang_tree_sitter()
    test_outline_generation()
    test_indexing_and_multilang_search()
    test_exact_ripgrep_search()
    test_codegraph_graph_engine()
    test_mcp_tools()
    test_incremental_indexing_and_watcher()
    print("\n🎉 全部单元与端到端测试 100% 全部通过！")
