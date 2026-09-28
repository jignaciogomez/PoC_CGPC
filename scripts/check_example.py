#!/usr/bin/env python3
"""Offline consistency checks for the small ADF/Databricks example."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pipeline = json.loads((ROOT / "adf/pipeline/PL_LoadOrders.json").read_text())
linked_service = json.loads((ROOT / "adf/linkedService/LS_Databricks.json").read_text())
parameter_rules = json.loads((ROOT / "adf/arm-template-parameters-definition.json").read_text())
activity = pipeline["properties"]["activities"][0]

assert pipeline["name"] == "PL_LoadOrders"
assert activity["type"] == "DatabricksNotebook"
assert activity["linkedServiceName"]["referenceName"] == linked_service["name"]
assert activity["typeProperties"]["baseParameters"]["catalog_name"] == "dev_bronze_ca"
assert linked_service["properties"]["typeProperties"]["authentication"] == "MSI"
assert "accessToken" not in linked_service["properties"]["typeProperties"]
assert parameter_rules["Microsoft.DataFactory/factories/pipelines"]["properties"]["activities"][0]["typeProperties"]["baseParameters"]["catalog_name"]
assert json.loads((ROOT / "adf/factory/dev-cgpc-poc.json").read_text())["name"] == "dev-cgpc-poc"
print("Example source checks passed")
