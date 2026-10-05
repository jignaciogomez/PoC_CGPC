"""Fail closed when a job is pointed at the wrong workspace or catalog."""

from urllib.parse import urlparse


TARGET_CATALOGS = {
    "dev": ("dev_scratch_ca", "dev_bronze_ca"),
    "qa": ("edp_qa", "qa_bronze_ca"),
}


def normalize_host(host: str) -> str:
    if host and "://" not in host:
        host = "https://" + host
    parsed = urlparse(host.rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise ValueError("Workspace host must be an HTTPS origin")
    return f"https://{parsed.netloc.lower()}"


def check_target(environment: str, platform_catalog: str, bronze_catalog: str,
                 actual_host: str, expected_host: str) -> None:
    expected = TARGET_CATALOGS.get(environment)
    if expected is None:
        raise ValueError(f"Unsupported deployment target: {environment!r}")
    if (platform_catalog, bronze_catalog) != expected:
        raise ValueError(f"{environment} requires catalogs {expected}, got "
                         f"{(platform_catalog, bronze_catalog)}")
    if normalize_host(actual_host) != normalize_host(expected_host):
        raise ValueError("The running Databricks workspace does not match this bundle target")


def check_no_catalog_override(document: dict, filename: str) -> None:
    if "catalog" in document:
        raise ValueError(f"{filename}: catalog overrides are forbidden; use the bundle target")
