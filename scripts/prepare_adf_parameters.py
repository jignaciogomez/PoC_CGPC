#!/usr/bin/env python3
"""Validate an ADF export and supply environment values without editing its ARM template."""

import argparse
import json
from pathlib import Path

PARAMETERS_SCHEMA = (
    "https://schema.management.azure.com/schemas/2019-04-01/"
    "deploymentParameters.json#"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def contains_encrypted_credential(value):
    if isinstance(value, dict):
        return "encryptedCredential" in value or any(
            contains_encrypted_credential(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(contains_encrypted_credential(item) for item in value)
    return False


def validate_portable_source(source_root):
    # ADF encrypts this property for one factory, so it cannot be promoted as-is.
    for path in sorted((source_root / "linkedService").glob("*.json")):
        if contains_encrypted_credential(load_json(path)):
            raise ValueError(
                f"{path}: encryptedCredential is factory-bound; use managed identity "
                "or an Azure Key Vault reference before exporting"
            )


def prepare_parameters(template, configuration, factory_name):
    exported = template.get("parameters")
    configured = configuration.get("parameters")
    if not isinstance(exported, dict) or not isinstance(configured, dict):
        raise ValueError("ARM template and environment configuration need parameters objects")
    if "factoryName" not in exported:
        raise ValueError("ADF export is missing its factoryName parameter")
    if not factory_name:
        raise ValueError("Target factory name is required")
    if "factoryName" in configured:
        raise ValueError("Set factoryName through the target environment, not the parameter file")

    # Configured names must exist in the actual export, and every parameter
    # without a source default must have a target value. This scales with new
    # pipelines, datasets, and linked services without naming them here.
    unknown = sorted(set(configured) - set(exported))
    if unknown:
        raise ValueError(f"Environment configuration has unknown ARM parameters: {unknown}")
    supplied = dict(configured)
    supplied["factoryName"] = {"value": factory_name}
    missing = sorted(
        name for name, definition in exported.items()
        if "defaultValue" not in definition and name not in supplied
    )
    if missing:
        raise ValueError(f"Environment configuration is missing required ARM parameters: {missing}")
    for name, setting in supplied.items():
        if not isinstance(setting, dict) or ("value" in setting) == ("reference" in setting):
            raise ValueError(f"ARM parameter {name} needs exactly one value or reference")

    return {
        "$schema": PARAMETERS_SCHEMA,
        "contentVersion": template.get("contentVersion", "1.0.0.0"),
        "parameters": supplied,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--factory-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    validate_portable_source(args.source_root)
    parameters = prepare_parameters(
        load_json(args.template), load_json(args.configuration), args.factory_name
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(parameters, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {args.output} with {len(parameters['parameters'])} ARM parameters")


if __name__ == "__main__":
    main()
