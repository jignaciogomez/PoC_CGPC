#!/usr/bin/env python3
"""Check that QA export preparation removes Dev credentials and endpoints."""
import copy
import unittest

from build_qa_adf_template import prepare


class QaTemplateTests(unittest.TestCase):
    def setUp(self):
        self.template = {
            "parameters": {
                "factoryName": {"type": "string", "defaultValue": "dev-cgpc-poc"},
                "LS_AdlsGen2_accountKey": {"type": "secureString"},
            },
            "resources": [
                {"type": "Microsoft.DataFactory/factories/linkedServices",
                 "name": "[concat(parameters('factoryName'), '/LS_AdlsGen2')]",
                 "properties": {"type": "AzureBlobFS", "typeProperties": {
                     "url": "https://devcgpcpocadls.dfs.core.windows.net/",
                     "accountKey": {"type": "SecureString", "value": "[parameters('LS_AdlsGen2_accountKey')]"}}}},
                {"type": "Microsoft.DataFactory/factories/datasets",
                 "name": "[concat(parameters('factoryName'), '/DS_RandomUserLanding')]",
                 "properties": {"typeProperties": {"location": {
                     "type": "AzureBlobFSLocation", "fileSystem": "sales",
                     "folderPath": "landing", "fileName": "users.json"}}}},
                {"type": "Microsoft.DataFactory/factories/pipelines",
                 "name": "[concat(parameters('factoryName'), '/PL_LoadRandomUsers')]"},
            ],
        }

    def test_retargets_qa_and_drops_factory_bound_credential(self):
        output, params = prepare(copy.deepcopy(self.template), "qa-cgpc-poc", "qacgpcpocadls", "sales")
        link = output["resources"][0]["properties"]["typeProperties"]
        self.assertEqual(link["url"], "https://qacgpcpocadls.dfs.core.windows.net/")
        self.assertNotIn("encryptedCredential", link)
        self.assertNotIn("accountKey", link)
        self.assertEqual(output["resources"][1]["properties"]["typeProperties"]["location"]["fileSystem"], "sales")
        self.assertEqual(set(output["parameters"]), {"factoryName"})
        self.assertEqual(output["parameters"]["factoryName"]["defaultValue"], "qa-cgpc-poc")
        self.assertEqual(params["parameters"]["factoryName"]["value"], "qa-cgpc-poc")

    def test_refuses_dev_account(self):
        with self.assertRaises(ValueError):
            prepare(copy.deepcopy(self.template), "qa-cgpc-poc", "devcgpcpocadls", "sales")


if __name__ == "__main__":
    unittest.main()
