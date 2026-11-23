"""Helpers for resolving Hugging Face model snapshots without network access."""

from __future__ import annotations

from pathlib import Path


class ModelNotCachedError(RuntimeError):
    """A requested model is not present in the local Hugging Face cache."""


def resolve_local_snapshot(model_name: str, cache_dir: Path) -> Path:
    """Return the newest cached snapshot for a model, without downloading it."""
    repository = "models--" + model_name.replace("/", "--")
    roots = (Path(cache_dir), Path(cache_dir) / "hub")
    candidates = [
        snapshot
        for root in roots
        for snapshot in (root / repository / "snapshots").glob("*")
        if snapshot.is_dir() and (snapshot / "config.json").is_file()
    ]
    if not candidates:
        raise ModelNotCachedError(
            f"Model '{model_name}' is not present in the local cache at "
            f"{cache_dir}. No download was attempted."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)
