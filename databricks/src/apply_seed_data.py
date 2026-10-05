# Databricks notebook source
# MAGIC %md
# MAGIC # EDP — Apply Seed Data from YAML
# MAGIC
# MAGIC Reads `config/data_platform/seed_data/*.yml` files and applies each one to the
# MAGIC corresponding config table using `MERGE INTO` (upsert semantics).
# MAGIC
# MAGIC ## Seed YAML format
# MAGIC ```yaml
# MAGIC target_table: config.source_master             # schema.table
# MAGIC merge_keys: [source_master_id]                 # columns used for the MERGE ON condition
# MAGIC rows:
# MAGIC   - source_master_id: sm_amazon_ads_example
# MAGIC     source_system_code: amazon_ads
# MAGIC     source_system_name: Amazon Advertising
# MAGIC     ingestion_pattern_type: API
# MAGIC     effective_start_ts: "2026-01-01T00:00:00"
# MAGIC     created_at: "2026-08-04T00:00:00"
# MAGIC     created_by: edp-platform
# MAGIC ```
# MAGIC
# MAGIC | Parameter       | Description |
# MAGIC |-----------------|-------------|
# MAGIC | `catalog`       | Unity Catalog name supplied by the bundle target |
# MAGIC | `seed_data_dir` | Workspace path to `config/data_platform/seed_data/` directory |

# COMMAND ----------

