#!/usr/bin/env python3
"""Offline structural checks for the Dev ADF to ADLS example."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read_json(path):
    return json.loads((ROOT / path).read_text())

factory = read_json("adf/factory/dev-cgpc-poc.json")
pipeline = read_json("adf/pipeline/PL_LoadRandomUsers.json")
http_link = read_json("adf/linkedService/LS_RandomUserHttp.json")
adls_link = read_json("adf/linkedService/LS_AdlsGen2.json")
source = read_json("adf/dataset/DS_RandomUserApi.json")
sink = read_json("adf/dataset/DS_RandomUserLanding.json")
activity, = pipeline["properties"]["activities"]

assert factory["name"] == "dev-cgpc-poc"
assert pipeline["name"] == "PL_LoadRandomUsers"
assert activity["type"] == "Copy"
assert activity["typeProperties"]["source"]["type"] == "BinarySource"
assert activity["typeProperties"]["source"]["storeSettings"]["type"] == "HttpReadSettings"
assert activity["typeProperties"]["sink"]["type"] == "BinarySink"
assert activity["typeProperties"]["sink"]["storeSettings"]["type"] == "AzureBlobFSWriteSettings"
assert activity["inputs"][0]["referenceName"] == source["name"]
assert activity["outputs"][0]["referenceName"] == sink["name"]
assert http_link["properties"]["type"] == "HttpServer"
assert http_link["properties"]["typeProperties"]["url"] == "https://randomuser.me/"
assert source["properties"]["typeProperties"]["location"]["relativeUrl"] == "api/?results=1000&exc=login"
assert adls_link["properties"]["type"] == "AzureBlobFS"
assert adls_link["properties"]["typeProperties"]["url"] == "https://devcgpcpocadls.dfs.core.windows.net/"
assert sink["properties"]["linkedServiceName"]["referenceName"] == adls_link["name"]
assert sink["properties"]["typeProperties"]["location"]["fileSystem"] == "sales"
assert sink["properties"]["typeProperties"]["location"]["folderPath"] == "landing"
assert sink["properties"]["typeProperties"]["location"]["fileName"] == "users.json"
notebook = (ROOT / "databricks/notebooks/load_random_users.py").read_text()
ast.parse(notebook)
assert "urlopen" not in notebook
assert 'spark.read.option("multiLine", "true").json(source_path)' in notebook
assert "dev_bronze_ca" in notebook
assert 'LANDING_FILE = "landing/users.json"' in notebook
print("Dev ADF to ADLS source checks passed")
