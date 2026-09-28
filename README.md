# PoC_CGPC: Dev API landing in ADLS

`dev-cgpc-poc` is connected to this repository on collaboration branch `Dev`, publish branch `adf_publish`, and ADF root `/adf`. The current implementation is **Dev only**.

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

There is no active QA deployment in this iteration. A future QA deployment can keep the generic ADF artifact names while supplying its own ADLS account, filesystem, credentials, and Databricks catalog `qa_bronze_ca.sales`. The current connection values are Dev specific. The existing ADF `adf_publish` branch remains the Live publishing output for this Dev factory.

## Local check

```bash
python3 scripts/check_example.py
```

This check verifies repository structure and Python syntax. A live ADF Copy and Databricks run require the cloud resources and permissions above.
