import os
import shutil
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

    # 1.4 Java 测试 (Spring Boot REST 控制器与服务、调用过滤)
    java_symbols = parser.parse_file(sample_dir / "UserController.java", include_calls=True)
    java_names = [s.name for s in java_symbols]
    print(f"Java 提取符号: {java_names}")
    assert "UserController" in java_names
    assert "UserController.UserController" in java_names
    assert "UserController.getUsers" in java_names
    assert "UserController.createUser" in java_names
    get_users = next(s for s in java_symbols if s.name == "UserController.getUsers")
    assert get_users.route_info == "HTTP GET /api/v1/users"
    assert any("UserService.findAll" in c for c in get_users.calls)

    # 验证 Java 过滤 JDK 标准库与局部变量调用误报
    user_svc_symbols = parser.parse_file(sample_dir / "UserService.java", include_calls=True)
    find_all = next(s for s in user_svc_symbols if s.name == "UserService.findAll")
    assert not any("java.util" in c for c in find_all.calls)
    assert not any("users.add" in c for c in find_all.calls)

    # 1.5 Rust 测试 (Actix-web 路由、结构体、枚举与调用图)
    rust_symbols = parser.parse_file(sample_dir / "order_service.rs", include_calls=True)
    rust_names = [s.name for s in rust_symbols]
    print(f"Rust 提取符号: {rust_names}")
    assert "OrderService" in rust_names
    assert "OrderStatus" in rust_names
    assert "OrderProcessor" in rust_names
    assert "OrderService.new" in rust_names
    assert "OrderService.get_order" in rust_names
    assert "OrderService.create_order" in rust_names
    assert "notify_order_created" in rust_names
    get_order = next(s for s in rust_symbols if s.name == "OrderService.get_order")
    assert get_order.route_info == "HTTP GET /api/v1/orders"
    create_order = next(s for s in rust_symbols if s.name == "OrderService.create_order")
    assert any("notify_order_created" in c for c in create_order.calls)

    print("✅ Tree-sitter 多语言语法解析 100% 通过！")


