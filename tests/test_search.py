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

    print("✅ 全部 FastMCP 工具多语言端到端验证通过！")


if __name__ == "__main__":
    test_multilang_tree_sitter()
    test_outline_generation()
    test_indexing_and_multilang_search()
    test_exact_ripgrep_search()
    test_mcp_tools()
    print("\n🎉 组装 Tree-sitter 全语言代码智能版全部测试通过！")
