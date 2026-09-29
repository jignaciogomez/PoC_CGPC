# PoC_CGPC: ADF promotion from Dev to QA

`dev-cgpc-poc` is connected to this repository on collaboration branch `Dev`, publish branch `adf_publish`, and ADF root `/adf`. Dev is the Git authoring environment. The QA workflow deploys reviewed ADF source after the QA resources and GitHub environment are configured.

```text
Random User API -> Dev ADF Copy -> Dev ADLS Gen2 sales/landing/users.json
                -> QA ADF Copy  -> QA ADLS Gen2 sales/landing/users.json
```

`PL_LoadRandomUsers` calls `https://randomuser.me/api/?results=1000&exc=login` with ADF's HTTP connector and writes the **entire JSON response** to ADLS Gen2 with a Binary Copy activity. The `results` array holds the 1,000 user rows; `info` retains the API seed and version. ADF does not reshape the JSON. Each run replaces `users.json`. The API response changes between runs because the URL has no fixed seed.

## Configure Dev

1. The ADF linked service [LS_AdlsGen2](adf/linkedService/LS_AdlsGen2.json) points to storage account `devcgpcpocadls`. The dataset [DS_RandomUserLanding](adf/dataset/DS_RandomUserLanding.json) writes to filesystem `sales`, path `landing/users.json`. These are Dev connection values even though the artifact names are generic.
2. The linked service contains an ADF Studio `encryptedCredential`. Confirm its authentication method and test the connection in ADF Studio; the Git JSON alone does not verify that it can write. If it uses the factory's managed identity, grant `dev-cgpc-poc` **Storage Blob Data Contributor** or equivalent ADLS ACLs. Also check storage firewall access for the integration runtime. [Microsoft's ADLS Gen2 connector guide](https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-data-lake-storage) covers the supported authentication options.
3. In ADF Studio on `Dev`, inspect the linked services and debug `PL_LoadRandomUsers`. Check that the Copy activity succeeds and `sales/landing/users.json` contains one JSON object with `results` and `info`. Publish in ADF Studio when the Git changes should become Live mode resources.

## Promote ADF ingestion to QA

`.github/workflows/promote-qa.yml` runs when reviewed source is pushed to `QA`. It can also be dispatched manually after the workflow exists on GitHub's default branch. The workflow validates source, exports the ADF JSON with Microsoft's utility, prepares a temporary QA ARM artifact, deploys it to the QA ADF factory, runs `PL_LoadRandomUsers`, and checks that `landing/users.json` exists in the QA ADLS filesystem. This QA test covers ADF ingestion only.

The Dev linked service contains a factory-bound `encryptedCredential` added by ADF Studio. Microsoft's ADF export converts it to an `accountKey` parameter. The QA build script removes that key **only from the temporary deployment artifact** and substitutes the QA ADLS endpoint and filesystem. The export contains child resources, so the QA factory must already exist with its system-assigned managed identity enabled. The Git source remains unchanged. [Microsoft documents](https://learn.microsoft.com/en-us/azure/data-factory/continuous-integration-delivery-resource-manager-custom-parameters) why the Dev encrypted credential cannot be reused in another factory.

Before the first QA branch push, create the QA ADF factory and QA ADLS Gen2 account/filesystem. Enable the QA factory's system-assigned identity and grant it **Storage Blob Data Contributor** on the QA destination. The GitHub Azure deployment identity needs permission to deploy resources to the QA resource group and **Storage Blob Data Reader** on the QA ADLS filesystem for the final file check. Confirm storage firewall access for the ADF integration runtime and GitHub runner.

Configure GitHub environment `qa` with these variables:

| Variable | Value |
| --- | --- |
| `DEV_FACTORY_RESOURCE_ID` | `/subscriptions/b2ab32d1-8c22-4a4e-acdd-94746d481eb1/resourceGroups/PoCCGPC/providers/Microsoft.DataFactory/factories/dev-cgpc-poc` |
| `QA_ADF_RESOURCE_GROUP` | `PoCCGPC` |
| `QA_ADF_FACTORY_NAME` | `qa-cgpc-poc` |
| `QA_ADLS_ACCOUNT_NAME` | `qacgpcpocadls` |
| `QA_ADLS_FILE_SYSTEM` | `sales` |

Add environment secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`. The QA resources are in subscription `b2ab32d1-8c22-4a4e-acdd-94746d481eb1`. Configure Azure OIDC federation for this repository's `qa` GitHub environment, and protect the `qa` environment and QA branch before merging `Dev` into `QA`. The Azure deployment identity also needs QA ADLS read access for the final file check.

The `adf_publish` branch remains the Live publishing output for the Dev factory. QA deploys from the reviewed `QA` source branch.

## Local check

```bash
python3 scripts/check_example.py
```

The QA workflow runs this check plus `scripts/test_qa_adf_template.py` before deployment. `scripts/build_qa_adf_template.py` is needed to change the Dev ADF export into a QA deployment artifact. A live ADF Copy requires the cloud resources and permissions above.
