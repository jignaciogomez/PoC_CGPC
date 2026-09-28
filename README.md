# PoC_CGPC: ADF and Databricks promotion

`dev-cgpc-poc` is Git-connected to this repository with collaboration branch `Dev`, publish branch `adf_publish`, and ADF root folder `/adf`. This example uses one ADF pipeline to start and monitor a Databricks Job. The job fetches [Random User API](https://randomuser.me/documentation) data from `https://randomuser.me/api/?results=1000&exc=login` and creates these objects:

| Target | Raw table | Flattened table | View |
| --- | --- | --- | --- |
| DEV | `dev_bronze_ca.sales.random_users_raw` | `dev_bronze_ca.sales.random_users` | `dev_bronze_ca.sales.v_random_users_by_country` |
| QA | `qa_bronze_ca.sales.random_users_raw` | `qa_bronze_ca.sales.random_users` | `qa_bronze_ca.sales.v_random_users_by_country` |

The supplied Databricks URL, `https://dbc-db5836d9-ab81.cloud.databricks.com`, identifies a **Databricks on AWS** workspace. ADF's native Azure Databricks linked service is for Azure Databricks, so `PL_LoadRandomUsers` uses ADF Web activities and the Databricks Jobs REST API. It gets a Databricks service-principal token from Azure Key Vault through the ADF managed identity, starts the target job, polls the run, and fails the pipeline when the job fails. The notebook itself retrieves the 1,000-user API response; ADF does not pass a large JSON payload between activities.

The API omits `login` as requested. The raw table keeps each user's JSON plus the response seed/version and load time. The flattened table exposes selected fields; the view counts users by country. Each run replaces the two demonstration tables. The API response changes between runs because the requested URL has no fixed seed.

## Promotion flow

1. Author ADF JSON in `Dev` under `/adf`. Develop the notebook in the `dev` Databricks bundle target. Publish in ADF Studio when DEV Live mode should run; that generates `adf_publish`.
2. Review a PR from `Dev` to `QA`. A push to `QA` runs `.github/workflows/promote-qa.yml`, protected by the GitHub `qa` environment.
3. The workflow exports an ARM template from the reviewed QA branch using the [ADF automated export utility](https://learn.microsoft.com/en-us/azure/data-factory/continuous-integration-delivery-improvements), deploys the Databricks bundle target `qa`, reads the resulting QA job ID, and deploys the ADF template with QA factory, job, and Key Vault settings.
4. Optionally run `PL_LoadRandomUsers` as a smoke test and inspect the QA table count and view. UAT/PROD can later use the same reviewed source and their own catalogs, secrets, identities, and protected environments.

The `adf_publish` branch is not the QA deployment input. ADF ARM parameters change target configuration without replacing arbitrary `dev` strings in source. `scripts/make_adf_parameters.py` checks that the [custom ADF parameter definition](https://learn.microsoft.com/en-us/azure/data-factory/continuous-integration-delivery-resource-manager-custom-parameters) produced the expected parameters.

## Remaining setup

1. Create or identify a Unity Catalog-capable Databricks cluster with HTTPS egress to `randomuser.me`. Set `BUNDLE_VAR_cluster_id` for local DEV bundle deployment and `QA_DATABRICKS_CLUSTER_ID` in the GitHub `qa` environment. The provided URL alone does not identify a cluster.
2. Run `databricks/sql/bootstrap_dev.sql` and `databricks/sql/bootstrap_qa.sql` as an authorized catalog creator. Grant the DEV and QA job run identities access to their respective catalogs and `sales` schema. If both targets share this workspace, catalog grants must enforce environment isolation.
3. Deploy the `dev` bundle target. Get the DEV job ID from `databricks bundle summary -t dev --output json` at `resources.jobs.load_random_users.id`; put it in `adf/factory/dev-cgpc-poc.json` as global parameter `databricksJobId`. The current value `0` is a placeholder.
4. Create an Azure Key Vault secret containing a Databricks service-principal access token with permission to run the DEV job. Give the DEV ADF managed identity Key Vault **Get Secret** access. Set the `databricksTokenSecretUrl` global parameter to that secret's URL. Set the QA equivalent in its own vault (or isolated secret) and grant the QA factory identity access. ADF reads the token with [secure Web activity output](https://learn.microsoft.com/en-us/azure/data-factory/how-to-use-azure-key-vault-secrets-pipeline-activities); it is never stored in Git.
5. Create a QA ADF factory if one does not yet exist. Set these GitHub `qa` environment variables: `DEV_FACTORY_RESOURCE_ID`, `QA_ADF_RESOURCE_GROUP`, `QA_ADF_FACTORY_NAME`, `QA_DATABRICKS_CLUSTER_ID`, and `QA_DATABRICKS_TOKEN_SECRET_URL`.
6. Set GitHub `qa` environment secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET`. Configure Azure OIDC federation for ARM deployment and a Databricks service principal with [OAuth M2M](https://docs.databricks.com/aws/en/dev-tools/cli/authentication) access for bundle deployment. The ADF runtime token in Key Vault and the CI deployment credentials are separate.
7. Protect `QA` and the `qa` environment before merging. On the first QA branch push, the workflow will attempt deployment; configure the resources and settings above first. GitHub manual dispatch requires the workflow file on the default branch, so the QA push trigger is the initial path.

The pipeline uses the current Databricks [Jobs run-now API](https://docs.databricks.com/api/workspace/jobs/runnow) and polls [run status](https://docs.databricks.com/api/workspace/jobs/getrun). Network access from ADF to the AWS workspace and from Databricks compute to Random User must be permitted. Actual cloud deployment and runtime behavior still need validation with the target resources.

## Local checks

```bash
python3 scripts/check_example.py
python3 -c "import ast; ast.parse(open('databricks/notebooks/load_random_users.py').read())"
```
