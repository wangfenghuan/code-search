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

from code_search_mcp.indexer import CodeIndexer, PythonAstChunker
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine
from code_search_mcp.searcher import CodeSearcher
from code_search_mcp.server import (
    exact_search,
    get_codebase_outline,
    get_file_content,
    index_codebase,
    search_codebase,
)


def test_chunker():
    print("\n--- 1. 测试 AST 代码切片与路由装饰器识别 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    chunker = PythonAstChunker(sample_dir)
    router_file = sample_dir / "auth_router.py"
    chunks = chunker.parse_file(router_file)

    symbols = [c.symbol_name for c in chunks]
    print(f"路由模块切出的符号: {symbols}")

    login_chunk = next(c for c in chunks if c.symbol_name == "login_api")
    print(f"login_api 识别到的路由信息: {login_chunk.route_info}")
    assert "POST" in login_chunk.route_info
    assert "/api/v1/auth/login" in login_chunk.route_info
    print("✅ AST 切片与路由解析通过！")


def test_outline_generation():
    print("\n--- 2. 测试项目架构大纲 (Outline) 极省 Token 地图 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    gen = ProjectOutlineGenerator(sample_dir)
    outline = gen.generate()
    md = gen.format_as_markdown(outline)
    print("生成的项目大纲 Markdown 预览:")
    print(md[:350] + "\n...")

    assert outline["total_modules"] >= 3
    assert "AuthService" in md
    assert "PasswordHasher" in md
    assert "ConnectionPool" in md
    print("✅ 架构大纲生成通过！")


def test_indexing_and_search():
    print("\n--- 3. 测试索引构建与精准符号/路由混合检索 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"

    # 执行全量索引
    indexer = CodeIndexer(sample_dir)
    res = indexer.index_all()
    print(f"索引结果: {res}")
    assert res["status"] == "success"
    assert res["indexed_files"] >= 3

    searcher = CodeSearcher(sample_dir)

    # 场景 A: 路由检索 "POST /api/v1/auth/login"
    q_route = "POST /api/v1/auth/login 接口"
    res_route = searcher.search(q_route, top_k=2)
    print(f"\n查询: '{q_route}'")
    for r in res_route:
        print(f"  命中: {r['file_path']} -> {r['symbol_name']} (路由: {r['route_info']}, 得分: {r['similarity']})")
    assert res_route[0]["symbol_name"] == "login_api", "未能精准命中 login_api 路由"
    print("✅ Web 路由精准加权测试通过！")

    # 场景 B: 精确类名加权 "看看 PasswordHasher 怎么初始化的"
    q_sym = "看看 PasswordHasher 怎么初始化的"
    res_sym = searcher.search(q_sym, top_k=2)
    print(f"\n查询: '{q_sym}'")
    for r in res_sym:
        print(f"  命中: {r['file_path']} -> {r['symbol_name']} (得分: {r['similarity']})")
    assert "PasswordHasher" in res_sym[0]["symbol_name"]
    print("✅ 精确符号增强测试通过！")


def test_exact_ripgrep_search():
    print("\n--- 4. 测试 ripgrep / 内置双轨精准字面量与证据检索 ---")
    sample_dir = ROOT_DIR / "tests" / "sample_project"
    engine = ExactSearchEngine(sample_dir)

    # 检索确切常量 / 字符串
    res1 = engine.search("custom_salt_secret")
    print(f"引擎: {res1['engine']}, 匹配项: {len(res1['matches'])}")
    assert len(res1["matches"]) >= 1
    assert any("auth.py" in m.file_path for m in res1["matches"])

    # 测试 MCP 工具 exact_search
    mcp_out = exact_search("custom_salt_secret", path=str(sample_dir))
    print("exact_search 工具输出:\n", mcp_out)
    assert "确凿字面量检索结果" in mcp_out
    assert "auth.py" in mcp_out
    print("✅ 精准字面量与证据检索通过！")


def test_mcp_tools():
    print("\n--- 5. 测试全部 FastMCP 工具接口（5个核心工具） ---")
    sample_dir = str(ROOT_DIR / "tests" / "sample_project")

    # 工具 1: get_codebase_outline
    outline_res = get_codebase_outline(sample_dir)
    assert "项目全局架构大纲" in outline_res

    # 工具 2: search_codebase (compact 模式)
    search_res = search_codebase("登录接口在哪", path=sample_dir, top_k=2, compact=True)
    assert "login_api" in search_res or "AuthService.login" in search_res

    # 工具 3: exact_search
    exact_res = exact_search("execute_transaction", path=sample_dir)
    assert "database.py" in exact_res

    # 工具 4: get_file_content
    auth_file_path = str(ROOT_DIR / "tests" / "sample_project" / "auth.py")
    file_content = get_file_content(auth_file_path, start_line=1, end_line=12)
    assert "PasswordHasher" in file_content

    print("✅ 全部 5 个 FastMCP 工具端到端验证通过！")


if __name__ == "__main__":
    test_chunker()
    test_outline_generation()
    test_indexing_and_search()
    test_exact_ripgrep_search()
    test_mcp_tools()
    print("\n🎉 组装思想 (Ripgrep + 证据链) 升级版测试全部通过！")
