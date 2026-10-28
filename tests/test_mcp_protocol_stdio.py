import json
import os
import subprocess
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


def test_mcp_stdio_protocol():
    print("=" * 75)
    print("📡 测试标准 MCP JSON-RPC Stdio 协议端到端完整交互")
    print("模拟真实 Claude Desktop / Cursor / Antigravity 与 MCP 服务进程交互")
    print("=" * 75)

    python_exe = sys.executable
    cmd = [python_exe, "-m", "code_search_mcp.server"]

    # 启动 MCP Server 子进程
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT_DIR),
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    sample_dir = str((ROOT_DIR / "tests" / "sample_project").resolve()).replace("\\", "/")

    def send_request(req_obj):
        line = json.dumps(req_obj) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()

    def read_response():
        line = proc.stdout.readline()
        if not line:
            err = proc.stderr.read()
            raise RuntimeError(f"Server closed pipe unexpectedly. Stderr: {err}")
        return json.loads(line)

    try:
        # 1. 握手阶段: initialize
        print("\n[1/6] 握手请求: initialize...")
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        send_request(init_req)
        init_resp = read_response()
        assert init_resp.get("id") == 1
        assert "serverInfo" in init_resp.get("result", {})
        print(f"   ✓ 握手成功! 服务端信息: {init_resp['result']['serverInfo']}")

        # 2. 发送 initialized 通知
        send_request({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 3. 发现阶段: tools/list
        print("\n[2/6] 工具枚举: tools/list...")
        send_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_resp = read_response()
        assert tools_resp.get("id") == 2
        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        print(f"   ✓ 服务端注册工具数量: {len(tools)} 个")
        print(f"   ✓ 工具清单: {tool_names}")
        expected_tools = [
            "index_codebase",
            "get_codebase_outline",
            "search_codebase",
            "exact_search",
            "get_file_content",
            "explore_codebase",
            "get_symbol_callers",
            "get_symbol_callees",
            "get_impact_radius",
            "find_references",
            "get_watch_status",
        ]
        for exp in expected_tools:
            assert exp in tool_names, f"缺少预期工具: {exp}"
        # 验证每个工具的英文描述和 MCP annotations (readOnlyHint / destructiveHint)
        for t in tools:
            name = t["name"]
            desc = t.get("description", "")
            annotations = t.get("annotations", {})
            assert desc, f"工具 {name} 缺少描述"
            assert annotations is not None, f"工具 {name} 缺少 annotations"
            assert annotations.get("destructiveHint") is False, f"工具 {name} destructiveHint 必须为 False"
            if name == "index_codebase":
                assert annotations.get("readOnlyHint") is False, "index_codebase readOnlyHint 必须为 False"
            else:
                assert annotations.get("readOnlyHint") is True, f"工具 {name} readOnlyHint 必须为 True"
        print("   ✅ 11 项 MCP 核心工具定义、英文描述与标准 annotations 全部规范暴露！")

        # 4. 调用工具: search_codebase (向量检索)
        print("\n[3/6] JSON-RPC 调用: search_codebase...")
        send_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_codebase",
                "arguments": {
                    "query": "在线支付处理与订单退款",
                    "path": sample_dir,
                    "top_k": 2,
                },
            },
        })
        search_resp = read_response()
        assert search_resp.get("id") == 3
        content = search_resp.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        assert "PaymentGateway" in text or "refundOrder" in text
        print(f"   ✓ search_codebase 返回正常 (预览前120字符):\n     {text[:120].replace(chr(10), ' ')}...")

        # 5. 调用工具: get_impact_radius (图谱爆炸半径)
        print("\n[4/6] JSON-RPC 调用: get_impact_radius...")
        send_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_impact_radius",
                "arguments": {
                    "symbol_name": "hash_password",
                    "path": sample_dir,
                    "max_depth": 3,
                },
            },
        })
        impact_resp = read_response()
        assert impact_resp.get("id") == 4
        imp_text = impact_resp.get("result", {}).get("content", [])[0].get("text", "")
        assert "Blast-Radius" in imp_text or "爆炸半径" in imp_text
        assert "HTTP POST /api/v1/auth/login" in imp_text
        print(f"   ✓ get_impact_radius 返回正常 (命中受波及 API 路由)")

        # 6. 调用工具: explore_codebase (一键全链路探索)
        print("\n[5/6] JSON-RPC 调用: explore_codebase...")
        send_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "explore_codebase",
                "arguments": {
                    "query": "用户登录鉴权与密码哈希",
                    "path": sample_dir,
                    "top_k": 1,
                },
            },
        })
        exp_resp = read_response()
        assert exp_resp.get("id") == 5
        exp_text = exp_resp.get("result", {}).get("content", [])[0].get("text", "")
        assert "Exploration" in exp_text or "探索" in exp_text
        print(f"   ✓ explore_codebase 返回正常 (生成完整 ASCII 调用依赖树与源码)")

        # 7. 调用工具: find_references (反向引用)
        print("\n[6/6] JSON-RPC 调用: find_references...")
        send_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "find_references",
                "arguments": {
                    "symbol_or_keyword": "verify_password",
                    "path": sample_dir,
                },
            },
        })
        ref_resp = read_response()
        assert ref_resp.get("id") == 6
        ref_text = ref_resp.get("result", {}).get("content", [])[0].get("text", "")
        assert "References" in ref_text or "反向引用" in ref_text
        print(f"   ✓ find_references 返回正常")

        print("\n" + "=" * 75)
        print("🎉 恭喜！标准 MCP JSON-RPC Stdio 协议端到端测试 100% 全部通过！")
        print("=" * 75)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    test_mcp_stdio_protocol()
