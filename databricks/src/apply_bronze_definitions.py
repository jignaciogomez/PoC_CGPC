# Databricks notebook source
"""Create additive bronze objects. Existing table columns are never dropped."""

import os
import sys

_source_dir = os.path.dirname(
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
sys.path.insert(0, "/Workspace" + _source_dir)
from target_guard import check_target

for name in ("catalog", "bronze_catalog", "environment", "expected_host"):
    dbutils.widgets.text(name, "")

platform = dbutils.widgets.get("catalog")
bronze = dbutils.widgets.get("bronze_catalog")
check_target(dbutils.widgets.get("environment"), platform, bronze,
             spark.conf.get("spark.databricks.workspaceUrl"),
             dbutils.widgets.get("expected_host"))

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{bronze}`.`sales`")
spark.sql(f"""
CREATE TABLE IF NOT EXISTS `{bronze}`.`sales`.`random_users_raw` (
  email STRING NOT NULL,
  gender STRING,
  first_name STRING,
  last_name STRING,
  country STRING,
  nationality STRING,
  payload_json STRING,
  record_hash STRING NOT NULL,
  source_seed STRING,
  source_file STRING,
  source_modified_at TIMESTAMP,
  ingested_at TIMESTAMP
) USING DELTA
""")
spark.sql(f"""
CREATE TABLE IF NOT EXISTS `{bronze}`.`sales`.`random_users_quarantine` (
  record_id STRING NOT NULL,
  source_file STRING,
  reason STRING,
  payload_json STRING,
  quarantined_at TIMESTAMP
) USING DELTA
""")

# ALTER VIEW preserves the existing view identity and privileges.
view = f"`{bronze}`.`sales`.`v_random_users`"
select = (f"SELECT email, first_name, last_name, gender, country, nationality, "
          f"ingested_at FROM `{bronze}`.`sales`.`random_users_raw`")
spark.sql(f"CREATE VIEW IF NOT EXISTS {view} AS {select}")
spark.sql(f"ALTER VIEW {view} AS {select}")
print(f"Bronze objects are ready in {bronze}.sales")
