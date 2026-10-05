# Databricks notebook source
# MAGIC %md
# MAGIC # EDP - Apply DML from YAML
# MAGIC
# MAGIC Applies DML statements defined in `config/data_platform/dml/*.yml`.
# MAGIC The bundle target supplies the catalog and environment.
# MAGIC
# MAGIC Supported operations:
# MAGIC - `insert`: append rows
# MAGIC - `update`: update existing rows matched by keys
# MAGIC - `upsert`: merge (update + insert)
# MAGIC
# MAGIC YAML format:
# MAGIC ```yaml
# MAGIC operation: upsert                # insert | update | upsert (default: upsert)
# MAGIC target_table: config.source_master
# MAGIC match_keys: [source_master_id]   # required for update/upsert
# MAGIC rows:
# MAGIC   - source_master_id: sm_amazon_ads_example
# MAGIC     source_system_name: Amazon Ads
# MAGIC ```

import os
import re
import sys
import uuid
from pathlib import Path

_source_dir = os.path.dirname(
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
sys.path.insert(0, "/Workspace" + _source_dir)

from yaml_utils import load_yaml
from target_guard import check_no_catalog_override, check_target
from workspace_paths import require_bundle_directory
from pyspark.sql.types import StringType, StructField, StructType


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


def _normalize_operation(spec: dict) -> str:
    return str(spec.get("operation", "upsert")).strip().lower()


def _row_columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in cols:
                cols.append(key)
    return cols


def _rows_df_casted(target_fqn: str, rows: list[dict]):
    cols = _row_columns(rows)
    str_rows = []
    for row in rows:
        str_row = {col: (str(row.get(col)) if row.get(col) is not None else None) for col in cols}
        str_rows.append(str_row)

    input_schema = StructType([StructField(col, StringType(), True) for col in cols])
    row_values = [tuple(r.get(col) for col in cols) for r in str_rows]
    df = spark.createDataFrame(row_values, schema=input_schema)
    target_schema = spark.table(target_fqn).schema
    for field in target_schema:
        if field.name in df.columns:
            df = df.withColumn(field.name, df[field.name].cast(field.dataType))

    return df, cols


def _sql_join(keys: list[str]) -> str:
    return " AND ".join(f"t.{_qi(k, 'match key')} = s.{_qi(k, 'match key')}" for k in keys)


def _run_insert(target_fqn: str, cols: list[str], view_name: str) -> None:
    target_fqn_sql = _qfqn(target_fqn)
    insert_cols = ", ".join(_qi(c, "column") for c in cols)
    insert_vals = ", ".join(f"s.{_qi(c, 'column')}" for c in cols)
    sql = (
        f"INSERT INTO {target_fqn_sql} ({insert_cols}) "
        f"SELECT {insert_vals} FROM {view_name} s"
    )
    spark.sql(sql)


def _run_update(target_fqn: str, keys: list[str], cols: list[str], view_name: str) -> None:
    target_fqn_sql = _qfqn(target_fqn)
    update_cols = [c for c in cols if c not in keys]
    if not update_cols:
        print(f"[apply_dml] {target_fqn}: update skipped (no non-key columns found).")
        return

    join_cond = _sql_join(keys)
    update_set = ", ".join(f"t.{_qi(c, 'column')} = s.{_qi(c, 'column')}" for c in update_cols)
    sql = f"""
    MERGE INTO {target_fqn_sql} t
    USING {view_name} s
    ON {join_cond}
    WHEN MATCHED THEN UPDATE SET {update_set}
    """
    spark.sql(sql)


def _run_upsert(target_fqn: str, keys: list[str], cols: list[str], view_name: str) -> None:
    target_fqn_sql = _qfqn(target_fqn)
    join_cond = _sql_join(keys)
    update_cols = [c for c in cols if c not in keys]
    update_set = ", ".join(f"t.{_qi(c, 'column')} = s.{_qi(c, 'column')}" for c in update_cols)
    insert_cols = ", ".join(_qi(c, "column") for c in cols)
    insert_vals = ", ".join(f"s.{_qi(c, 'column')}" for c in cols)

    merge_sql = f"""
    MERGE INTO {target_fqn_sql} t
    USING {view_name} s
    ON {join_cond}
    {"WHEN MATCHED THEN UPDATE SET " + update_set if update_set else ""}
    WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """
    spark.sql(merge_sql)


def _apply_dml_file(path: Path, catalog: str) -> None:
    spec = load_yaml(path)
    check_no_catalog_override(spec, path.name)
    for row in spec.get("rows", []):
        if "environment" in row:
            raise ValueError(f"{path.name}: environment is supplied by the bundle target")
        row["environment"] = environment

    if not isinstance(spec, dict):
        raise ValueError(f"{path.name}: YAML root must be a mapping.")

    target_catalog = catalog
    _validate_identifier(str(target_catalog), "catalog")
    operation = _normalize_operation(spec)
    target_table = spec.get("target_table")
    rows = spec.get("rows") or []
    keys = spec.get("match_keys") or spec.get("merge_keys") or []

    if not target_table:
        raise ValueError(f"{path.name}: missing required field 'target_table'.")
    if not isinstance(rows, list):
        raise ValueError(f"{path.name}: 'rows' must be a list.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path.name}: each item in 'rows' must be a mapping.")
    if not rows:
        print(f"[apply_dml] {path.name}: no rows - skipping.")
        return

    table_parts = str(target_table).split(".")
    if len(table_parts) != 2:
        raise ValueError(f"{path.name}: 'target_table' must be schema.table.")
    _validate_identifier(table_parts[0], "target schema")
    _validate_identifier(table_parts[1], "target table")

    all_cols = _row_columns(rows)
    if not all_cols:
        raise ValueError(f"{path.name}: rows contain no columns.")
    for col in all_cols:
        _validate_identifier(col, "row column")

    key_list: list[str] = []
    for key in keys:
        normalized = _validate_identifier(str(key), "match key")
        if normalized not in key_list:
            key_list.append(normalized)
    keys = key_list

    if operation in {"update", "upsert"}:
        missing_key_cols = [key for key in keys if key not in all_cols]
        if missing_key_cols:
            raise ValueError(f"{path.name}: match_keys missing in rows: {missing_key_cols}")

    target_fqn = f"{target_catalog}.{target_table}"
    df, cols = _rows_df_casted(target_fqn, rows)

    target_cols = {field.name for field in spark.table(target_fqn).schema}
    unknown_cols = [col for col in cols if col not in target_cols]
    if unknown_cols:
        raise ValueError(
            f"{path.name}: these columns are not in target table {target_fqn}: {unknown_cols}"
        )

    view_name = f"_dml_src_{uuid.uuid4().hex}"
    df.createOrReplaceTempView(view_name)

    if operation == "insert":
        _run_insert(target_fqn, cols, view_name)
    elif operation == "update":
        if not keys:
            raise ValueError(f"{path.name}: 'match_keys' is required for update operation.")
        _run_update(target_fqn, keys, cols, view_name)
    elif operation == "upsert":
        if not keys:
            raise ValueError(f"{path.name}: 'match_keys' (or 'merge_keys') is required for upsert operation.")
        _run_upsert(target_fqn, keys, cols, view_name)
    else:
        raise ValueError(
            f"{path.name}: unsupported operation '{operation}'. Expected insert, update, or upsert."
        )

    print(f"[apply_dml] {path.name}: operation={operation} rows={len(rows)} target={target_fqn}")


# Widgets

dbutils.widgets.text("catalog", "", "Unity Catalog name")
dbutils.widgets.text("bronze_catalog", "", "Bronze catalog")
dbutils.widgets.text("environment", "", "Environment")
dbutils.widgets.text("expected_host", "", "Expected workspace host")
dbutils.widgets.text("dml_dir", "", "Workspace path to config/data_platform/dml/")

catalog = dbutils.widgets.get("catalog")
environment = dbutils.widgets.get("environment")
check_target(environment, catalog, dbutils.widgets.get("bronze_catalog"),
             spark.conf.get("spark.databricks.workspaceUrl"),
             dbutils.widgets.get("expected_host"))
dml_dir = dbutils.widgets.get("dml_dir")

dml_dir = require_bundle_directory(dml_dir, "dml_dir")

spark.sql(f"USE CATALOG {catalog}")
print(f"catalog={catalog!r} dml_dir={dml_dir!r}")

paths = sorted(Path(dml_dir).glob("*.yml"))
if not paths:
    raise FileNotFoundError(f"No DML YAML files found in {dml_dir}")
else:
    for path in paths:
        _apply_dml_file(path, catalog)
    print(f"[apply_dml] Done - {len(paths)} file(s) processed.")
