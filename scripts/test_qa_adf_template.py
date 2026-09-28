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
                "devEndpoint": {"type": "string", "defaultValue": "https://devcgpcpocadls.dfs.core.windows.net/"},
                "devCredential": {"type": "securestring"},
            },
            "resources": [
                {"type": "Microsoft.DataFactory/factories", "name": "[parameters('factoryName')]", "location": "eastus", "identity": {"type": "SystemAssigned", "principalId": "dev-id", "tenantId": "dev-tenant"}},
                {"type": "Microsoft.DataFactory/factories/linkedservices",
                 "name": "[concat(parameters('factoryName'), '/LS_AdlsGen2')]",
                 "properties": {"type": "AzureBlobFS", "typeProperties": {
                     "url": "[parameters('devEndpoint')]",
                     "encryptedCredential": "[parameters('devCredential')]"}}},
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
        output, params = prepare(copy.deepcopy(self.template), "qa-cgpc-poc", "westus2", "qacgpcadls", "qasales")
        self.assertEqual(output["resources"][0]["location"], "westus2")
        self.assertEqual(output["resources"][0]["identity"], {"type": "SystemAssigned"})
        link = output["resources"][1]["properties"]["typeProperties"]
        self.assertEqual(link["url"], "https://qacgpcadls.dfs.core.windows.net/")
        self.assertNotIn("encryptedCredential", link)
        self.assertEqual(output["resources"][2]["properties"]["typeProperties"]["location"]["fileSystem"], "qasales")
        self.assertEqual(set(output["parameters"]), {"factoryName"})
        self.assertEqual(params["parameters"]["factoryName"]["value"], "qa-cgpc-poc")

    def test_refuses_dev_account(self):
        with self.assertRaises(ValueError):
            prepare(copy.deepcopy(self.template), "qa-cgpc-poc", "eastus", "devcgpcpocadls", "sales")


if __name__ == "__main__":
    unittest.main()
