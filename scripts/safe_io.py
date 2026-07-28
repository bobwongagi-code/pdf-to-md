"""Small file-safety helpers for user-visible artifacts."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX only
    msvcrt = None


class OutputPathError(ValueError):
    """Raised when an output path would overwrite protected data."""


def _resolved(path: Path) -> Path:
    # Keep the final path itself intact so a dangling or existing symlink is
    # rejected/replaced as an output entry instead of being followed silently.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _collision_key(path: Path) -> str:
    """Return a conservative path key for case-insensitive filesystems."""
    key = os.path.realpath(str(_resolved(path)))
    if sys.platform == "darwin" or os.name == "nt":
        return key.casefold()
    return os.path.normcase(key)


def _path_exists(path: Path) -> bool:
    """Like Path.exists(), but also detects dangling symlinks."""
    return os.path.lexists(str(path))


def paths_collide(first: Path, second: Path) -> bool:
    first_resolved = _resolved(first)
    second_resolved = _resolved(second)
    if _collision_key(first_resolved) == _collision_key(second_resolved):
        return True
    try:
        return os.path.samefile(first_resolved, second_resolved)
    except OSError:
        return False


def reject_collisions(
    output_path: Path,
    protected_paths: Iterable[Path],
    *,
    force: bool = False,
    label: str = "output",
    protected_label: str = "input",
) -> Path:
    output_path = _resolved(output_path)
    for protected_path in protected_paths:
        if paths_collide(output_path, protected_path):
            raise OutputPathError(f"{label} path collides with {protected_label}: {output_path}")
    if _path_exists(output_path) and not force:
        raise OutputPathError(f"{label} already exists: {output_path} (use --force to overwrite)")
    return output_path


@contextmanager
def file_lock(lock_path: Path):
    """Hold an advisory lock that works on the supported desktop platforms."""
    lock_path = _resolved(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        try:
            lock_path.chmod(0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            lock_file.seek(0)
            lock_file.write(b"0")
            lock_file.flush()
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield lock_file
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def atomic_replace(temp_path: Path, output_path: Path, *, force: bool = False) -> Path:
    """Commit a prepared file in the same directory as the target."""
    temp_path = _resolved(temp_path)
    output_path = _resolved(output_path)
    if _path_exists(output_path) and not force:
        raise OutputPathError(f"output already exists: {output_path} (use --force to overwrite)")
    if temp_path.parent != output_path.parent:
        raise OutputPathError("temporary file must be in the output directory")
    os.replace(temp_path, output_path)
    try:
        dir_fd = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass
    return output_path


def atomic_replace_directory(
    staging_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> Path:
    """Atomically publish a prepared directory, with rollback on replacement failure."""
    staging_path = _resolved(staging_path)
    output_path = _resolved(output_path)
    if staging_path.is_symlink() or not staging_path.is_dir():
        raise OutputPathError(f"staging directory does not exist: {staging_path}")
    if staging_path.parent != output_path.parent:
        raise OutputPathError("staging directory must be beside the output directory")
    if _path_exists(output_path) and not force:
        raise OutputPathError(
            f"output directory already exists: {output_path} (use --force to overwrite)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = output_path.parent / f".{output_path.name}.previous-{os.getpid()}-{uuid.uuid4().hex}"
    had_output = _path_exists(output_path)
    moved_output = False
    try:
        if had_output:
            os.replace(output_path, backup_path)
            moved_output = True
        os.replace(staging_path, output_path)
    except Exception:
        if moved_output and _path_exists(output_path):
            if output_path.is_dir() and not output_path.is_symlink():
                shutil.rmtree(output_path, ignore_errors=True)
            else:
                output_path.unlink(missing_ok=True)
        if had_output and _path_exists(backup_path):
            os.replace(backup_path, output_path)
        raise
    finally:
        if _path_exists(backup_path):
            if backup_path.is_dir() and not backup_path.is_symlink():
                shutil.rmtree(backup_path, ignore_errors=True)
            else:
                backup_path.unlink(missing_ok=True)
    return output_path


def atomic_write(
    output_path: Path,
    writer: Callable[[object], None],
    *,
    mode: str,
    force: bool = False,
    permissions: Optional[int] = 0o600,
) -> Path:
    output_path = _resolved(output_path)
    if _path_exists(output_path) and not force:
        raise OutputPathError(f"output already exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    temp_path = Path(temp_name)
    try:
        if permissions is not None:
            os.fchmod(fd, permissions)
        open_kwargs = {"encoding": "utf-8"} if "b" not in mode else {}
        with os.fdopen(fd, mode, **open_kwargs) as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        return atomic_replace(temp_path, output_path, force=force)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def atomic_write_text(output_path: Path, content: str, *, force: bool = False) -> Path:
    return atomic_write(
        output_path,
        lambda f: f.write(content),
        mode="w",
        force=force,
    )


def atomic_write_json(
    output_path: Path,
    payload: object,
    *,
    indent: Optional[int] = None,
    force: bool = False,
) -> Path:
    return atomic_write(
        output_path,
        lambda f: json.dump(payload, f, indent=indent, ensure_ascii=False),
        mode="w",
        force=force,
    )
