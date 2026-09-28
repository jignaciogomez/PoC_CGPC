#!/usr/bin/env python3
"""Offline structural checks for the connected ADF/Databricks example."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
factory = json.loads((ROOT / "adf/factory/dev-cgpc-poc.json").read_text())
pipeline = json.loads((ROOT / "adf/pipeline/PL_LoadRandomUsers.json").read_text())
rules = json.loads((ROOT / "adf/arm-template-parameters-definition.json").read_text())
activities = {activity["name"]: activity for activity in pipeline["properties"]["activities"]}
globals_block = factory["properties"]["globalParameters"]

assert factory["name"] == "dev-cgpc-poc"
assert globals_block["databricksHost"]["value"] == "https://dbc-db5836d9-ab81.cloud.databricks.com"
assert set(globals_block) == {"databricksHost", "databricksJobId", "databricksTokenSecretUrl"}
assert pipeline["name"] == "PL_LoadRandomUsers"
assert activities["GetDatabricksToken"]["policy"]["secureOutput"] is True
assert activities["StartJob"]["policy"]["secureInput"] is True
assert activities["StartJob"]["type"] == "WebActivity"
assert activities["WaitForJob"]["type"] == "Until"
assert activities["CheckJobResult"]["type"] == "IfCondition"
assert rules["Microsoft.DataFactory/factories"]["properties"]["globalParameters"]["*"]["value"] == "="
assert not (ROOT / "adf/linkedService/LS_Databricks.json").exists(), "Azure-only linked service must be removed"
print("ADF source checks passed")
