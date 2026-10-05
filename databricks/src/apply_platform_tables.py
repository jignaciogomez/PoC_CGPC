# Databricks notebook source

import os
import sys

_source_dir = os.path.dirname(
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
sys.path.insert(0, "/Workspace" + _source_dir)
from target_guard import check_target
from workspace_paths import require_bundle_directory


dbutils.widgets.text("catalog", "", "Unity Catalog name")
dbutils.widgets.text("bronze_catalog", "", "Bronze catalog")
dbutils.widgets.text("expected_host", "", "Expected workspace host")
dbutils.widgets.text("environment", "", "Environment label")
dbutils.widgets.text("schemas_dir", "", "Workspace path to config/data_platform/schemas/")

catalog = dbutils.widgets.get("catalog")
bronze_catalog = dbutils.widgets.get("bronze_catalog")
expected_host = dbutils.widgets.get("expected_host")
environment = dbutils.widgets.get("environment")
check_target(environment, catalog, bronze_catalog,
             spark.conf.get("spark.databricks.workspaceUrl"), expected_host)
schemas_dir = dbutils.widgets.get("schemas_dir")
allow_drop_columns = False
fail_on_type_drift = True

schemas_dir = require_bundle_directory(schemas_dir, "schemas_dir")

from schema_builder import SchemaBuilder

spark.sql(f"USE CATALOG {catalog}")
print(
	"[apply_platform_tables] "
	f"catalog={catalog!r} environment={environment!r} "
	f"schemas_dir={schemas_dir!r} allow_drop_columns={allow_drop_columns} "
	f"fail_on_type_drift={fail_on_type_drift}"
)

builder = SchemaBuilder(
	spark=spark,
	catalog=catalog,
	allow_drop_columns=allow_drop_columns,
	fail_on_type_drift=fail_on_type_drift,
)
builder.apply_all(schemas_dir)
