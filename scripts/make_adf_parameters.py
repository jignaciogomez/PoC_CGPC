#!/usr/bin/env python3
"""Build ADF target parameter file from the exported ARM template."""
import argparse
import json
import re
from pathlib import Path

REFERENCE = re.compile(r"^\[parameters\('([^']+)'\)\]$")
GLOBAL_NAMES = {
    "databricksHost": "workspace_host",
    "databricksJobId": "job_id",
    "databricksTokenSecretUrl": "token_secret_url",
}


def parameter_name(value, label):
    match = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError(f"{label} was not exposed as an ARM parameter: {value!r}")
    return match.group(1)


def global_parameter_values(template):
    found = {}
    for resource in template["resources"]:
        kind = resource["type"].lower()
        properties = resource.get("properties", {})
        if kind == "microsoft.datafactory/factories":
            globals_block = properties.get("globalParameters", {})
        elif kind == "microsoft.datafactory/factories/globalparameters":
            globals_block = properties
        else:
            continue
        for name in GLOBAL_NAMES:
            if name in globals_block:
                found.setdefault(name, set()).add(
                    parameter_name(globals_block[name]["value"], name)
                )
    if set(found) != set(GLOBAL_NAMES) or any(len(names) != 1 for names in found.values()):
        raise ValueError(f"Expected three distinct, parameterized ADF globals; found {found}")
    return {name: next(iter(names)) for name, names in found.items()}


parser = argparse.ArgumentParser()
parser.add_argument("--template", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--factory-name", required=True)
parser.add_argument("--workspace-host", required=True)
parser.add_argument("--job-id", required=True)
parser.add_argument("--token-secret-url", required=True)
args = parser.parse_args()

if not args.workspace_host.startswith("https://") or not args.workspace_host.endswith(".cloud.databricks.com"):
    raise ValueError("Expected an HTTPS Databricks on AWS workspace host")
if not args.job_id.isdecimal():
    raise ValueError("Databricks job ID must be numeric")
if not args.token_secret_url.startswith("https://") or "/secrets/" not in args.token_secret_url:
    raise ValueError("Expected an Azure Key Vault secret URL")

template = json.loads(args.template.read_text())
exported_globals = global_parameter_values(template)
factory_names = [key for key in template["parameters"] if key.lower() == "factoryname"]
if len(factory_names) != 1:
    raise ValueError("Expected one factoryName ARM parameter")
values = {factory_names[0]: args.factory_name}
for global_name, argument_name in GLOBAL_NAMES.items():
    values[exported_globals[global_name]] = getattr(args, argument_name)
if len(values) != 4 or set(values) - set(template["parameters"]):
    raise ValueError("Exported ARM parameters do not match the target values")

parameters = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {name: {"value": value} for name, value in values.items()},
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(parameters, indent=2) + "\n")
print(f"Wrote ADF parameters to {args.output}")
