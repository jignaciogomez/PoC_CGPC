# ADF promotion PoC

The DEV factory `dev-cgpc-poc` is connected to this repository on collaboration branch `Dev` with ADF root `/adf`. Its publish branch is `adf_publish`. Only DEV uses ADF Git integration; downstream factories receive reviewed source through deployments as their workflows are added. The intended Git promotion path is feature branch → `Dev` → `QA` → `UAT` → `Prod`, with a protected branch and PR review at every merge. Configure those branch rules in GitHub; the current deployment workflow implements the `QA` step.

The example pipeline `PL_LoadRandomUsers` copies the complete JSON response from `https://randomuser.me/api/?results=1000&exc=login` to `sales/landing/users.json`. It does not flatten the `results` array. Its pipeline, dataset, and linked service names remain the same in every factory.

## Environment configuration

ADF's [custom ARM parameter definition](adf/arm-template-parameters-definition.json) exposes the URL of each `AzureBlobFS` linked service and the filesystem of each dataset that has one. The `-` action removes the DEV value as an ARM default, so the deployment needs an explicit target value. For the current source, Microsoft's export generates `LS_AdlsGen2_url` and `DS_RandomUserLanding_fileSystem` as required parameters. The QA values are in [deploy/qa.parameters.json](deploy/qa.parameters.json); the target `factoryName` comes from the GitHub `qa` environment variable. The workflow never rewrites the exported template.

| GitHub `qa` environment variable | Value |
| --- | --- |
| `DEV_FACTORY_RESOURCE_ID` | `/subscriptions/b2ab32d1-8c22-4a4e-acdd-94746d481eb1/resourceGroups/PoCCGPC/providers/Microsoft.DataFactory/factories/dev-cgpc-poc` |
| `QA_ADF_RESOURCE_GROUP` | `PoCCGPC` |
| `QA_ADF_FACTORY_NAME` | `qa-cgpc-poc` |

Set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` as GitHub `qa` environment secrets. Configure Azure federated identity for this repository's `qa` environment and grant the deployment identity permission to deploy ADF child resources in `PoCCGPC`. The QA factory must already exist. Restrict the `qa` GitHub environment and protect the `QA` branch as appropriate for the PR review process.

Both factories' `LS_AdlsGen2` linked services use their respective factory managed identities. Grant each factory identity data-plane write access to its own storage destination (for example, Storage Blob Data Contributor) and verify any storage firewall and ADLS ACL settings before *running* a pipeline. Deployment itself does not run or inspect a pipeline. The existing QA storage account was previously reported as lacking hierarchical namespace; check its storage configuration when preparing an end-to-end ADLS Gen2 runtime test.

## QA deployment

When reviewed changes land on `QA`, [the workflow](.github/workflows/promote-qa.yml) exports all ADF source with Microsoft's ADF utility, validates the environment configuration, then runs ARM validation and incremental deployment against `qa-cgpc-poc`. An incremental deployment updates the resources included in the full export; it does not delete resources omitted from the export. A manual dispatch from `QA` can redeploy the reviewed state after an accidental change in the QA factory. The workflow can be dispatched manually once available on GitHub's default branch.

[scripts/prepare_adf_parameters.py](scripts/prepare_adf_parameters.py) checks that QA configuration names match the actual export and that every required parameter has a QA value. It adds `factoryName` to a temporary effective parameter file. It also rejects a source linked service with `encryptedCredential`, which ADF encrypts for one factory and cannot promote as-is. This is a validation guard, not credential stripping. The exported ARM template is passed to Azure unchanged.

When adding a linked service, dataset, or pipeline in DEV, use stable logical names. Add any new environment-specific properties to the ADF parameter definition, then add the generated QA parameter names and values to `deploy/qa.parameters.json`. The workflow will fail clearly if a new required parameter has no QA value. Never commit secret values to the parameter file; use an Azure Key Vault reference or protected environment secret for those properties. Add UAT and Prod workflows and configuration files when those target factories are ready, using the same export and parameter preparation approach.

## Inspect the generated artifacts locally

From the repository root, with Node.js and Python installed:

```bash
python3 scripts/test_prepare_adf_parameters.py
cd ci/adf
npm install --no-audit --no-fund
npm run build -- export ../../adf "/subscriptions/b2ab32d1-8c22-4a4e-acdd-94746d481eb1/resourceGroups/PoCCGPC/providers/Microsoft.DataFactory/factories/dev-cgpc-poc" ../../build/adf
cd ../..
python3 scripts/prepare_adf_parameters.py \
  --source-root adf \
  --template build/adf/ARMTemplateForFactory.json \
  --configuration deploy/qa.parameters.json \
  --factory-name qa-cgpc-poc \
  --output build/adf/qa.parameters.json
```

Inspect `build/adf/ARMTemplateForFactory.json` and `build/adf/qa.parameters.json`. `build/` is ignored by Git because these files are generated for each deployment. `ARMTemplateParametersForFactory.json`, also created by the ADF utility, contains DEV export values and is **not** the parameter file passed to the QA deployment.
