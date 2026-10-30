"""CLI End-to-End Automated Test Suite (Test CLI Subcommands)

Covers and validates all 11 subcommands:
1. index: Index codebase
2. outline: Generate architecture outline map
3. search: Hybrid semantic search
4. exact: Ripgrep exact literal & regex search
5. explore: End-to-end surgical feature exploration
6. callers: Upstream caller tracking
7. callees: Downstream dependency tracking
8. impact: Blast radius / impact analysis
9. install: Auto-installer & client config wizard
10. cache: Index cache list & disk usage
11. clean: Cache cleanup & orphan recovery
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
    """Execute CLI command in a subprocess"""
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
    print("🧪 Running end-to-end automated tests for all CLI subcommands...")
    print("=" * 65)

    # 1. Test help
    code, out, err = run_cli_cmd(["--help"])
    assert code == 0, f"help failed: {err}"
    assert "code-search-graph" in out or "code-search-mcp" in out
    assert "Usage:" in out or "Options:" in out or "Commands:" in out
    print("✅ 1. CLI --help basic test passed")

    # 1b. Test --version
    code, out, err = run_cli_cmd(["--version"])
    assert code == 0, f"--version failed: {err}"
    assert "0.8.11" in out or "Version" in out
    print("✅ 1b. CLI --version test passed")

    # 2. Test index
    code, out, err = run_cli_cmd(["index", str(SAMPLE_REPO)])
    assert code == 0, f"index failed: {err}"
    assert "Indexing Complete" in out or "Repository" in out
    print("✅ 2. CLI index subcommand test passed")

    # 3. Test outline (positional argument, --path, and -p)
    code, out, err = run_cli_cmd(["outline", str(SAMPLE_REPO)])
    assert code == 0, f"outline positional arg failed: {err}"
    assert "auth.py" in out

    code, out, err = run_cli_cmd(["outline", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"outline --path option failed: {err}"
    assert "auth.py" in out

    code, out, err = run_cli_cmd(["outline", "-p", str(SAMPLE_REPO)])
    assert code == 0, f"outline -p option failed: {err}"
    assert "auth.py" in out
    print("✅ 3. CLI outline subcommand (positional/--path/-p) tests passed")

    # 4. Test search
    code, out, err = run_cli_cmd(["search", "user login authentication and token", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"search failed: {err}"
    assert "Search Results" in out
    print("✅ 4. CLI search hybrid retrieval test passed")

    # 5. Test exact
    code, out, err = run_cli_cmd(["exact", "hash_password", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"exact failed: {err}"
    assert "Exact Matches" in out
    print("✅ 5. CLI exact ripgrep test passed")

    # 6. Test explore
    code, out, err = run_cli_cmd(["explore", "user authentication login flow", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"explore failed: {err}"
    assert "auth" in out or "login" in out or "Trace" in out
    print("✅ 6. CLI explore surgical exploration test passed")

    # 7. Test callers
    code, out, err = run_cli_cmd(["callers", "hash_password", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"callers failed: {err}"
    assert "Callers" in out
    print("✅ 7. CLI callers test passed")

    # 8. Test callees
    code, out, err = run_cli_cmd(["callees", "AuthService.login", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"callees failed: {err}"
    assert "Callees" in out
    print("✅ 8. CLI callees test passed")

    # 9. Test impact
    code, out, err = run_cli_cmd(["impact", "hash_password", "--path", str(SAMPLE_REPO), "--depth", "2"])
    assert code == 0, f"impact failed: {err}"
    assert "hash_password" in out
    print("✅ 9. CLI impact blast radius test passed")

    # 10. Test install --help
    code, out, err = run_cli_cmd(["install", "--help"])
    assert code == 0, f"install --help failed: {err}"
    assert "--clients" in out
    print("✅ 10. CLI install wizard test passed")

    # 11. Test cache
    code, out, err = run_cli_cmd(["cache"])
    assert code == 0, f"cache failed: {err}"
    assert "Global Index Cache" in out
    print("✅ 11. CLI cache status test passed")

    # 12. Test clean --dry-run
    code, out, err = run_cli_cmd(["clean", "--dry-run"])
    assert code == 0, f"clean --dry-run failed: {err}"
    assert "Dry Run" in out
    print("✅ 12. CLI clean dry-run test passed")

    # 13. Test diff and review
    code, out, err = run_cli_cmd(["diff", "HEAD", "--path", str(SAMPLE_REPO)])
    assert code == 0, f"diff failed: {err}"
    assert "Git Diff" in out or "Review" in out or "Clean" in out
    print("✅ 13. CLI diff and review blast-radius test passed")

    # 14. Test deadcode
    code, out, err = run_cli_cmd(["deadcode", str(SAMPLE_REPO), "--json"])
    assert code == 0, f"deadcode failed: {err}"
    assert "dead_code" in out
    assert "UserService.findAll" in out
    print("✅ 14. CLI deadcode analysis test passed")

    # 15. Test ui --help
    code, out, err = run_cli_cmd(["ui", "--help"])
    assert code == 0, f"ui --help failed: {err}"
    assert "--port" in out or "--no-browser" in out
    print("✅ 15. CLI interactive Web UI command test passed")

    print("\n" + "=" * 65)
    print("🎉 Congratulations! All 15 CLI subcommand tests passed 100%!")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    test_cli_all_subcommands()
