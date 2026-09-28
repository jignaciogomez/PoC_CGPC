# PoC_CGPC: Dev API landing in ADLS

`dev-cgpc-poc` is connected to this repository on collaboration branch `Dev`, publish branch `adf_publish`, and ADF root `/adf`. Dev is the Git authoring environment. The QA workflow deploys reviewed source after the QA resources and GitHub environment are configured.

```text
Random User API -> ADF Copy activity -> Dev ADLS Gen2 sales/landing/users.json
                                                |
                                                v
                             Databricks Dev job -> dev_bronze_ca.sales tables/view
```

`PL_LoadRandomUsers` calls `https://randomuser.me/api/?results=1000&exc=login` with ADF's HTTP connector and writes the **entire JSON response** to ADLS Gen2 with a Binary Copy activity. The `results` array holds the 1,000 user rows; `info` retains the API seed and version. ADF does not reshape the JSON. Each run replaces `users.json`, so run the Databricks job after the Copy succeeds. The API response changes between runs because the URL has no fixed seed.

The Dev Databricks job reads this ADLS file, extracts each `results` element, and creates:

| Object | Purpose |
| --- | --- |
| `dev_bronze_ca.sales.random_users_raw` | One raw JSON string per user, plus response metadata and load time |
| `dev_bronze_ca.sales.random_users` | Selected flattened fields |
| `dev_bronze_ca.sales.v_random_users_by_country` | User counts by country |

The Databricks workspace URL `https://dbc-db5836d9-ab81.cloud.databricks.com/` identifies Databricks on AWS. Accessing Azure ADLS from this workspace needs a separate Microsoft Entra service principal and Databricks secrets. ADF writes the lake file through its ADLS linked service; Databricks uses separate read credentials. The notebook uses [Databricks' documented cross-cloud ABFS OAuth pattern](https://docs.databricks.com/aws/en/connect/storage/azure-storage), which Databricks describes as a legacy pattern that bypasses Unity Catalog governance for the *source storage*. The resulting managed tables remain in the named catalog.

## Configure Dev

1. The ADF linked service [LS_AdlsGen2](adf/linkedService/LS_AdlsGen2.json) points to storage account `devcgpcpocadls`. The dataset [DS_RandomUserLanding](adf/dataset/DS_RandomUserLanding.json) writes to filesystem `sales`, path `landing/users.json`. These are Dev connection values even though the artifact names are generic.
2. The linked service contains an ADF Studio `encryptedCredential`. Confirm its authentication method and test the connection in ADF Studio; the Git JSON alone does not verify that it can write. If it uses the factory's managed identity, grant `dev-cgpc-poc` **Storage Blob Data Contributor** or equivalent ADLS ACLs. Also check storage firewall access for the integration runtime. [Microsoft's ADLS Gen2 connector guide](https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-data-lake-storage) covers the supported authentication options.
3. In ADF Studio on `Dev`, inspect the linked services and debug `PL_LoadRandomUsers`. Check that the Copy activity succeeds and `sales/landing/users.json` contains one JSON object with `results` and `info`. Publish in ADF Studio when the Git changes should become Live mode resources.
4. Run `databricks/sql/bootstrap_dev.sql` as an authorized catalog creator. Grant the Dev job identity permission to use `dev_bronze_ca.sales` and create/replace its tables and view.
5. Register a Microsoft Entra application for Databricks read access to the Dev ADLS filesystem. Give it **Storage Blob Data Reader** or appropriate read ACLs. Create a Databricks secret scope named `dev-adls` with keys `client-id`, `client-secret`, and `tenant-id`. Do not commit credential values.
6. Supply `BUNDLE_VAR_cluster_id`, then run `databricks bundle validate -t dev` and `databricks bundle deploy -t dev` from `databricks/`. Start the Dev job after the ADF Copy. Its cluster must support the ABFS OAuth configuration and network access to Azure storage and Microsoft Entra ID.

## Promote ADF ingestion to QA

`.github/workflows/promote-qa.yml` runs when reviewed source is pushed to `QA`. It can also be dispatched manually after the workflow exists on GitHub's default branch. The workflow validates source, exports the ADF JSON with Microsoft's utility, prepares a temporary QA ARM artifact, deploys it to the QA ADF factory, runs `PL_LoadRandomUsers`, and checks that `landing/users.json` exists in the QA ADLS filesystem. This first QA test covers **ADF ingestion only**. Databricks deployment and `qa_bronze_ca.sales` are a later step.

The Dev linked service contains a factory-bound `encryptedCredential` added by ADF Studio. The QA build script removes it **only from the temporary deployment artifact**, substitutes the QA ADLS endpoint and filesystem, and uses the QA factory's system-assigned managed identity. The Git source remains unchanged. [Microsoft documents](https://learn.microsoft.com/en-us/azure/data-factory/continuous-integration-delivery-resource-manager-custom-parameters) why that encrypted credential cannot be reused in another factory.

Before the first QA branch push, create the QA ADF factory and QA ADLS Gen2 account/filesystem. Enable the QA factory's system-assigned identity and grant it **Storage Blob Data Contributor** on the QA destination. The GitHub Azure deployment identity needs permission to deploy resources to the QA resource group and **Storage Blob Data Reader** on the QA ADLS filesystem for the final file check. Confirm storage firewall access for the ADF integration runtime and GitHub runner.

Configure GitHub environment `qa` with these variables:

| Variable | Value |
| --- | --- |
| `DEV_FACTORY_RESOURCE_ID` | Full Azure resource ID of `dev-cgpc-poc` (needed by the ADF export utility) |
| `QA_ADF_RESOURCE_GROUP` | `PoCCGPC` |
| `QA_ADF_FACTORY_NAME` | `qa-cgpc-poc` |
| `QA_ADLS_ACCOUNT_NAME` | `qacgpcpocadls` |
| `QA_ADLS_FILE_SYSTEM` | QA filesystem/container name (still to confirm) |

Add environment secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`. The QA resources are in subscription `b2ab32d1-8c22-4a4e-acdd-94746d481eb1`. Configure Azure OIDC federation for this repository's `qa` GitHub environment, and protect the `qa` environment and QA branch before merging `Dev` into `QA`. The Azure deployment identity also needs QA ADLS read access for the final file check.

The `adf_publish` branch remains the Live publishing output for the Dev factory. QA deploys from the reviewed `QA` source branch.

## Local check

```bash
python3 scripts/check_example.py
```

This check verifies repository structure and Python syntax. A live ADF Copy and Databricks run require the cloud resources and permissions above.
