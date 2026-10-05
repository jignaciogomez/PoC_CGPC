"""Resolve one explicit bundle path to the notebook filesystem."""

from pathlib import Path


def require_bundle_directory(value: str, label: str) -> Path:
    if not value:
        raise ValueError(f"{label} must be supplied by the bundle job")
    candidates = [Path(value)]
    # Workspace paths can be reported with or without the local /Workspace mount.
    # This changes only the mount prefix, never the selected bundle directory.
    if value.startswith("/") and not value.startswith("/Workspace/"):
        candidates.append(Path("/Workspace" + value))
    for path in candidates:
        if path.is_dir():
            return path
    raise FileNotFoundError(f"{label} does not exist: {value}")
