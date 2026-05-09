"""
Project archive and version-restore helpers.

The writing app is file-first, so V1.1 adds a small safety layer around files:
discover automatic versions, restore a selected backup, and create a portable
project snapshot without secrets or volatile indexes.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SNAPSHOT_DIR = "06_项目快照"

SKIP_DIR_NAMES = {
    ".git",
    ".chromadb",
    ".chromadb_test",
    ".venv",
    ".uv-cache",
    "node_modules",
    "__pycache__",
    "logs",
    "versions",
    "99_回收站",
    SNAPSHOT_DIR,
}

SKIP_FILE_NAMES = {
    ".env",
    "webui_workbench_preview.png",
}

SKIP_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite",
    ".db",
    ".zip",
}


def archive_existing(path: Path) -> Path | None:
    """备份现有的文件到同级目录的 `versions/` 文件夹下。"""
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_dir = path.parent / "versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    archived = version_dir / f"{path.stem}_{timestamp}{path.suffix}"
    shutil.copy2(path, archived)
    return archived


@dataclass(frozen=True)
class SnapshotResult:
    path: Path
    file_count: int
    total_bytes: int


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_label(label: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", (label or "").strip())
    return cleaned.strip("_")[:40]


def _resolve_inside(project_dir: Path, rel_path: str | Path) -> Path:
    root = project_dir.resolve()
    path = (root / rel_path).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"路径不在项目目录内：{rel_path}")
    return path


def _is_snapshot_candidate(project_dir: Path, path: Path, max_file_mb: int = 200) -> bool:
    rel = path.relative_to(project_dir)
    if any(part in SKIP_DIR_NAMES for part in rel.parts[:-1]):
        return False
    if path.name in SKIP_FILE_NAMES:
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.stat().st_size <= max_file_mb * 1024 * 1024


def iter_snapshot_files(project_dir: Path, max_file_mb: int = 200) -> list[Path]:
    root = project_dir.resolve()
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and _is_snapshot_candidate(root, path, max_file_mb=max_file_mb)
    ]
    return sorted(files, key=lambda p: str(p.relative_to(root)).lower())


def create_project_snapshot(project_dir: Path, label: str = "", max_file_mb: int = 200) -> SnapshotResult:
    root = project_dir.resolve()
    out_dir = root / SNAPSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{_safe_label(label)}" if _safe_label(label) else ""
    snapshot_path = out_dir / f"novel_snapshot_{_now_stamp()}{suffix}.zip"

    files = iter_snapshot_files(root, max_file_mb=max_file_mb)
    total_bytes = sum(path.stat().st_size for path in files)
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(root),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "excluded_dirs": sorted(SKIP_DIR_NAMES),
        "excluded_files": sorted(SKIP_FILE_NAMES),
        "files": [str(path.relative_to(root)).replace("\\", "/") for path in files],
    }

    with zipfile.ZipFile(snapshot_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("snapshot_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path in files:
            zf.write(path, str(path.relative_to(root)).replace("\\", "/"))

    return SnapshotResult(snapshot_path, len(files), total_bytes)


def list_snapshots(project_dir: Path) -> list[dict]:
    root = project_dir.resolve()
    out_dir = root / SNAPSHOT_DIR
    if not out_dir.exists():
        return []
    rows = []
    for path in sorted(out_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows.append({
            "rel_path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return rows


def _target_from_version_path(project_dir: Path, version_path: Path) -> Path:
    root = project_dir.resolve()
    try:
        rel = version_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("备份文件不在项目目录内") from exc
    if "versions" not in rel.parts:
        raise ValueError("只能恢复 versions/ 目录中的备份文件")
    if version_path.parent.name != "versions":
        raise ValueError("备份文件必须直接位于 versions/ 目录下")

    original_stem = re.sub(r"_\d{8}_\d{6}$", "", version_path.stem)
    return version_path.parent.parent / f"{original_stem}{version_path.suffix}"


def collect_version_backups(project_dir: Path) -> list[dict]:
    root = project_dir.resolve()
    _VENV_DIRS = {".venv", ".uv-cache", "node_modules", ".git", "__pycache__"}
    rows = []
    for path in sorted(root.rglob("versions/*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if not path.is_file():
            continue
        if _VENV_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            target = _target_from_version_path(root, path)
        except ValueError:
            continue
        rows.append({
            "rel_path": str(path.relative_to(root)),
            "target_rel_path": str(target.relative_to(root)),
            "size": path.stat().st_size,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return rows


def restore_version_backup(project_dir: Path, version_rel_path: str) -> dict:
    root = project_dir.resolve()
    version_path = _resolve_inside(root, version_rel_path)
    if not version_path.exists() or not version_path.is_file():
        raise FileNotFoundError(f"备份文件不存在：{version_rel_path}")
    target = _target_from_version_path(root, version_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    current_backup = None
    if target.exists():
        backup_dir = target.parent / "versions"
        backup_dir.mkdir(parents=True, exist_ok=True)
        current_backup = backup_dir / f"{target.stem}_pre_restore_{_now_stamp()}{target.suffix}"
        shutil.copy2(target, current_backup)

    shutil.copy2(version_path, target)
    return {
        "restored": str(target.relative_to(root)),
        "source": str(version_path.relative_to(root)),
        "current_backup": str(current_backup.relative_to(root)) if current_backup else "",
    }