def test_outline_generation():
    print("\n--- 2. 测试项目全局多语言架构大纲 (Outline) ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    gen = ProjectOutlineGenerator(sample_dir)
    outline = gen.generate()
    md = gen.format_as_markdown(outline)
    print("多语言项目大纲 Markdown 预览:")
    print(md[:450] + "\n...")

    assert outline["total_modules"] >= 5
    assert "[typescript]" in md
    assert "[go]" in md
    assert "[python]" in md
    assert "[java]" in md
    assert "[rust]" in md
    assert "PaymentGateway" in md
    assert "OrderManager" in md
    assert "UserController" in md
    assert "OrderService" in md
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

    # 测试 C: 检索 Java 用户领域业务
    q_java = "查询系统全部活跃用户"
    res_java = searcher.search(q_java, top_k=2)
    print(f"\n查询: '{q_java}'")
    for r in res_java:
        print(f"  命中: [{r['language']}] {r['file_path']} -> {r['symbol_name']} (得分: {r['similarity']})")
    assert any("UserService" in r["symbol_name"] for r in res_java), "未能命中 Java 用户服务模块"
    print("✅ Java 跨语言语义检索通过！")


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


def test_phase0_fixes():
    print("\n--- 8. 测试 Phase 0 核心修复：语言内置过滤隔离、Schema 版本控制、前缀删除与元数据同步 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    indexer = CodeIndexer(sample_dir)
    res = indexer.index_all()
    assert res["status"] == "success"

    # 1. 验证按语言隔离的内置过滤 (Fix #4)
    from code_search_mcp.multilang_parser import TreeSitterParser
    parser = TreeSitterParser()
    py_code = b"""
def demo_func():
    make()
    open("a.txt")
    sum([1, 2])
"""
    symbols = parser.parse_code(py_code, "demo.py", "python")
    calls = symbols[0].calls
    print(f"Python 提取调用列表: {calls}")
    assert "make" in calls, "Python 自定义 make() 不应被过滤"
    assert "open" not in calls, "Python 内置 open 应该被过滤"
    assert "sum" not in calls, "Python 内置 sum 应该被过滤"

    # 验证 JS console.log 修复
    js_code = b"""
function testLog() {
    console.log("hello");
    console.error("error");
    customLog("message");
}
"""
    js_symbols = parser.parse_code(js_code, "test.js", "javascript")
    js_calls = js_symbols[0].calls
    print(f"JavaScript 提取调用列表: {js_calls}")
    assert "customLog" in js_calls
    assert "log" not in js_calls, "console.log 中的 log 应该被过滤"
    assert "error" not in js_calls, "console.error 中的 error 应该被过滤"
    print("✅ 语言内置过滤隔离与 console.log 修复通过！")

    # 2. 验证 Schema 版本控制 (Fix #16)
    import json
    from code_search_mcp.config import INDEX_SCHEMA_VERSION, get_repo_db_path
    from code_search_mcp.searcher import CodeSearcher
    meta_path = get_repo_db_path(sample_dir) / "meta.json"
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_data.get("schema_version") == INDEX_SCHEMA_VERSION
    assert meta_data.get("indexed_files") >= 5
    assert meta_data.get("indexed_chunks") >= 20

    # 模拟旧版本 schema
    meta_data["schema_version"] = "v0_incompatible"
    meta_path.write_text(json.dumps(meta_data), encoding="utf-8")
    searcher = CodeSearcher(sample_dir)
    assert not searcher.is_indexed(), "旧版本 schema 应被判定为未索引/不兼容"

    # 恢复索引
    indexer.index_all()
    assert searcher.is_indexed()
    print("✅ Schema 版本校验与模型兼容机制通过！")

    # 3. 验证文件夹级前缀删除与元数据同步 (Fix #14)
    sub_dir = sample_dir / "temp_subpkg"
    sub_dir.mkdir(parents=True, exist_ok=True)
    f1 = sub_dir / "mod_a.py"
    f2 = sub_dir / "mod_b.py"
    f1.write_text("def sub_func_a(): pass\n", encoding="utf-8")
    f2.write_text("def sub_func_b(): pass\n", encoding="utf-8")

    indexer.index_file_incremental(f1)
    indexer.index_file_incremental(f2)

    meta_after_add = json.loads(meta_path.read_text(encoding="utf-8"))
    files_count_add = meta_after_add["indexed_files"]

    # 递归删除整个 temp_subpkg 目录
    f1.unlink()
    f2.unlink()
    sub_dir.rmdir()

    indexer.delete_file_from_index("temp_subpkg")
    meta_after_del = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_after_del["indexed_files"] < files_count_add, "删除文件夹后文件统计应同步减少"
    print("✅ 文件夹级递归前缀删除与元数据同步通过！")

    # 4. 验证 get_callers 对已删除/外部符号的明确提示 (Fix #13, #15)
    from code_search_mcp.graph_engine import CodeGraphEngine, format_callers_markdown
    graph = CodeGraphEngine.get_instance(sample_dir)
    res_external = graph.get_callers("non_existent_function_xyz")
    assert not res_external["defined_in_repo"]
    md = format_callers_markdown(res_external)
    assert "未检索到定义" in md
    print("✅ 符号存在性校验与未定义提示通过！")


def test_phase1_fixes():
    print("\n--- 9. 测试 Phase 1: 跨文件 Import 解析、模块全限定名与拓扑消歧 ---")
    import shutil
    import tempfile
    from code_search_mcp.multilang_parser import TreeSitterParser
    from code_search_mcp.indexer import CodeIndexer
    from code_search_mcp.graph_engine import CodeGraphEngine, format_callees_markdown, format_callers_markdown

    # 1. 验证跨文件 Import 与类型实例化推断
    parser = TreeSitterParser()
    py_code = (
        b"from auth.service import AuthService, hash_password as hp\n"
        b"auth_service = AuthService()\n"
        b"def handle_login(req):\n"
        b"    auth_service.login(req)\n"
        b"    hp(req.password)\n"
    )
    syms = parser.parse_code(py_code, file_name="routes/auth.py", lang="python")
    login_fn = [s for s in syms if s.name == "handle_login"][0]
    assert "login" in login_fn.calls
    assert "auth.service.AuthService.login" in login_fn.calls, "应推断出 AuthService.login 的跨文件限定调用"
    assert "hp" in login_fn.calls
    assert "auth.service.hash_password" in login_fn.calls, "应通过 alias hp 解析出原函数限定调用"
    assert login_fn.qualified_name == "routes.auth.handle_login"
    print("✅ 跨文件 Import 与实例变量限定调用解析通过！")

    # 2. 验证多文件同名符号拓扑消歧 (同目录优先 vs 跨模块歧义)
    test_dir = Path(tempfile.mkdtemp(prefix="test_disambig_"))
    try:
        user_dir = test_dir / "user"
        order_dir = test_dir / "order"
        user_dir.mkdir(parents=True)
        order_dir.mkdir(parents=True)

        (user_dir / "service.py").write_text("def process():\n    return 'user'\n", encoding="utf-8")
        (user_dir / "controller.py").write_text("def run_user():\n    process()\n", encoding="utf-8")
        (order_dir / "service.py").write_text("def process():\n    return 'order'\n", encoding="utf-8")
        (test_dir / "main.py").write_text("def global_run():\n    process()\n", encoding="utf-8")

        indexer = CodeIndexer(test_dir)
        indexer.index_all()

        graph = CodeGraphEngine.get_instance(test_dir)

        # 2.1 user/controller.py 里的 process 应该消歧为 user/service.py (同目录优先)
        callees_user = graph.get_callees("run_user")
        assert callees_user["status"] == "success"
        matched_callee = [c for c in callees_user["callees"] if c["target_symbol"] == "process"][0]
        assert not matched_callee["ambiguous"], "同目录符号应自动唯一消歧"
        assert "user" in matched_callee["file_path"]

        # 2.2 main.py 里的 process 处于不同目录，有两个候选，应标记 ambiguous
        callees_main = graph.get_callees("global_run")
        assert callees_main["status"] == "success"
        matched_main_callee = [c for c in callees_main["callees"] if c["target_symbol"] == "process"][0]
        assert matched_main_callee["ambiguous"], "跨模块同名候选应标记 ambiguous"
        assert len(matched_main_callee["candidates"]) == 2
        md_callees = format_callees_markdown(callees_main)
        assert "重名歧义提示" in md_callees

        # 2.3 get_callers 探测 process 时提示多重定义
        callers_res = graph.get_callers("process")
        assert len(callers_res["ambiguous_definitions"]) == 2
        md_callers = format_callers_markdown(callers_res)
        assert "同名符号多定义提示" in md_callers
        print("✅ 同名符号拓扑消歧 (同文件/同目录消歧 + 歧义报警) 端到端通过！")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_phase2_fixes():
    print("\n--- 10. 测试 Phase 2: 代码分块重构 (Windowed Chunking) 与真正 BM25+Dense RRF 混合检索 ---")
    import shutil
    import tempfile
    from code_search_mcp.config import DEFAULT_MODEL_NAME, VECTOR_DIMENSION
    from code_search_mcp.indexer import CodeIndexer, UniversalCodeChunker
    from code_search_mcp.searcher import CodeSearcher

    # 1. 验证配置与向量维度解耦 (Fix #5)
    assert DEFAULT_MODEL_NAME == "BAAI/bge-small-zh-v1.5"
    assert VECTOR_DIMENSION == 512
    print("✅ 向量模型与维度可配置解耦通过！")

    # 2. 验证超长函数滑动窗口切分 (Windowed Chunking, Fix #6)
    test_dir = Path(tempfile.mkdtemp(prefix="test_chunking_"))
    try:
        long_func_lines = ["def complex_business_flow():", '    """处理极其复杂的跨多阶段交易流转"""']
        for i in range(150):
            long_func_lines.append(f"    step_{i} = execute_step({i})")
        long_func_lines.append("    return True\n")
        (test_dir / "complex.py").write_text("\n".join(long_func_lines), encoding="utf-8")

        chunker = UniversalCodeChunker(test_dir)
        chunks = chunker.parse_file(test_dir / "complex.py")
        assert len(chunks) >= 2, f"150行的超长函数应该被切分为多块窗口，实际切得 {len(chunks)} 块"
        assert chunks[0].symbol_name == "complex_business_flow#part1"
        assert chunks[1].symbol_name == "complex_business_flow#part2"
        assert "所属模块: complex" in chunks[0].enriched_text
        print("✅ 超长函数滑动窗口切分 (Windowed Chunking) 与模块上下文注入通过！")

        # 3. 验证真正 Dense + BM25 FTS 混合检索与 RRF 融合 (Fix #7)
        indexer = CodeIndexer(test_dir)
        indexer.index_all()

        searcher = CodeSearcher(test_dir)
        assert searcher.is_indexed()

        # 检索测试
        results = searcher.search("跨多阶段交易流转", top_k=2)
        assert len(results) > 0
        assert "complex_business_flow" in results[0]["symbol_name"]
        assert results[0]["similarity"] > 0.0
        print("✅ Dense + BM25 RRF 真正混合检索通过！")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_phase3_fixes():
    print("\n--- 11. 测试 Phase 3: BFS 多层调用链路展开、业务流聚合与全仓库反向引用分析 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    from code_search_mcp.graph_engine import CodeGraphEngine, format_references_markdown
    from code_search_mcp.server import find_references

    graph = CodeGraphEngine.get_instance(sample_dir)
    assert graph.load()

    # 1. 验证 BFS 多层调用拓扑树与端到端链路生成 (Fix #8, #9, #11)
    explore_res = graph.explore_feature("用户登录认证与密码校验", top_k=2, max_depth=3)
    assert explore_res["status"] == "success"
    md = explore_res["surgical_context_markdown"]
    print("BFS 全链路探索结果 Markdown 片段:")
    for line in md.splitlines():
        if "Execution Trace" in line or "└──" in line or "├──" in line or "业务调用链路" in line:
            print("  " + line)

    assert "端到端多层调用链路 (Execution Trace)" in md
    assert "└── ➡️" in md or "├── ➡️" in md, "应包含多层树状 ASCII 调用拓扑"
    assert len(explore_res["involved_files"]) >= 1
    print("✅ BFS 多层执行链路生成与全景路由拓扑通过！")

    # 2. 验证全仓库反向引用分析 (find_references, Fix #20)
    ref_res = graph.find_references("hash_password")
    assert ref_res["status"] == "success"
    assert ref_res["structural_callers_count"] >= 1
    assert ref_res["total_references"] >= 2
    md_refs = format_references_markdown(ref_res)
    assert "代码符号显式调用方" in md_refs
    print("✅ CodeGraphEngine.find_references 反向引用分析通过！")

    # 3. 验证 MCP 工具层 find_references
    mcp_tool_res = find_references("verify_password", path=str(sample_dir))
    assert "跨模块反向引用分析" in mcp_tool_res
    assert "AuthService.login" in mcp_tool_res
    print("✅ MCP Tool find_references 端到端调用验证通过！")


def test_dynamic_calls_and_sqlite_engine():
    print("\n--- 12. 测试动态调用识别 (getattr / obj[dynamic]) 与 SQLite 按需图引擎 ---")
    from code_search_mcp.multilang_parser import TreeSitterParser
    import tempfile
    import shutil
    from code_search_mcp.indexer import CodeIndexer
    from code_search_mcp.graph_engine import CodeGraphEngine

    parser = TreeSitterParser()

    # 1. 验证 Python 动态调用抽取 (getattr 字符串字面量、动态变量与字典分发)
    py_code = '''
class DynamicWorker:
    def execute(self, action_var: str):
        # 1. getattr 字符串字面量静态化调用
        getattr(self, "do_task")("param1")
        # 2. getattr 动态变量调用
        getattr(self, action_var)("param2")
        # 3. 字典/映射动态下标分发
        dispatch_table["handle_event"](payload)

    def do_task(self, param: str):
        return True
'''.encode("utf-8")
    py_syms = parser.parse_code(py_code, file_name="dynamic_demo.py", lang="python")
    worker_exec = [s for s in py_syms if s.name == "DynamicWorker.execute"][0]
    print(f"Python 动态调用抽取结果: {worker_exec.calls}")
    assert "do_task" in worker_exec.calls, "getattr字面量应成功提取目标函数名"
    assert "handle_event" in worker_exec.calls, "subscript字典字面量应提取目标函数名"
    assert any("<dynamic:action_var>" in c for c in worker_exec.calls), "getattr动态变量应提取动态标记"
    print("✅ Python getattr 与下标动态调用提取通过！")

    # 2. 验证 TS/JS 动态下标调用抽取 (obj['prop'] 与 obj[dynamic])
    ts_code = '''
class PaymentRouter {
    process(action: string) {
        // 1. 下标字符串字面量调用
        this["refundOrder"](123);
        // 2. 下标动态变量调用
        this[action](456);
    }
    refundOrder(id: number) {
        return true;
    }
}
'''.encode("utf-8")
    ts_syms = parser.parse_code(ts_code, file_name="router.ts", lang="typescript")
    router_proc = [s for s in ts_syms if s.name == "PaymentRouter.process"][0]
    print(f"TS 动态调用抽取结果: {router_proc.calls}")
    assert "refundOrder" in router_proc.calls, "TS obj['method'] 应提取 method"
    assert any("<dynamic:action>" in c for c in router_proc.calls), "TS obj[dynamic] 应提取动态标记"
    print("✅ TS/JS 下标动态调用提取通过！")

    # 3. 验证 SQLite 按需查询引擎
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    engine = CodeGraphEngine.get_instance(sample_dir)
    assert engine.load()
    assert engine.sqlite_path.exists(), f"SQLite 数据库文件应已生成在 {engine.sqlite_path}"

    # 验证 SQLite 节点表与调用表
    conn = engine._get_db()
    node_count = conn.execute("SELECT count(*) as c FROM nodes").fetchone()["c"]
    call_count = conn.execute("SELECT count(*) as c FROM calls").fetchone()["c"]
    print(f"SQLite 图谱库当前索引: {node_count} 个节点, {call_count} 条调用边")
    assert node_count >= 5
    assert call_count >= 5

    # 验证毫秒级按需查询
    callers = engine.get_callers("hash_password")
    assert callers["status"] == "success"
    assert callers["callers_count"] >= 1
    print("✅ SQLite 按需图引擎索引与秒级查询验证通过！")


def test_identifier_splitting_and_rrf():
    print("\n--- 13. 测试标识符拆词注入（Camel/Snake Case）与多路 RRF 归一化融合 ---")
    from code_search_mcp.indexer import CodeIndexer, build_enriched_text
    from code_search_mcp.searcher import CodeSearcher
    from code_search_mcp.text_utils import (
        expand_query_with_splits,
        extract_natural_words_from_identifiers,
        split_camel_snake_case,
    )

    # 1. 验证 Camel/Snake Case 拆词算法
    words_snake = split_camel_snake_case("verify_jwt_token_signature")
    assert words_snake == ["verify", "jwt", "token", "signature"]

    words_camel = split_camel_snake_case("verifyJwtTokenSignature")
    assert words_camel == ["verify", "jwt", "token", "signature"]

    words_pascal = split_camel_snake_case("UserProfileManager")
    assert words_pascal == ["user", "profile", "manager"]

    words_acronym = split_camel_snake_case("getHTTPResponseCode")
    assert words_acronym == ["get", "http", "response", "code"]
    print("✅ 1. 标识符 Camel/Snake/Pascal/Acronym 拆词精准测试通过！")

    # 2. 验证查询语句自动展开
    exp1 = expand_query_with_splits("verify_jwt_token 鉴权")
    assert "verify jwt token" in exp1
    exp2 = expand_query_with_splits("verifyJwtTokenSignature")
    assert "verify jwt token signature" in exp2
    print("✅ 2. 查询语句自动自然语言拆词展开测试通过！")

    # 3. 验证 build_enriched_text 拆词注入且不改变原始源码
    raw_code = "def verify_jwt_token_signature(req):\n    return check_token(req.token)"
    enriched = build_enriched_text(
        rel_path="auth/jwt.py",
        language="python",
        symbol_name="verify_jwt_token_signature",
        chunk_type="function",
        signature="(req)",
        docstring="验证 JWT 签名合法性",
        route_info="",
        decorators="",
        code=raw_code,
        module_name="auth.jwt",
    )
    assert "标识符自然语言拆词: verify jwt token signature" in enriched
    assert "def verify_jwt_token_signature(req):" in enriched
    assert raw_code in enriched  # 源码保持原汁原味
    print("✅ 3. 向量化富化文本拆词注入且源码不改变验证通过！")

    # 4. 验证端到端多路 RRF 倒数排名融合检索 (LanceDB 向量 + Ripgrep 符号 + AST 路由结构)
    test_repo = ROOT_DIR / "tests" / "test_rrf_repo"
    shutil.rmtree(test_repo, ignore_errors=True)
    test_repo.mkdir(parents=True, exist_ok=True)
    try:
        # 创建包含复杂长标识符代码文件
        jwt_py = test_repo / "security_jwt.py"
        jwt_py.write_text(
            '"""JWT 核心安全签名验证模块"""\n\n'
            "def verify_jwt_token_signature(request_token: str):\n"
            '    """验证并校验客户端 JWT 签名的合法性与有效期"""\n'
            '    return True\n\n'
            "def handle_unrelated_job():\n"
            '    """无关的定时任务处理"""\n'
            '    pass\n',
            encoding="utf-8",
        )

        indexer = CodeIndexer(test_repo)
        indexer.index_all()

        searcher = CodeSearcher(test_repo)
        assert searcher.is_indexed()

        # 中文自然语言提问 "JWT 签名校验"
        results_zh = searcher.search("JWT 签名校验", top_k=2)
        assert len(results_zh) > 0
        top_match = results_zh[0]
        assert top_match["symbol_name"] == "verify_jwt_token_signature"
        assert 0.0 < top_match["similarity"] <= 1.0
        print(f"  命中结果: {top_match['symbol_name']} (RRF 归一化得分: {top_match['similarity']})")

        # 英文长标识符提问 "verifyJwtTokenSignature"
        results_en = searcher.search("verifyJwtTokenSignature", top_k=2)
        assert len(results_en) > 0
        assert results_en[0]["symbol_name"] == "verify_jwt_token_signature"
        assert 0.0 < results_en[0]["similarity"] <= 1.0
        print(f"  英文标识符命中: {results_en[0]['symbol_name']} (RRF 归一化得分: {results_en[0]['similarity']})")

        print("✅ 4. 多路 RRF (向量 + Ripgrep + AST) 统一归一化检索验证 100% 通过！")
    finally:
        shutil.rmtree(test_repo, ignore_errors=True)


if __name__ == "__main__":
    test_multilang_tree_sitter()
    test_outline_generation()
    test_indexing_and_multilang_search()
    test_exact_ripgrep_search()
    test_codegraph_graph_engine()
    test_mcp_tools()
    test_incremental_indexing_and_watcher()
    test_phase0_fixes()
    test_phase1_fixes()
    test_phase2_fixes()
    test_phase3_fixes()
    test_dynamic_calls_and_sqlite_engine()
    test_identifier_splitting_and_rrf()
    print("\n🎉 全部单元与端到端测试 100% 全部通过！")


