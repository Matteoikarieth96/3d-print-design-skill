"""safeio: the only way the skill's scripts write files or echo untrusted text (stdlib only).

atomic_write(path, data)
    Refuses to write through a symlink (or onto anything that is not a regular
    file), writes a new temp file next to the target with O_CREAT | O_EXCL
    (mode 0o644, umask applies), flushes it, then os.replace()s it over the
    target. rename() replaces a directory entry and never follows a link, so
    even a symlink planted between the check and the rename is replaced, not
    followed: the link's target is never written.

safe_text(value, limit)
    Strips C0/C1 control characters and other Unicode "C" categories (format
    characters such as bidi overrides and zero-width spaces, surrogates,
    private use, unassigned) before a file name or request path is printed to
    a terminal or log, and truncates it.
"""
from __future__ import annotations

import os
import secrets
import stat
import unicodedata
from pathlib import Path
from typing import Union


def atomic_write(path: Union[str, Path], data: Union[bytes, str], mode: int = 0o644) -> Path:
    path = Path(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(f"refusing to write through a symlink: {safe_text(str(path))}")
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"refusing to overwrite something that is not a regular file: {safe_text(str(path))}")
    parent = path.parent if str(path.parent) else Path(".")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    for _ in range(20):
        tmp = parent / f".{path.name[:80]}.{secrets.token_hex(6)}.tmp"
        try:
            fd = os.open(tmp, flags, mode)
            break
        except FileExistsError:
            continue
    else:  # pragma: no cover
        raise OSError(f"could not create a temporary file in {safe_text(str(parent))}")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def safe_text(value, limit: int = 200) -> str:
    text = str(value)
    cleaned = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3] + "..."
    return cleaned
