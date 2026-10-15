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
from code_search_mcp.searcher import CodeSearcher
from code_search_mcp.server import (
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


def test_mcp_tools():
    print("\n--- 4. 测试 FastMCP 工具接口（含 outline 与 compact 模式） ---")
    sample_dir = str(ROOT_DIR / "tests" / "sample_project")

    # 工具 1: get_codebase_outline
    outline_res = get_codebase_outline(sample_dir)
    print("get_codebase_outline 预览:\n", outline_res[:200] + "...")
    assert "项目全局架构大纲" in outline_res

    # 工具 2: search_codebase (compact 模式)
    search_res = search_codebase("登录接口在哪", path=sample_dir, top_k=2, compact=True)
    print("\nsearch_codebase (compact) 输出:\n", search_res)
    assert "login_api" in search_res or "AuthService.login" in search_res

    # 工具 3: get_file_content
    auth_file_path = str(ROOT_DIR / "tests" / "sample_project" / "auth.py")
    file_content = get_file_content(auth_file_path, start_line=1, end_line=12)
    print("\nget_file_content 输出:\n", file_content)
    assert "PasswordHasher" in file_content

    print("✅ 全部 FastMCP 工具接口验证通过！")


if __name__ == "__main__":
    test_chunker()
    test_outline_generation()
    test_indexing_and_search()
    test_mcp_tools()
    print("\n🎉 进阶准确性与 Token 优化版全部测试通过！")
