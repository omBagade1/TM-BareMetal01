"""Bounded metadata listing; no shell execution or file contents."""
import os
import stat
from pathlib import Path


def checked_directory(workspace: Path, directory: str | None) -> Path:
    root = workspace.resolve(strict=True)
    path = Path(directory) if directory else root
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Directory must be inside the approved workspace")
    if not path.is_dir():
        raise ValueError("The selected path is not a directory")
    return path


def list_workspace_files(workspace: Path, directory: str, limit: int = 1000) -> dict:
    path = checked_directory(workspace, directory)
    files = []
    skipped = 0
    truncated = False
    with os.scandir(path) as entries:
        for index, entry in enumerate(entries):
            if index >= limit:
                truncated = True
                break
            try:
                info = entry.stat(follow_symlinks=False)
                # Exclude Windows reparse points as well as Unix symlinks.
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    skipped += 1
                    continue
                if stat.S_ISREG(info.st_mode):
                    files.append({"name": entry.name, "size_bytes": info.st_size})
            except OSError:
                skipped += 1
    return {"directory": str(path), "files": sorted(files, key=lambda f: f['name'].casefold()),
            "skipped": skipped, "truncated": truncated}
