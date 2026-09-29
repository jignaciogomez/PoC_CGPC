#!/usr/bin/env python3
"""Turn an ADF export into a QA-only ARM template and parameter file.

The Dev linked service contains a factory-bound encryptedCredential. The ADF
exporter turns it into an accountKey parameter. This script removes that key
from the disposable QA artifact so the existing QA factory uses its managed
identity. It also replaces the ADLS endpoint and filesystem without changing
Git source.
"""
import argparse
import json
import re
from pathlib import Path

ACCOUNT = re.compile(r"[a-z0-9]{3,24}\Z")
FILESYSTEM = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?\Z")


def one_resource(resources, kind, name=None):
    matches = [item for item in resources
               if item.get("type", "").lower() == kind.lower()
               and (name is None or name in str(item.get("name", "")))]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {kind} resource named {name}; found {len(matches)}")
    return matches[0]


def prepare(template, factory_name, account, filesystem):
    if not ACCOUNT.fullmatch(account) or account == "devcgpcpocadls":
        raise ValueError("QA storage account must be a valid account distinct from Dev")
    if not FILESYSTEM.fullmatch(filesystem) or "--" in filesystem:
        raise ValueError("QA filesystem name is invalid")
    if not factory_name or factory_name == "dev-cgpc-poc":
        raise ValueError("QA factory name must differ from Dev")
    resources = template["resources"]
    adls = one_resource(resources, "Microsoft.DataFactory/factories/linkedservices", "LS_AdlsGen2")
    dataset = one_resource(resources, "Microsoft.DataFactory/factories/datasets", "DS_RandomUserLanding")
    one_resource(resources, "Microsoft.DataFactory/factories/pipelines", "PL_LoadRandomUsers")

    link_properties = adls["properties"]
    if link_properties.get("type") != "AzureBlobFS":
        raise ValueError("LS_AdlsGen2 is not an ADLS Gen2 linked service")
    link_type_properties = link_properties["typeProperties"]
    link_type_properties["url"] = f"https://{account}.dfs.core.windows.net/"
    link_type_properties.pop("encryptedCredential", None)
    link_type_properties.pop("accountKey", None)
    if any(key in link_type_properties for key in ("accountkey", "sasUri", "sasToken", "servicePrincipalId", "servicePrincipalCredentialType", "servicePrincipalCredential", "credential", "credentials")):
        raise ValueError("QA ADLS linked service still contains a credential property")

    location_properties = dataset["properties"]["typeProperties"]["location"]
    if location_properties.get("type") != "AzureBlobFSLocation":
        raise ValueError("DS_RandomUserLanding is not an ADLS Gen2 dataset")
    location_properties["fileSystem"] = filesystem
    if location_properties.get("folderPath") != "landing" or location_properties.get("fileName") != "users.json":
        raise ValueError("Unexpected landing path in exported dataset")

    # The export may have created parameters for properties replaced above. Drop
    # only parameters no longer referenced by any ARM expression in the artifact.
    parameters = template["parameters"]
    for name in list(parameters):
        body = json.dumps({key: value for key, value in template.items() if key != "parameters"})
        reference = re.compile(r"parameters\s*\(\s*['\"]" + re.escape(name) + r"['\"]\s*\)", re.I)
        if not reference.search(body):
            del parameters[name]

    factory_names = [name for name in parameters if name.lower() == "factoryname"]
    if len(factory_names) != 1:
        raise ValueError("Expected one factoryName ARM parameter")
    required = [name for name, spec in parameters.items()
                if "defaultValue" not in spec and name != factory_names[0]]
    if required:
        raise ValueError(f"Export has unresolved required parameters: {required}")
    parameters[factory_names[0]]["defaultValue"] = factory_name

    rendered = json.dumps(template)
    if "encryptedCredential" in rendered or "devcgpcpocadls" in rendered or "accountKey" in rendered:
        raise ValueError("QA artifact still contains a Dev credential or storage endpoint")

    parameter_file = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {factory_names[0]: {"value": factory_name}},
    }
    return template, parameter_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output-template", type=Path, required=True)
    parser.add_argument("--output-parameters", type=Path, required=True)
    parser.add_argument("--factory-name", required=True)
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--filesystem", required=True)
    args = parser.parse_args()
    template = json.loads(args.template.read_text())
    qa_template, qa_parameters = prepare(
        template, args.factory_name, args.storage_account, args.filesystem
    )
    args.output_template.parent.mkdir(parents=True, exist_ok=True)
    args.output_parameters.parent.mkdir(parents=True, exist_ok=True)
    args.output_template.write_text(json.dumps(qa_template, indent=2) + "\n")
    args.output_parameters.write_text(json.dumps(qa_parameters, indent=2) + "\n")
    print(f"Prepared QA ADF deployment artifact for {args.factory_name}")


if __name__ == "__main__":
    main()
