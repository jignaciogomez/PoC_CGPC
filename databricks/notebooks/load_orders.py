# Databricks notebook source
from datetime import date
import re

dbutils.widgets.text("catalog_name", "dev_bronze_ca")
dbutils.widgets.text("process_date", "2026-01-01")

catalog = dbutils.widgets.get("catalog_name")
process_date = dbutils.widgets.get("process_date")

if catalog not in {"dev_bronze_ca", "qa_bronze_ca", "uat_bronze_ca", "prod_bronze_ca"}:
    raise ValueError("Unexpected catalog name")
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", process_date):
    raise ValueError("process_date must be YYYY-MM-DD")
date.fromisoformat(process_date)

# The catalog must be provisioned and granted to the run identity beforehand.
# Only the schema, small demo table, and view are created by this notebook.
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`sales`")
spark.sql(
    f"""
    CREATE OR REPLACE TABLE `{catalog}`.`sales`.`orders_demo`
    USING DELTA
    AS SELECT * FROM VALUES
      (1, 'US', CAST(120.00 AS DECIMAL(10,2)), DATE('{process_date}')),
      (2, 'CA', CAST(80.00 AS DECIMAL(10,2)), DATE('{process_date}')),
      (3, 'US', CAST(30.00 AS DECIMAL(10,2)), DATE('{process_date}'))
    AS t(order_id, country_code, amount, process_date)
    """
)
spark.sql(
    f"""
    CREATE OR REPLACE VIEW `{catalog}`.`sales`.`v_orders_by_country` AS
    SELECT country_code, SUM(amount) AS total_amount, COUNT(*) AS order_count
    FROM `{catalog}`.`sales`.`orders_demo`
    GROUP BY country_code
    """
)

display(spark.table(f"`{catalog}`.`sales`.`v_orders_by_country`"))
