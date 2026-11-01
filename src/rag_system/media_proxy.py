"""Persistent opaque handles for remote certificate files linked from database rows."""

from __future__ import annotations

import json
import logging
import secrets
import threading
from pathlib import Path

logger = logging.getLogger(__name__)
_REGISTRY = Path(__file__).resolve().parents[2] / "data" / ".database_media_paths.json"
_PATHS: dict[str, str] = {}
_LOCK = threading.Lock()

try:
    loaded = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        _PATHS = {
            str(token): str(path)
            for token, path in loaded.items()
            if isinstance(token, str) and isinstance(path, str)
            and path.replace("\\", "/").startswith("api/v1/crew/file_upload/")
        }
except FileNotFoundError:
    pass
except (OSError, json.JSONDecodeError):
    logger.exception("Could not load the certificate media token registry")


def _save_registry() -> None:
    temporary = _REGISTRY.with_suffix(".tmp")
    try:
        _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(_PATHS), encoding="utf-8")
        temporary.replace(_REGISTRY)
    except OSError:
        logger.exception("Could not persist the certificate media token registry")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def register_media_path(path: str) -> str:
    token = secrets.token_urlsafe(24)
    with _LOCK:
        _PATHS[token] = path
        while len(_PATHS) > 5000:
            _PATHS.pop(next(iter(_PATHS)))
        _save_registry()
    return token


def resolve_media_path(token: str) -> str | None:
    with _LOCK:
        return _PATHS.get(token)
