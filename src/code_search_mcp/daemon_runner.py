"""Background Daemon runner entry point."""

import argparse
import os
import sys
import traceback

from code_search_mcp.daemon import get_daemon_log_file, run_daemon_process

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="code-search-graph background daemon")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (default: random available)")
    args = parser.parse_args()

    # Child independently opens daemon.log for unbuffered logging
    log_path = get_daemon_log_file()
    try:
        log_fp = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_fp
        sys.stderr = log_fp
    except Exception:
        pass

    try:
        run_daemon_process(port=args.port)
    except Exception:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[DAEMON FATAL EXCEPTION] {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
