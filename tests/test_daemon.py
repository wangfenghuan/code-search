import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from code_search_mcp.daemon import DaemonClient, start_daemon, stop_daemon, get_daemon_status

ROOT_DIR = Path(__file__).parent.parent
SAMPLE_REPO = ROOT_DIR / "tests" / "sample_project"


def test_daemon_full_lifecycle_and_ipc_calls():
    # 1. Clean stop before test
    stop_daemon()
    time.sleep(0.3)

    client = DaemonClient()
    assert not client.is_running(), "Daemon should initially be stopped"

    # 2. Start daemon
    ok, msg, info = start_daemon()
    assert ok, f"Failed to start daemon: {msg}"
    assert info is not None
    assert info.get("pid", 0) > 0
    assert info.get("port", 0) > 0

    assert client.is_running(), "Daemon client should report running"

    # 3. Check status
    status = get_daemon_status()
    assert status is not None
    assert status.get("status") == "running"
    assert status.get("pid") == info.get("pid")

    repo_str = str(SAMPLE_REPO.resolve())

    # 4. Call /api/callers
    t0 = time.perf_counter()
    callers_res = client.call("/api/callers", {"path": repo_str, "symbol_name": "verify_password"})
    dt_callers = (time.perf_counter() - t0) * 1000
    assert callers_res is not None
    assert "callers" in callers_res
    print(f"✓ callers IPC latency: {dt_callers:.2f}ms")

    # 5. Call /api/callees
    t0 = time.perf_counter()
    callees_res = client.call("/api/callees", {"path": repo_str, "symbol_name": "AuthService.login"})
    dt_callees = (time.perf_counter() - t0) * 1000
    assert callees_res is not None
    assert "callees" in callees_res
    print(f"✓ callees IPC latency: {dt_callees:.2f}ms")

    # 6. Call /api/impact
    impact_res = client.call("/api/impact", {"path": repo_str, "symbol_name": "hash_password", "depth": 2})
    assert impact_res is not None
    assert "total_impacted_symbols" in impact_res

    # 7. Call /api/deadcode
    dead_res = client.call("/api/deadcode", {"path": repo_str, "limit": 20})
    assert dead_res is not None
    assert "dead_code" in dead_res
    assert dead_res.get("total_candidates", 0) > 0

    # 8. Call /api/outline
    outline_res = client.call("/api/outline", {"path": repo_str, "max_depth": 2})
    assert outline_res is not None
    assert outline_res.get("status") == "success"

    # 9. Call /api/exact
    exact_res = client.call("/api/exact", {"path": repo_str, "pattern": "hash_password"})
    assert exact_res is not None
    assert "matches" in exact_res or "total_matches" in exact_res

    # 10. Clean stop daemon
    ok_stop, msg_stop = stop_daemon()
    assert ok_stop, f"Failed to stop daemon: {msg_stop}"
    time.sleep(0.3)
    assert not client.is_running(), "Daemon should report stopped after stop"


if __name__ == "__main__":
    test_daemon_full_lifecycle_and_ipc_calls()
    print("All daemon tests passed successfully!")
