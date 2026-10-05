#!/usr/bin/env python3
"""Local checks for promotion boundaries that do not require a workspace."""

import ast
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "databricks" / "src"))
from target_guard import TARGET_CATALOGS, check_target
from yaml_utils import load_yaml
from workspace_paths import require_bundle_directory


class PromotionChecks(unittest.TestCase):
    def test_bundle_target_catalogs_match_runtime_guard(self):
        bundle = load_yaml(ROOT / "databricks/bundles/databricks.yml")
        for target, (platform, bronze) in TARGET_CATALOGS.items():
            variables = bundle["targets"][target]["variables"]
            self.assertEqual(variables["platform_catalog"], platform)
            self.assertEqual(variables["bronze_catalog"], bronze)

    def test_job_paths_resolve_to_versioned_files(self):
        bundle_root = ROOT / "databricks/bundles"
        resource_file = bundle_root / "resources/jobs_data_platform.yml"
        jobs = load_yaml(resource_file)["resources"]["jobs"]
        for job in jobs.values():
            for task in job["tasks"]:
                notebook = (resource_file.parent / task["notebook_task"]["notebook_path"]).resolve()
                self.assertTrue(notebook.is_file(), notebook)
                for key in ("schemas_dir", "seed_data_dir", "dml_dir"):
                    value = task["notebook_task"].get("base_parameters", {}).get(key)
                    if value:
                        self.assertTrue(value.startswith("${workspace.file_path}/"))
                        relative = value.removeprefix("${workspace.file_path}/")
                        self.assertTrue((bundle_root / relative).is_dir(), relative)

    def test_bundle_directory_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(require_bundle_directory(directory, "input"), Path(directory))
            with self.assertRaises(FileNotFoundError):
                require_bundle_directory(directory + "/missing", "input")

    def test_qa_cannot_use_dev_catalog_or_workspace(self):
        with self.assertRaises(ValueError):
            check_target("qa", "dev_scratch_ca", "qa_bronze_ca",
                         "qa.example.net", "https://qa.example.net")
        with self.assertRaises(ValueError):
            check_target("qa", "edp_qa", "qa_bronze_ca",
                         "dev.example.net", "https://qa.example.net")
        check_target("qa", "edp_qa", "qa_bronze_ca",
                     "qa.example.net", "https://qa.example.net")

    def test_duplicate_yaml_keys_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yml"
            path.write_text("target_table: config.first\ntarget_table: config.second\n")
            with self.assertRaisesRegex(ValueError, "Duplicate YAML key"):
                load_yaml(path)

    def test_definitions_have_no_target_overrides(self):
        folder = ROOT / "databricks/bundles/config/data_platform"
        for path in folder.rglob("*.yml"):
            with self.subTest(path=path):
                document = load_yaml(path)
                self.assertNotIn("catalog", document)
                if "rows" in document:
                    for row in document["rows"]:
                        self.assertNotIn("environment", row)

    def test_python_sources_parse(self):
        for path in (ROOT / "databricks/src").glob("*.py"):
            with self.subTest(path=path):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


if __name__ == "__main__":
    unittest.main()
