#!/usr/bin/env python3
"""Validate GitHub environment settings before touching a Databricks workspace."""

import os
import sys
from urllib.parse import urlparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "databricks" / "src"))
from target_guard import TARGET_CATALOGS


def host(value):
    parsed = urlparse(value.rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise ValueError("Databricks hosts must be HTTPS origins")
    return parsed.netloc.lower()


def main():
    target = sys.argv[1] if len(sys.argv) == 2 else None
    if target not in TARGET_CATALOGS:
        raise ValueError(f"Unsupported Databricks target: {target!r}")
    required = (
        "DATABRICKS_HOST", "DATABRICKS_CLIENT_ID", "SOURCE_DATABRICKS_HOST",
        "DATABRICKS_BUNDLE_VAR_workspace_host",
        "DATABRICKS_BUNDLE_VAR_landing_volume_path",
        "DATABRICKS_BUNDLE_VAR_checkpoint_path",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Missing GitHub {target.upper()} environment settings: {missing}")
    target_host = host(os.environ["DATABRICKS_HOST"])
    if target_host != host(os.environ["DATABRICKS_BUNDLE_VAR_workspace_host"]):
        raise ValueError("Bundle host and authenticated target host differ")
    if target_host == host(os.environ["SOURCE_DATABRICKS_HOST"]):
        raise ValueError("Promotion source and target must use separate Databricks workspaces")
    bronze_catalog = TARGET_CATALOGS[target][1]
    for key in ("landing_volume_path", "checkpoint_path"):
        value = os.environ[f"DATABRICKS_BUNDLE_VAR_{key}"]
        if not value.startswith(f"/Volumes/{bronze_catalog}/sales/"):
            raise ValueError(f"{key} must be inside {bronze_catalog}.sales")
    print(f"{target.upper()} workspace and bundle target settings are consistent")


if __name__ == "__main__":
    main()
