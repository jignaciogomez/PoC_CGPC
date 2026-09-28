# Databricks notebook source
"""Load the JSON response landed by the Dev ADF pipeline into Unity Catalog."""
import re

from pyspark.sql.functions import col, current_timestamp, explode, to_json

CATALOG = "dev_bronze_ca"
SCHEMA = "sales"
LANDING_FILE = "landing/users.json"
SECRET_SCOPE = "dev-adls"

dbutils.widgets.text("storage_account", "")
dbutils.widgets.text("file_system", "")
storage_account = dbutils.widgets.get("storage_account")
file_system = dbutils.widgets.get("file_system")
if not re.fullmatch(r"[a-z0-9]{3,24}", storage_account):
    raise ValueError("Set storage_account to the Dev ADLS Gen2 account name")
if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", file_system):
    raise ValueError("Set file_system to the Dev ADLS Gen2 filesystem name")

account_host = f"{storage_account}.dfs.core.windows.net"
config_prefix = f"fs.azure.account."
spark.conf.set(f"{config_prefix}auth.type.{account_host}", "OAuth")
spark.conf.set(
    f"{config_prefix}oauth.provider.type.{account_host}",
    "org.apache.hadoop.fs.azurebfs.oauth2.ClientCredsTokenProvider",
)
spark.conf.set(f"{config_prefix}oauth2.client.id.{account_host}", dbutils.secrets.get(SECRET_SCOPE, "client-id"))
spark.conf.set(f"{config_prefix}oauth2.client.secret.{account_host}", dbutils.secrets.get(SECRET_SCOPE, "client-secret"))
tenant_id = dbutils.secrets.get(SECRET_SCOPE, "tenant-id")
spark.conf.set(
    f"{config_prefix}oauth2.client.endpoint.{account_host}",
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/token",
)

source_path = f"abfss://{file_system}@{account_host}/{LANDING_FILE}"
payload = spark.read.option("multiLine", "true").json(source_path)
if payload.count() != 1 or "results" not in payload.columns or "info" not in payload.columns:
    raise ValueError("Expected one Random User JSON response with results and info")
users = payload.select(
    explode(col("results")).alias("user"),
    col("info.seed").alias("api_seed"),
    col("info.version").alias("api_version"),
)
user_count = users.count()
if user_count != 1000:
    raise ValueError(f"Expected 1000 users in the landed response, got {user_count}")
if "login" in users.select("user.*").columns:
    raise ValueError("The API response unexpectedly contains login fields")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")
raw_table = f"{CATALOG}.{SCHEMA}.random_users_raw"
users_table = f"{CATALOG}.{SCHEMA}.random_users"
country_view = f"{CATALOG}.{SCHEMA}.v_random_users_by_country"

raw_df = users.select(
    to_json(col("user")).alias("raw_json"),
    col("api_seed"),
    col("api_version"),
    current_timestamp().alias("loaded_at_utc"),
)
raw_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(raw_table)

spark.sql(f"""
CREATE OR REPLACE TABLE {users_table} USING DELTA AS
SELECT
  sha2(concat_ws('|', get_json_object(raw_json, '$.email'), get_json_object(raw_json, '$.nat')), 256) AS user_key,
  get_json_object(raw_json, '$.gender') AS gender,
  get_json_object(raw_json, '$.name.title') AS name_title,
  get_json_object(raw_json, '$.name.first') AS first_name,
  get_json_object(raw_json, '$.name.last') AS last_name,
  get_json_object(raw_json, '$.email') AS email,
  get_json_object(raw_json, '$.location.city') AS city,
  get_json_object(raw_json, '$.location.state') AS state,
  get_json_object(raw_json, '$.location.country') AS country,
  get_json_object(raw_json, '$.location.postcode') AS postcode,
  get_json_object(raw_json, '$.nat') AS nationality,
  get_json_object(raw_json, '$.dob.date') AS date_of_birth_utc,
  api_seed,
  api_version,
  loaded_at_utc
FROM {raw_table}
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {country_view} AS
SELECT country, COUNT(*) AS user_count
FROM {users_table}
GROUP BY country
""")

print(f"Loaded {spark.table(users_table).count()} users from {source_path}")
display(spark.table(country_view).orderBy("country"))
