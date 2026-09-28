# Databricks notebook source
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from pyspark.sql.types import StringType, StructField, StructType, TimestampType

API_URL = "https://randomuser.me/api/?results=1000&exc=login"
ALLOWED_CATALOGS = {"dev_bronze_ca", "qa_bronze_ca"}
SCHEMA = "sales"

dbutils.widgets.text("catalog_name", "dev_bronze_ca")
catalog = dbutils.widgets.get("catalog_name")
if catalog not in ALLOWED_CATALOGS:
    raise ValueError(f"Unsupported catalog: {catalog}")

request = Request(API_URL, headers={"Accept": "application/json", "User-Agent": "cgpc-promotion-poc/1.0"})
with urlopen(request, timeout=60) as response:
    payload = json.load(response)

if "error" in payload:
    raise RuntimeError(f"Random User API error: {payload['error']}")
users = payload.get("results")
info = payload.get("info", {})
if not isinstance(users, list) or len(users) != 1000:
    raise ValueError(f"Expected 1000 users; got {len(users) if isinstance(users, list) else 'invalid payload'}")
if any("login" in user for user in users):
    raise ValueError("The API response unexpectedly contains login fields")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{SCHEMA}`")
raw_table = f"{catalog}.{SCHEMA}.random_users_raw"
users_table = f"{catalog}.{SCHEMA}.random_users"
country_view = f"{catalog}.{SCHEMA}.v_random_users_by_country"

loaded_at = datetime.now(timezone.utc)
rows = [(json.dumps(user, ensure_ascii=False), str(info.get("seed", "")), str(info.get("version", "")), loaded_at) for user in users]
raw_schema = StructType([
    StructField("raw_json", StringType(), False),
    StructField("api_seed", StringType(), False),
    StructField("api_version", StringType(), False),
    StructField("loaded_at_utc", TimestampType(), False),
])
raw_df = spark.createDataFrame(rows, schema=raw_schema)
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

print(f"Loaded {spark.table(users_table).count()} users into {catalog}.{SCHEMA}.random_users")
display(spark.table(country_view).orderBy("country"))
