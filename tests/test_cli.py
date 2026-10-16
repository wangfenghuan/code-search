"""CLI 全功能自动化测试套件 (Test CLI Subcommands End-to-End)

全面覆盖并验证 CLI 提供的 11 个子命令：
1. index: 索引代码库
2. outline: 生成架构大纲
3. search: 混合与语义检索
4. exact: ripgrep 确切字面量与正则
5. explore: 一键手术级业务探索
6. callers: 上游调用方追踪
7. callees: 下游依赖追踪
8. impact: 爆炸半径影响面分析
9. install: 一键安装配置向导
10. cache: 缓存清单与磁盘占用
11. clean: 缓存清理与孤儿数据回收
"""

import os
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).parent.parent
SAMPLE_REPO = ROOT_DIR / "tests" / "sample_project"


def run_cli_cmd(args: list[str]) -> tuple[int, str, str]:
    """通过子进程调用 CLI 命令"""
    cmd = [sys.executable, "-m", "code_search_mcp.cli"] + args
    res = subprocess.run(
        cmd,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return res.returncode, res.stdout, res.stderr


def test_cli_all_subcommands():
    print("\n" + "=" * 65)
    print("🧪 正在执行 CLI 全子命令端到端自动化测试...")
    print("=" * 65)

    # 1. 测试 help
    code, out, err = run_cli_cmd(["--help"])
    assert code == 0, f"help 失败: {err}"
    assert "code-search-mcp" in out
    print("✅ 1. CLI --help 基础测试通过")

    # 2. 测试 index
    code, out, err = run_cli_cmd(["index", str(SAMPLE_REPO)])
    assert code == 0, f"index 失败: {err}"
    assert "索引成功" in out
    print("✅ 2. CLI index 子命令测试通过")

    # 3. 测试 outline
    code, out, err = run_cli_cmd(["outline", str(SAMPLE_REPO)])
    assert code == 0, f"outline 失败: {err}"
    assert "项目全局多语言架构大纲" in out
    assert "auth.py" in out
    print("✅ 3. CLI outline 子命令测试通过")

    # 4. 测试 search
    code, out, err = run_cli_cmd(["search", "用户登录认证与密码校验", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"search 失败: {err}"
    assert "代码检索结果" in out
    print("✅ 4. CLI search 语义检索子命令测试通过")

    # 5. 测试 exact
    code, out, err = run_cli_cmd(["exact", "hash_password", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"exact 失败: {err}"
    assert "确凿字面量检索结果" in out
    print("✅ 5. CLI exact ripgrep 精准匹配子命令测试通过")

    # 6. 测试 explore
    code, out, err = run_cli_cmd(["explore", "用户登录与密码加密流程", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"explore 失败: {err}"
    assert "业务全链路手术级探索" in out
    print("✅ 6. CLI explore 手术级探索子命令测试通过")

    # 7. 测试 callers
    code, out, err = run_cli_cmd(["callers", "hash_password", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"callers 失败: {err}"
    assert "上游调用方" in out
    print("✅ 7. CLI callers 上游追踪子命令测试通过")

    # 8. 测试 callees
    code, out, err = run_cli_cmd(["callees", "AuthService.login", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"callees 失败: {err}"
    assert "下游依赖调用" in out
    print("✅ 8. CLI callees 下游追踪子命令测试通过")

    # 9. 测试 impact
    code, out, err = run_cli_cmd(["impact", "hash_password", "--path", str(SAMPLE_REPO), "--depth", "2"])
    assert code == 0, f"impact 失败: {err}"
    assert "爆炸半径/影响面分析" in out
    print("✅ 9. CLI impact 爆炸半径分析子命令测试通过")

    # 10. 测试 install --help
    code, out, err = run_cli_cmd(["install", "--help"])
    assert code == 0, f"install --help 失败: {err}"
    assert "--clients" in out
    print("✅ 10. CLI install 一键安装配置向导测试通过")

    # 11. 测试 cache list / status
    code, out, err = run_cli_cmd(["cache"])
    assert code == 0, f"cache 失败: {err}"
    assert "全局索引缓存清单" in out
    print("✅ 11. CLI cache 缓存状态查看测试通过")

    # 12. 测试 clean --dry-run
    code, out, err = run_cli_cmd(["clean", "--dry-run"])
    assert code == 0, f"clean --dry-run 失败: {err}"
    assert "模拟预览" in out
    print("✅ 12. CLI clean 缓存清理机制测试通过")

    print("\n" + "=" * 65)
    print("🎉 恭喜！全部 12 个 CLI 子命令端到端自动化测试 100% 全部通过！")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    test_cli_all_subcommands()
