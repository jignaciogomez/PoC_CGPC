# PoC_CGPC: Dev API landing in ADLS

`dev-cgpc-poc` is connected to this repository on collaboration branch `Dev`, publish branch `adf_publish`, and ADF root `/adf`. The current implementation is **Dev only**.

```text
Random User API -> ADF Copy activity -> Dev ADLS Gen2 landing/randomuser/users.json
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

The Databricks workspace URL `https://dbc-db5836d9-ab81.cloud.databricks.com/` identifies Databricks on AWS. Accessing Azure ADLS from this workspace needs a separate Microsoft Entra service principal and Databricks secrets. The ADF managed identity only writes the lake file. The notebook uses [Databricks' documented cross-cloud ABFS OAuth pattern](https://docs.databricks.com/aws/en/connect/storage/azure-storage), which Databricks describes as a legacy pattern that bypasses Unity Catalog governance for the *source storage*. The resulting managed tables remain in the named catalog.

## Configure Dev

1. In `adf/linkedService/LS_DevAdlsGen2.json`, replace `replacewithdevaccount` with the real **Dev** ADLS Gen2 storage account. In `adf/dataset/DS_DevRandomUserLanding.json`, replace `replace-with-dev-filesystem` with its existing filesystem (container). The configured output is `landing/randomuser/users.json`.
2. Give the system-assigned identity of `dev-cgpc-poc` **Storage Blob Data Contributor** on the Dev storage account or equivalent filesystem/folder ACLs. The ADF identity object ID is visible in the factory's Azure portal Identity page. Confirm the storage firewall allows the selected ADF integration runtime. [Microsoft's ADLS Gen2 connector guide](https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-data-lake-storage) covers these settings.
3. In ADF Studio on `Dev`, inspect the HTTP and ADLS linked services, test their connections, then debug `PL_LoadRandomUsers`. Check the Copy activity succeeded and `users.json` contains one JSON object with `results` and `info`. Publish in ADF Studio when the Git changes should become Live mode resources.
4. Run `databricks/sql/bootstrap_dev.sql` as an authorized catalog creator. Grant the Dev job identity permission to use `dev_bronze_ca.sales` and create/replace its tables and view.
5. Register a Microsoft Entra application for Databricks read access to the Dev ADLS filesystem. Give it **Storage Blob Data Reader** or appropriate read ACLs. Create a Databricks secret scope named `dev-adls` with keys `client-id`, `client-secret`, and `tenant-id`. Do not commit credential values.
6. Supply `BUNDLE_VAR_cluster_id`, `BUNDLE_VAR_storage_account`, and `BUNDLE_VAR_file_system`, then run `databricks bundle validate -t dev` and `databricks bundle deploy -t dev` from `databricks/`. Start the Dev job after the ADF Copy. Its cluster must support the ABFS OAuth configuration and network access to Azure storage and Microsoft Entra ID.

There is no active QA deployment in this iteration. The future promotion can deploy reviewed source to a QA factory and change its ADLS account, filesystem, and Databricks catalog to `qa_bronze_ca.sales` through environment configuration. The existing ADF `adf_publish` branch remains the Live publishing output for this Dev factory.

## Local check

```bash
python3 scripts/check_example.py
```

This check verifies repository structure and Python syntax. A live ADF Copy and Databricks run require the cloud resources and permissions above.
