"""缓存空间管理与自动化清理模块 (Cache Manager & Auto-Pruning)

解决开发人员长期索引多代码库、CI/CD 跑测产生的磁盘空间积压问题：
1. 缓存清单与磁盘占用统计 (list / status)
2. 孤儿缓存智能识别 (源目录已不存在的幽灵缓存)
3. 灵活清理机制 (按天数、按孤儿、按指定仓库、或全量重置)
4. 磁盘配额防护与自动熔断 (Auto-Prune)
"""

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from code_search_mcp.config import get_cache_root, get_db_dir, get_repo_hash


@dataclass
class CacheEntry:
    hash_id: str
    db_path: Path
    repo_path: Optional[str]
    repo_exists: bool
    size_bytes: int
    indexed_files: int
    indexed_chunks: int
    created_at: float
    last_updated: float

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)


def get_dir_size(path: Path) -> int:
    """递归计算目录总大小（字节）"""
    total = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += get_dir_size(Path(entry.path))
            except Exception:
                pass
    except Exception:
        pass
    return total


class CacheManager:
    """本地索引缓存管理器"""

    def __init__(self, db_root: Optional[Path] = None):
        self.db_root = db_root or get_db_dir()

    def list_entries(self) -> List[CacheEntry]:
        """扫描并解析所有已索引代码库的缓存状态"""
        entries: List[CacheEntry] = []
        if not self.db_root.exists():
            return entries

        for item in self.db_root.iterdir():
            if not item.is_dir():
                continue

            meta_file = item / "meta.json"
            repo_path = None
            repo_exists = False
            files_count = 0
            chunks_count = 0
            c_time = item.stat().st_ctime
            m_time = item.stat().st_mtime

            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    repo_path = meta.get("repo_path")
                    files_count = meta.get("indexed_files", 0)
                    chunks_count = meta.get("indexed_chunks", 0)
                    c_time = meta.get("created_at", c_time)
                    m_time = meta.get("last_updated", m_time)
                    if repo_path and Path(repo_path).exists():
                        repo_exists = True
                except Exception:
                    pass

            size = get_dir_size(item)
            entries.append(
                CacheEntry(
                    hash_id=item.name,
                    db_path=item,
                    repo_path=repo_path,
                    repo_exists=repo_exists,
                    size_bytes=size,
                    indexed_files=files_count,
                    indexed_chunks=chunks_count,
                    created_at=c_time,
                    last_updated=m_time,
                )
            )

        entries.sort(key=lambda x: x.last_updated, reverse=True)
        return entries

    def get_summary(self) -> Dict[str, Any]:
        """获取全局缓存概览统计"""
        entries = self.list_entries()
        total_size = sum(e.size_bytes for e in entries)
        orphaned = [e for e in entries if not e.repo_exists]
        orphaned_size = sum(e.size_bytes for e in orphaned)

        return {
            "total_entries": len(entries),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "orphaned_entries": len(orphaned),
            "orphaned_size_bytes": orphaned_size,
            "orphaned_size_mb": round(orphaned_size / (1024 * 1024), 2),
            "cache_root": str(self.db_root),
        }

    def clean(
        self,
        all_caches: bool = False,
        orphaned_only: bool = False,
        older_than_days: Optional[int] = None,
        target_repo: Optional[str | Path] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """执行清理操作

        Args:
            all_caches: 是否全量清空所有代码库缓存
            orphaned_only: 仅清理源项目已从磁盘删除的孤儿数据
            older_than_days: 清理超过 N 天未更新的缓存
            target_repo: 仅清理指定目标代码库的缓存
            dry_run: 仅模拟计算，不实际删除文件
        """
        entries = self.list_entries()
        to_delete: List[CacheEntry] = []
        now = time.time()

        target_hash = get_repo_hash(target_repo) if target_repo else None

        for e in entries:
            # 1. 指定目标代码库
            if target_hash:
                if e.hash_id == target_hash:
                    to_delete.append(e)
                continue

            # 2. 全量清理
            if all_caches:
                to_delete.append(e)
                continue

            # 3. 仅清理孤儿
            if orphaned_only:
                if not e.repo_exists:
                    to_delete.append(e)
                continue

            # 4. 按天数清理
            if older_than_days is not None:
                cutoff = now - (older_than_days * 86400)
                if e.last_updated < cutoff:
                    to_delete.append(e)
                continue

            # 默认：如果未指定任何参数，安全清理孤儿缓存
            if not e.repo_exists:
                to_delete.append(e)

        freed_bytes = sum(e.size_bytes for e in to_delete)
        deleted_count = 0
        failed_count = 0

        if not dry_run:
            for e in to_delete:
                try:
                    shutil.rmtree(e.db_path, ignore_errors=True)
                    deleted_count += 1
                except Exception:
                    failed_count += 1

        return {
            "dry_run": dry_run,
            "matched_entries": len(to_delete),
            "freed_bytes": freed_bytes,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "deleted_items": [
                {
                    "hash": e.hash_id,
                    "repo_path": e.repo_path or "<未知/已删除>",
                    "size_mb": e.size_mb,
                }
                for e in to_delete
            ],
        }

    def auto_prune_if_needed(self, max_total_mb: float = 3000.0) -> Optional[Dict[str, Any]]:
        """配额防护：若总缓存体积超出阈值 (默认 3GB)，自动执行 LRU 淘汰与孤儿清理"""
        summary = self.get_summary()
        if summary["total_size_mb"] <= max_total_mb:
            return None

        # 先清理孤儿缓存
        res = self.clean(orphaned_only=True)
        # 若依然超出配额，按 LRU 顺序清理最久未访问的旧缓存直至恢复安全配额
        entries = self.list_entries()
        current_mb = sum(e.size_bytes for e in entries) / (1024 * 1024)
        if current_mb > max_total_mb:
            entries.sort(key=lambda x: x.last_updated)  # 最久未更新排在前
            for e in entries:
                if current_mb <= max_total_mb:
                    break
                shutil.rmtree(e.db_path, ignore_errors=True)
                current_mb -= e.size_mb

        return res
