#!/usr/bin/env python3
"""Check generic ARM parameter coverage and the nonportable ADF credential guard."""

import json
import tempfile
import unittest
from pathlib import Path

from prepare_adf_parameters import prepare_parameters, validate_portable_source


class PrepareParametersTests(unittest.TestCase):
    def test_landing_dataset_uses_one_file_per_run(self):
        root = Path(__file__).resolve().parents[1]
        dataset = json.loads((root / "adf/dataset/DS_RandomUserLanding.json").read_text())
        pipeline = json.loads((root / "adf/pipeline/PL_LoadRandomUsers.json").read_text())
        self.assertIn("file_name", dataset["properties"]["parameters"])
        output = pipeline["properties"]["activities"][0]["outputs"][0]
        self.assertIn("pipeline().RunId", output["parameters"]["file_name"]["value"])

    def setUp(self):
        self.template = {
            "parameters": {
                "factoryName": {"type": "string", "defaultValue": "dev-factory"},
                "Storage_url": {"type": "string"},
                "Landing_fileSystem": {"type": "string"},
            },
            "resources": [
                {"type": "Microsoft.DataFactory/factories/pipelines", "name": "One"},
                {"type": "Microsoft.DataFactory/factories/pipelines", "name": "Two"},
            ],
        }
        self.configuration = {
            "parameters": {
                "Storage_url": {"value": "https://qa.dfs.core.windows.net/"},
                "Landing_fileSystem": {"value": "sales"},
            }
        }

    def test_prepares_values_without_changing_resources(self):
        original = json.dumps(self.template)
        result = prepare_parameters(self.template, self.configuration, "qa-factory")
        self.assertEqual(json.dumps(self.template), original)
        self.assertEqual(result["parameters"]["factoryName"], {"value": "qa-factory"})
        self.assertEqual(len(self.template["resources"]), 2)

    def test_new_required_parameter_needs_configuration(self):
        self.template["parameters"]["AnotherConnection_url"] = {"type": "string"}
        with self.assertRaisesRegex(ValueError, "AnotherConnection_url"):
            prepare_parameters(self.template, self.configuration, "qa-factory")

    def test_rejects_factory_bound_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "linkedService"
            folder.mkdir()
            (folder / "AnyConnection.json").write_text(
                json.dumps({"properties": {"typeProperties": {"encryptedCredential": "x"}}})
            )
            with self.assertRaisesRegex(ValueError, "encryptedCredential"):
                validate_portable_source(Path(directory))


if __name__ == "__main__":
    unittest.main()
