import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from code_search_mcp.config import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_FILES
from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.multilang_parser import EXTENSION_LANG_MAP

try:
    from watchfiles import Change, DefaultFilter, watch
    HAS_WATCHFILES = True
except ImportError:
    HAS_WATCHFILES = False


class CodeFilter:
    """过滤监控目录与文件，忽略依赖库、缓存文件与非源代码"""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        self.supported_exts = set(EXTENSION_LANG_MAP.keys())

    def __call__(self, change: Any, path_str: str) -> bool:
        p = Path(path_str)
        # 忽略隐藏文件或忽略目录
        for part in p.parts:
            if part in DEFAULT_IGNORE_DIRS or (part.startswith(".") and part != "."):
                return False

        # 仅关注支持的编程语言后缀
        ext = p.suffix.lower()
        if ext not in self.supported_exts:
            return False

        # 忽略临时文件
        if p.name.startswith("~") or p.name.startswith(".#") or p.name in DEFAULT_IGNORE_FILES:
            return False

        return True


class RepoWatcher:
    """代码库实时热监听器 (启发自 CodeGraph)

    核心机制:
    1. 采用操作系统原生事件通知 (Windows ReadDirectoryChangesW / Linux inotify / macOS FSEvents)
    2. 防抖聚合 (Debounce 1500ms): 编辑器快速连续保存时自动合并为单次更新
    3. 增量热更新: 单文件变更仅重新解析该文件，0.3s 内完成 AST 抽取与向量追加
    4. 零输出污染: 所有通知严格流向 sys.stderr，绝不破坏 MCP JSON-RPC 通信
    """

    def __init__(self, repo_path: str | Path, debounce_ms: int = 1500):
        self.repo_path = Path(repo_path).resolve()
        self.debounce_ms = debounce_ms
        self.indexer = CodeIndexer(self.repo_path)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.is_running = False
        self.last_sync_time: Optional[float] = None
        self.sync_count = 0
        self.recent_events: List[Dict[str, Any]] = []

    def start(self) -> bool:
        """在后台守护线程中启动文件监听"""
        if self.is_running:
            return True

        if not self.repo_path.exists() or not self.repo_path.is_dir():
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name=f"Watcher-{self.repo_path.name}", daemon=True)
        self._thread.start()
        self.is_running = True
        sys.stderr.write(f"[code-search-mcp] [热监听] 已启动后台文件监控: {self.repo_path} (防抖: {self.debounce_ms}ms)\n")
        return True

    def stop(self):
        """停止文件监听"""
        if not self.is_running:
            return
        self._stop_event.set()
        self.is_running = False
        sys.stderr.write(f"[code-search-mcp] [热监听] 已停止后台文件监控: {self.repo_path}\n")

    def _run_loop(self):
        if HAS_WATCHFILES:
            self._run_watchfiles_loop()
        else:
            self._run_fallback_polling_loop()

    def _run_watchfiles_loop(self):
        code_filter = CodeFilter(self.repo_path)
        try:
            for changes in watch(
                self.repo_path,
                watch_filter=code_filter,
                debounce=self.debounce_ms,
                stop_event=self._stop_event,
            ):
                if self._stop_event.is_set():
                    break
                self._handle_changes(changes)
        except Exception as e:
            sys.stderr.write(f"[code-search-mcp] [热监听异常] watchfiles 监控失败: {e}\n")
            self.is_running = False

    def _run_fallback_polling_loop(self):
        """降级方案：当未安装 watchfiles 时，使用轻量 mtime 轮询"""
        supported_exts = set(EXTENSION_LANG_MAP.keys())
        last_mtimes: Dict[str, float] = {}

        # 初始快照
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in supported_exts:
                    full_p = os.path.join(root, f)
                    try:
                        last_mtimes[full_p] = os.stat(full_p).st_mtime
                    except Exception:
                        pass

        while not self._stop_event.is_set():
            time.sleep(self.debounce_ms / 1000.0)
            changed_files: Set[str] = set()

            current_files: Set[str] = set()
            for root, dirs, files in os.walk(self.repo_path):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
                for f in files:
                    ext = Path(f).suffix.lower()
                    if ext in supported_exts:
                        full_p = os.path.join(root, f)
                        current_files.add(full_p)
                        try:
                            mtime = os.stat(full_p).st_mtime
                            if full_p not in last_mtimes or mtime > last_mtimes[full_p]:
                                changed_files.add(full_p)
                                last_mtimes[full_p] = mtime
                        except Exception:
                            pass

            # 检查删除的文件
            deleted_files = set(last_mtimes.keys()) - current_files
            for df in deleted_files:
                changed_files.add(df)
                del last_mtimes[df]

            if changed_files:
                synthetic_changes = {(None, f) for f in changed_files}
                self._handle_changes(synthetic_changes)

    def _handle_changes(self, changes: Any):
        t0 = time.perf_counter()
        changed_paths = set()
        for item in changes:
            p_str = item[1] if isinstance(item, (tuple, list)) else str(item)
            changed_paths.add(p_str)

        if not changed_paths:
            return

        for path_str in changed_paths:
            file_path = Path(path_str)
            try:
                rel_path = str(file_path.relative_to(self.repo_path)).replace("\\", "/")
            except ValueError:
                rel_path = str(file_path).replace("\\", "/")

            res = self.indexer.index_file_incremental(file_path)
            status_text = "增量更新" if res.get("status") == "updated" else "移除索引"
            chunks_num = res.get("chunks_count", 0)

            event = {
                "time": time.strftime("%H:%M:%S"),
                "file": rel_path,
                "status": res.get("status"),
                "chunks": chunks_num,
            }
            self.recent_events.append(event)
            if len(self.recent_events) > 20:
                self.recent_events.pop(0)

            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000
            sys.stderr.write(
                f"[code-search-mcp] [热更新] {rel_path} ({status_text}, {chunks_num} 块代码) -> 耗时 {elapsed_ms:.1f}ms\n"
            )

        self.last_sync_time = time.time()
        self.sync_count += len(changed_paths)


# 全局多代码库监听器管理器
_watchers_lock = threading.Lock()
_active_watchers: Dict[str, RepoWatcher] = {}


def get_or_create_watcher(repo_path: str | Path, auto_start: bool = True) -> RepoWatcher:
    """获取或为目标仓库创建单例热监听器"""
    resolved = str(Path(repo_path).resolve())
    with _watchers_lock:
        if resolved not in _active_watchers:
            watcher = RepoWatcher(resolved)
            _active_watchers[resolved] = watcher
        watcher = _active_watchers[resolved]
        if auto_start and not watcher.is_running:
            watcher.start()
        return watcher


def get_all_watchers_status() -> List[Dict[str, Any]]:
    """获取所有活跃代码库的监控状态"""
    with _watchers_lock:
        results = []
        for path_str, watcher in _active_watchers.items():
            results.append(
                {
                    "repo_path": path_str,
                    "is_running": watcher.is_running,
                    "sync_count": watcher.sync_count,
                    "last_sync": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(watcher.last_sync_time))
                    if watcher.last_sync_time
                    else "未发生同步",
                    "recent_events": list(watcher.recent_events),
                }
            )
        return results