import sys
import os
import re
_source_dir = os.path.dirname(
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
sys.path.insert(0, "/Workspace" + _source_dir)
from yaml_utils import load_yaml
from target_guard import check_no_catalog_override, check_target
from workspace_paths import require_bundle_directory
from pathlib import Path
from pyspark.sql.types import StringType, StructField, StructType

dbutils.widgets.text("catalog",      "", "Unity Catalog name")
dbutils.widgets.text("bronze_catalog", "", "Bronze catalog")
dbutils.widgets.text("environment", "", "Environment")
dbutils.widgets.text("expected_host", "", "Expected workspace host")
dbutils.widgets.text("seed_data_dir", "",        "Workspace path to config/data_platform/seed_data/")

catalog      = dbutils.widgets.get("catalog")
environment = dbutils.widgets.get("environment")
check_target(environment, catalog, dbutils.widgets.get("bronze_catalog"),
             spark.conf.get("spark.databricks.workspaceUrl"),
             dbutils.widgets.get("expected_host"))
seed_data_dir = dbutils.widgets.get("seed_data_dir")

seed_data_dir = require_bundle_directory(seed_data_dir, "seed_data_dir")

spark.sql(f"USE CATALOG {catalog}")
print(f"catalog={catalog!r}  seed_data_dir={seed_data_dir!r}")

# COMMAND ----------

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(identifier: str, label: str) -> str:
    if not isinstance(identifier, str) or not identifier:
        raise ValueError(f"{label} must be a non-empty string.")
    if not IDENTIFIER_RE.match(identifier):
        raise ValueError(f"{label}={identifier!r} is invalid.")
    return identifier


def _qi(identifier: str, label: str = "identifier") -> str:
    return f"`{_validate_identifier(identifier, label)}`"


def _qfqn(fqn: str) -> str:
    parts = str(fqn).split(".")
    if len(parts) < 3:
        raise ValueError(f"target table must be catalog.schema.table, got {fqn!r}")
    return ".".join(_qi(p, "target table part") for p in parts)


def _row_columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in cols:
                cols.append(key)
    return cols


def _validate_seed(seed: dict, file_name: str) -> tuple[str, str, list[str], list[dict]]:
    if not isinstance(seed, dict):
        raise ValueError(f"{file_name}: YAML root must be a mapping.")

    check_no_catalog_override(seed, file_name)
    target_catalog = catalog
    target_table = seed.get("target_table")
    merge_keys = seed.get("merge_keys")
    rows = seed.get("rows") or []

    _validate_identifier(str(target_catalog), "catalog")
    if not target_table:
        raise ValueError(f"{file_name}: missing required field 'target_table'.")
    if not isinstance(merge_keys, list) or not merge_keys:
        raise ValueError(f"{file_name}: 'merge_keys' must be a non-empty list.")
    if not isinstance(rows, list):
        raise ValueError(f"{file_name}: 'rows' must be a list.")

    parts = str(target_table).split(".")
    if len(parts) != 2:
        raise ValueError(f"{file_name}: 'target_table' must be schema.table.")
    _validate_identifier(parts[0], "target schema")
    _validate_identifier(parts[1], "target table")

    dedup_keys: list[str] = []
    for key in merge_keys:
        normalized = _validate_identifier(str(key), "merge key")
        if normalized not in dedup_keys:
            dedup_keys.append(normalized)

    return str(target_catalog), str(target_table), dedup_keys, rows


def apply_seed_file(path: Path) -> None:
    seed = load_yaml(path)
    for row in seed.get("rows", []):
        if "environment" in row:
            raise ValueError(f"{path.name}: environment is supplied by the bundle target")
        row["environment"] = environment

    target_catalog, target_table, merge_keys, rows = _validate_seed(seed, path.name)
    target_fqn = f"{target_catalog}.{target_table}"

    if not rows:
        print(f"[apply_seed_data] {path.name}: no rows — skipping.")
        return

    # Build a DataFrame from the YAML rows, cast to match target table schema
    all_cols = _row_columns(rows)
    for col in all_cols:
        _validate_identifier(col, "row column")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path.name}: each item in 'rows' must be a mapping.")

    str_rows = [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in rows]
    input_schema = StructType([StructField(col, StringType(), True) for col in all_cols])
    row_values = [tuple(r.get(col) for col in all_cols) for r in str_rows]
    df = spark.createDataFrame(row_values, schema=input_schema)
    target_schema = spark.table(target_fqn).schema
    target_cols = {field.name for field in target_schema}

    unknown_cols = [col for col in all_cols if col not in target_cols]
    if unknown_cols:
        raise ValueError(
            f"{path.name}: these columns are not in target table {target_fqn}: {unknown_cols}"
        )
    missing_key_cols = [key for key in merge_keys if key not in all_cols]
    if missing_key_cols:
        raise ValueError(f"{path.name}: merge_keys missing in rows: {missing_key_cols}")

    for field in target_schema:
        if field.name in df.columns:
            df = df.withColumn(field.name, df[field.name].cast(field.dataType))

    df.createOrReplaceTempView("_seed_src")

    target_fqn_sql = _qfqn(target_fqn)
    join_cond   = " AND ".join(f"t.{_qi(k, 'merge key')} = s.{_qi(k, 'merge key')}" for k in merge_keys)
    update_cols = [c for c in all_cols if c not in merge_keys]
    update_set  = ", ".join(f"t.{_qi(c, 'column')} = s.{_qi(c, 'column')}" for c in update_cols)
    insert_cols = ", ".join(_qi(c, "column") for c in all_cols)
    insert_vals = ", ".join(f"s.{_qi(c, 'column')}" for c in all_cols)

    merge_sql = f"""
    MERGE INTO {target_fqn_sql} t
    USING _seed_src s
    ON {join_cond}
    {"WHEN MATCHED THEN UPDATE SET " + update_set if update_set else ""}
    WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """

    spark.sql(merge_sql)
    print(f"[apply_seed_data] {path.name}: {len(rows)} row(s) merged into {target_fqn}.")

# COMMAND ----------

seed_paths = sorted(Path(seed_data_dir).glob("*.yml"))

if not seed_paths:
    raise FileNotFoundError(f"No seed YAML files found in {seed_data_dir}")
else:
    for p in seed_paths:
        apply_seed_file(p)
    print(f"\n[apply_seed_data] Done — {len(seed_paths)} file(s) processed.")
