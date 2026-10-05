# Databricks notebook source
"""Process immutable ADF response files with Auto Loader and idempotent MERGE."""

import os
import sys

_source_dir = os.path.dirname(
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
sys.path.insert(0, "/Workspace" + _source_dir)
from target_guard import check_target

from delta.tables import DeltaTable
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import ArrayType, StringType, StructField, StructType


def struct(**fields):
    return StructType([StructField(name, kind, True) for name, kind in fields.items()])


# ADF copies the entire API response as binary. Parse its top-level envelope
# first, then explode results so each user becomes one bronze row.
USER_SCHEMA = struct(
    gender=StringType(),
    name=struct(title=StringType(), first=StringType(), last=StringType()),
    location=struct(
        street=struct(number=StringType(), name=StringType()),
        city=StringType(), state=StringType(), country=StringType(),
        postcode=StringType(),
        coordinates=struct(latitude=StringType(), longitude=StringType()),
        timezone=struct(offset=StringType(), description=StringType()),
    ),
    email=StringType(),
    dob=struct(date=StringType(), age=StringType()),
    registered=struct(date=StringType(), age=StringType()),
    phone=StringType(), cell=StringType(),
    id=struct(name=StringType(), value=StringType()),
    picture=struct(large=StringType(), medium=StringType(), thumbnail=StringType()),
    nat=StringType(),
)
RESPONSE_SCHEMA = struct(
    results=ArrayType(USER_SCHEMA),
    info=struct(seed=StringType(), results=StringType(), page=StringType(),
                version=StringType()),
)

for name in ("catalog", "bronze_catalog", "environment", "expected_host",
             "landing_volume_path", "checkpoint_path"):
    dbutils.widgets.text(name, "")

platform = dbutils.widgets.get("catalog")
bronze = dbutils.widgets.get("bronze_catalog")
check_target(dbutils.widgets.get("environment"), platform, bronze,
             spark.conf.get("spark.databricks.workspaceUrl"),
             dbutils.widgets.get("expected_host"))
landing = dbutils.widgets.get("landing_volume_path").rstrip("/")
checkpoint = dbutils.widgets.get("checkpoint_path").rstrip("/")
prefix = f"/Volumes/{bronze}/sales/"
if not landing.startswith(prefix) or not checkpoint.startswith(prefix):
    raise ValueError("Landing and checkpoint paths must be in the selected bronze catalog")
if landing == checkpoint or checkpoint.startswith(landing + "/"):
    raise ValueError("Auto Loader checkpoint must be outside the landing directory")

# Fail before starting a stream if the admin-provisioned external volume or the
# UC-managed checkpoint volume is missing or inaccessible to the job identity.
dbutils.fs.ls(landing)
dbutils.fs.ls(os.path.dirname(checkpoint))
target = f"{bronze}.sales.random_users_raw"
quarantine_target = f"{bronze}.sales.random_users_quarantine"
spark.table(target).limit(0).collect()
spark.table(quarantine_target).limit(0).collect()


def apply_batch(batch, batch_id):
    if batch.isEmpty():
        return
    parsed = batch.select(
        F.col("path").alias("source_file"),
        F.col("modificationTime").alias("source_modified_at"),
        F.col("content").cast("string").alias("raw_json"),
        F.from_json(F.col("content").cast("string"), RESPONSE_SCHEMA).alias("document"),
    )
    invalid = parsed.filter(
        F.col("document").isNull() | F.col("document.results").isNull()
    ).select(
        F.sha2(F.concat_ws("::", "source_file", "raw_json"), 256).alias("record_id"),
        "source_file", F.lit("invalid_response_json").alias("reason"),
        F.col("raw_json").alias("payload_json"),
        F.current_timestamp().alias("quarantined_at"),
    )
    users = parsed.filter(F.col("document.results").isNotNull()).select(
        "source_file", "source_modified_at",
        F.col("document.info.seed").alias("source_seed"),
        F.explode_outer("document.results").alias("user"),
    ).withColumn("payload_json", F.to_json("user"))
    users = users.withColumn("email", F.lower(F.trim(F.col("user.email"))))
    missing_email = users.filter(F.col("email").isNull() | (F.col("email") == ""))
    missing_email = missing_email.select(
        F.sha2(F.concat_ws("::", "source_file", "payload_json"), 256).alias("record_id"),
        "source_file", F.lit("missing_email").alias("reason"),
        "payload_json", F.current_timestamp().alias("quarantined_at"),
    )
    rejected = invalid.unionByName(missing_email).dropDuplicates(["record_id"])
    DeltaTable.forName(spark, quarantine_target).alias("t").merge(
        rejected.alias("s"), "t.record_id = s.record_id"
    ).whenNotMatchedInsertAll().execute()

    good = users.filter(F.col("email").isNotNull() & (F.col("email") != ""))
    good = good.select(
        "email", F.col("user.gender").alias("gender"),
        F.col("user.name.first").alias("first_name"),
        F.col("user.name.last").alias("last_name"),
        F.col("user.location.country").alias("country"),
        F.col("user.nat").alias("nationality"),
        "payload_json", F.sha2("payload_json", 256).alias("record_hash"),
        "source_seed", "source_file", "source_modified_at",
        F.current_timestamp().alias("ingested_at"),
    )
    order = Window.partitionBy("email").orderBy(
        F.col("source_modified_at").desc(), F.col("source_file").desc(),
        F.col("record_hash").desc()
    )
    good = good.withColumn("row_no", F.row_number().over(order)).filter("row_no = 1").drop("row_no")
    # foreachBatch has at-least-once delivery. The hash predicate makes replay
    # harmless and avoids rewriting rows whose user payload has not changed.
    DeltaTable.forName(spark, target).alias("t").merge(
        good.alias("s"), "t.email = s.email"
    ).whenMatchedUpdateAll(condition="t.record_hash <> s.record_hash") \
     .whenNotMatchedInsertAll().execute()
    print(f"Processed Auto Loader batch {batch_id}")


query = (spark.readStream.format("cloudFiles")
         .option("cloudFiles.format", "binaryFile")
         .load(landing)
         .writeStream.foreachBatch(apply_batch)
         .option("checkpointLocation", checkpoint)
         .trigger(availableNow=True)
         .start())
query.awaitTermination()
