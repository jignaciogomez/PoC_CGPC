#!/usr/bin/env python3
"""Create target ARM parameters after checking the ADF utility's actual export."""
import argparse
import json
import re
from pathlib import Path

REFERENCE = re.compile(r"^\[parameters\('([^']+)'\)\]$")


def ref_name(value, label):
    match = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError(f"{label} was not parameterized in the ADF export: {value!r}")
    return match.group(1)


def named_resource(template, resource_type, suffix):
    matches = [r for r in template["resources"]
               if r["type"].lower() == resource_type.lower()
               and (r["name"].endswith("/" + suffix) or suffix in r["name"])]
    if len(matches) != 1:
        raise ValueError(f"Expected one {resource_type}/{suffix}; found {len(matches)}")
    return matches[0]


parser = argparse.ArgumentParser()
parser.add_argument("--template", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--factory-name", required=True)
parser.add_argument("--workspace-host", required=True)
parser.add_argument("--workspace-resource-id", required=True)
parser.add_argument("--cluster-id", required=True)
parser.add_argument("--notebook-path", required=True)
parser.add_argument("--catalog", required=True)
args = parser.parse_args()

if not re.fullmatch(r"(dev|qa|uat|prod)_bronze_ca", args.catalog):
    raise ValueError("Catalog must follow <environment>_bronze_ca")
if not args.workspace_host.startswith("https://") or not args.notebook_path.startswith("/"):
    raise ValueError("Workspace host must be HTTPS and notebook path must be absolute")
if "/providers/Microsoft.Databricks/workspaces/" not in args.workspace_resource_id:
    raise ValueError("Expected an Azure Databricks workspace resource ID")

template = json.loads(args.template.read_text())
ls = named_resource(template, "Microsoft.DataFactory/factories/linkedservices", "LS_Databricks")
pl = named_resource(template, "Microsoft.DataFactory/factories/pipelines", "PL_LoadOrders")
ls_props = ls["properties"]["typeProperties"]
activity = next(a for a in pl["properties"]["activities"] if a["name"] == "BuildBronzeOrders")
task_props = activity["typeProperties"]
values = {
    ref_name(ls_props["domain"], "Databricks workspace domain"): args.workspace_host,
    ref_name(ls_props["workspaceResourceId"], "Databricks workspace resource ID"): args.workspace_resource_id,
    ref_name(ls_props["existingClusterId"], "Databricks cluster"): args.cluster_id,
    ref_name(task_props["notebookPath"], "notebook path"): args.notebook_path,
    ref_name(task_props["baseParameters"]["catalog_name"], "catalog"): args.catalog,
}

factory_parameters = [name for name in template["parameters"] if name.lower() == "factoryname"]
if len(factory_parameters) != 1:
    raise ValueError("Expected a factoryName ARM parameter")
values[factory_parameters[0]] = args.factory_name
if len(values) != 6:
    raise ValueError("ADF export reused a parameter for distinct settings")
missing = set(values) - set(template["parameters"])
if missing:
    raise ValueError(f"Missing ARM parameters: {sorted(missing)}")

document = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {name: {"value": value} for name, value in values.items()},
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(document, indent=2) + "\n")
print(f"Wrote {args.output} for {args.catalog}")
