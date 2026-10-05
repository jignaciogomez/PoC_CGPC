"""
schema_builder.py
-----------------
Generates and applies Delta table DDL from YAML schema definition files.

YAML schema format  (config/data_platform/schemas/<schema_name>.yml)
------------------------------------------------------
schema: <schema_name>
tables:
  - name: <table_name>
    comment: "<table comment>"           # optional
    using: DELTA                          # optional, defaults to DELTA
    partitioned_by: [col1, col2]          # optional
    columns:
      - name: <col_name>
        type: <spark_type>                # STRING, TIMESTAMP, INT, BIGINT, BOOLEAN,
                                          # DATE, "DECIMAL(p,s)", etc.
        not_null: true                    # optional, defaults to false
        default: <sql_default_expr>       # optional  e.g. "false", "'active'"
        comment: "<col comment>"          # optional
    primary_key:                          # optional
      name: <constraint_name>
      columns: [col1, col2]
        foreign_keys:                         # optional list (ignored by this process)
            - name: <constraint_name>
                columns: [local_col1]
                ref_table: <schema.table>
                ref_columns: [ref_col1]
        check_constraints:                    # optional list (ignored by this process)
            - name: <constraint_name>
                expression: "<sql expression>"
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from yaml_utils import load_yaml
from target_guard import check_no_catalog_override


class SchemaBuilder:
    """Reads YAML schema definitions and applies CREATE/ALTER changes via spark.sql()."""

    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        spark: Any,
        catalog: str,
        allow_drop_columns: bool = False,
        fail_on_type_drift: bool = True,
    ) -> None:
        self.spark = spark
        self.catalog = catalog
        self.default_catalog = catalog
        self.allow_drop_columns = allow_drop_columns
        self.fail_on_type_drift = fail_on_type_drift

    # ------------------------------------------------------------------
    # Internal DDL builders
    # ------------------------------------------------------------------

    @staticmethod
    def _esc(text: str) -> str:
        """Escape single quotes for use inside SQL string literals."""
        return str(text).replace("'", "''")

    @classmethod
    def _validate_identifier(cls, identifier: str, label: str) -> str:
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{label} must be a non-empty string.")
        if not cls._IDENTIFIER_RE.match(identifier):
            raise ValueError(
                f"{label}={identifier!r} is invalid. Only letters, numbers, and underscore are allowed "
                "and it must not start with a number."
            )
        return identifier

    @classmethod
    def _qi(cls, identifier: str, label: str = "identifier") -> str:
        ident = cls._validate_identifier(identifier, label)
        return f"`{ident}`"

    @classmethod
    def _qfqn(cls, fqn: str, label: str = "table") -> str:
        parts = str(fqn).split(".")
        if len(parts) < 2:
            raise ValueError(f"{label}={fqn!r} must be schema-qualified.")
        return ".".join(cls._qi(part, f"{label} part") for part in parts)

    def _col_fragment(self, col: dict[str, Any], include_default: bool = True) -> str:
        col_name = self._qi(col["name"], "column name")
        parts: list[str] = [f"  {col_name}", str(col["type"])]
        if col.get("not_null"):
            parts.append("NOT NULL")
        if include_default and "default" in col:
            parts.append(f"DEFAULT {col['default']}")
        if col.get("comment"):
            parts.append(f"COMMENT '{self._esc(col['comment'])}'")
        return " ".join(parts)

    def _col_fragment_for_alter_add(self, col: dict[str, Any]) -> str:
        # Databricks ADD COLUMNS supports name/type/comment reliably for existing tables.
        col_name = self._qi(col["name"], "column name")
        parts: list[str] = [f"{col_name}", str(col["type"])]
        if col.get("comment"):
            parts.append(f"COMMENT '{self._esc(col['comment'])}'")
        return " ".join(parts)

    def _constraint_fragments(self, table: dict[str, Any]) -> list[str]:
        frags: list[str] = []

        pk = table.get("primary_key")
        if pk:
            cols = ", ".join(self._qi(col, "pk column") for col in pk["columns"])
            pk_name = self._qi(pk["name"], "primary key name")
            frags.append(f"  CONSTRAINT {pk_name} PRIMARY KEY ({cols})")

        # Foreign key constraints are intentionally ignored in this process.

        # Check constraints are intentionally ignored to keep compatibility
        # with runtimes that only support PRIMARY KEY / FOREIGN KEY constraints.

        return frags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _validate_table_definition(self, table: dict[str, Any]) -> None:
        self._validate_identifier(table["name"], "table name")
        cols = table.get("columns", [])
        if not cols:
            raise ValueError(f"Table {table['name']!r} must define at least one column.")

        seen: set[str] = set()
        for col in cols:
            col_name = self._validate_identifier(col["name"], "column name")
            col_name_lower = col_name.lower()
            if col_name_lower in seen:
                raise ValueError(f"Table {table['name']!r} has duplicate column name {col_name!r}.")
            seen.add(col_name_lower)

    def _table_not_found(self, exc: Exception) -> bool:
        if hasattr(exc, "getErrorClass"):
            error_class = exc.getErrorClass()
            return error_class in {"TABLE_OR_VIEW_NOT_FOUND", "SCHEMA_NOT_FOUND"}
        return False

    def _table_exists(self, fqn: str) -> bool:
        try:
            self.spark.sql(f"DESCRIBE TABLE {self._qfqn(fqn)}")
            return True
        except Exception as exc:
            if self._table_not_found(exc):
                return False
            raise RuntimeError(f"Failed while checking table existence for {fqn}: {exc}") from exc

    def _existing_columns(self, fqn: str) -> dict[str, Any]:
        schema = self.spark.sql(f"SELECT * FROM {self._qfqn(fqn)} LIMIT 0").schema
        return {field.name.lower(): field for field in schema.fields}

    def _reconcile_existing_table(self, schema: str, table: dict[str, Any]) -> None:
        fqn = f"{self.catalog}.{schema}.{table['name']}"
        fqn_sql = self._qfqn(fqn)
        desired_cols_by_name = {col["name"].lower(): col for col in table.get("columns", [])}
        existing_cols_by_name = self._existing_columns(fqn)

        to_add = [
            desired_cols_by_name[name]
            for name in desired_cols_by_name
            if name not in existing_cols_by_name
        ]
        to_drop = [
            existing_cols_by_name[name].name
            for name in existing_cols_by_name
            if name not in desired_cols_by_name
        ]

        # Refuse incompatible definitions before making additive changes.
        common_names = set(desired_cols_by_name).intersection(existing_cols_by_name)
        for name in sorted(common_names):
            desired_type = str(desired_cols_by_name[name]["type"]).lower().replace(" ", "")
            existing_type = existing_cols_by_name[name].dataType.simpleString().lower().replace(" ", "")
            if desired_type != existing_type and self.fail_on_type_drift:
                raise ValueError(
                    f"Type drift for {fqn}.{name}: existing={existing_type}, yaml={desired_type}"
                )

        for col in to_add:
            if col.get("not_null"):
                raise ValueError(
                    f"Cannot add required column {fqn}.{col['name']} automatically; "
                    "backfill and enforce NOT NULL through a reviewed migration"
                )
        for col in to_add:
            add_sql = f"ALTER TABLE {fqn_sql} ADD COLUMNS ({self._col_fragment_for_alter_add(col)})"
            self.spark.sql(add_sql)
            print(f"[schema_builder]   + column added: {fqn}.{col['name']}")

        # Apply defaults after structural changes, using ALTER TABLE flow that
        # enables the required Delta feature first.
        self._apply_defaults(fqn, table)

        if to_drop:
            if self.allow_drop_columns:
                for col_name in to_drop:
                    drop_sql = f"ALTER TABLE {fqn_sql} DROP COLUMN {self._qi(col_name, 'column name')}"
                    self.spark.sql(drop_sql)
                    print(f"[schema_builder]   - column dropped: {fqn}.{col_name}")
            else:
                print(
                    f"[schema_builder]   ! {fqn}: {len(to_drop)} extra column(s) found in table and kept "
                    "(set allow_drop_columns=true to drop)."
                )

        common_names = set(desired_cols_by_name).intersection(existing_cols_by_name)
        for name in sorted(common_names):
            desired_type = str(desired_cols_by_name[name]["type"]).lower().replace(" ", "")
            existing_type = existing_cols_by_name[name].dataType.simpleString().lower().replace(" ", "")
            if desired_type != existing_type:
                msg = (
                    f"[schema_builder] type drift detected for {fqn}.{existing_cols_by_name[name].name}: "
                    f"existing={existing_type}, yaml={desired_type}."
                )
                if self.fail_on_type_drift:
                    raise ValueError(msg)
                print(f"[schema_builder]   ! {msg}")

        if table.get("primary_key"):
            print(
                f"[schema_builder]   ! {fqn}: constraint reconciliation for existing tables is not automated yet."
            )

        if table.get("check_constraints"):
            print(
                f"[schema_builder]   ! {fqn}: check_constraints are ignored by this process."
            )

        if not to_add and (not to_drop or not self.allow_drop_columns):
            print(f"[schema_builder]   = no column changes: {fqn}")

    def _apply_defaults(self, fqn: str, table: dict[str, Any]) -> None:
        defaults = [col for col in table.get("columns", []) if "default" in col]
        if not defaults:
            return

        fqn_sql = self._qfqn(fqn)
        self.spark.sql(
            f"ALTER TABLE {fqn_sql} SET TBLPROPERTIES "
            "('delta.feature.allowColumnDefaults' = 'supported')"
        )

        for col in defaults:
            col_sql = self._qi(col["name"], "column name")
            self.spark.sql(
                f"ALTER TABLE {fqn_sql} ALTER COLUMN {col_sql} SET DEFAULT {col['default']}"
            )
        print(f"[schema_builder]   + defaults applied: {fqn}")

    def build_ddl(self, schema: str, table: dict[str, Any]) -> str:
        """Return the full CREATE TABLE IF NOT EXISTS DDL string for *table*."""
        fqn      = f"{self.catalog}.{schema}.{table['name']}"
        fqn_sql  = self._qfqn(fqn)
        # DEFAULT is applied later via ALTER TABLE after enabling the Delta feature.
        col_frags = [self._col_fragment(c, include_default=False) for c in table["columns"]]
        con_frags = self._constraint_fragments(table)
        body      = ",\n".join(col_frags + con_frags)

        ddl = (
            f"CREATE TABLE IF NOT EXISTS {fqn_sql} (\n{body}\n)\n"
            f"USING {table.get('using', 'DELTA')}"
        )

        if table.get("partitioned_by"):
            part_cols = ", ".join(self._qi(c, "partition column") for c in table["partitioned_by"])
            ddl += f"\nPARTITIONED BY ({part_cols})"

        if table.get("comment"):
            ddl += f"\nCOMMENT '{self._esc(table['comment'])}'"

        return ddl

    def apply_schema_file(self, yaml_path: str | Path) -> int:
        """
        Create schema (if needed) and all tables defined in *yaml_path*.
        Returns the number of tables processed.
        """
        definition = load_yaml(yaml_path)

        if not isinstance(definition, dict):
            raise ValueError(f"Invalid schema YAML in {yaml_path}: expected a mapping at root.")

        check_no_catalog_override(definition, str(yaml_path))
        self.catalog = self.default_catalog
        self._validate_identifier(self.catalog, "catalog")
        schema = definition["schema"]
        self._validate_identifier(schema, "schema name")
        catalog_sql = self._qi(self.catalog, "catalog")
        schema_sql = self._qi(schema, "schema")
        self.spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_sql}.{schema_sql}")
        print(f"[schema_builder] schema  {self.catalog}.{schema}  ensured.")

        tables = definition.get("tables", [])
        for table in tables:
            self._validate_table_definition(table)
            fqn = f"{self.catalog}.{schema}.{table['name']}"
            if not self._table_exists(fqn):
                ddl = self.build_ddl(schema, table)
                print(f"[schema_builder]   + creating {fqn}")
                self.spark.sql(ddl)
                self._apply_defaults(fqn, table)
            else:
                print(f"[schema_builder]   ~ altering {fqn}")
                self._reconcile_existing_table(schema, table)

        print(
            f"[schema_builder] ✓ {schema}: {len(tables)} table(s) applied.\n"
        )
        return len(tables)

    def apply_all(self, schemas_dir: str | Path) -> None:
        """
        Apply every *.yml file found in *schemas_dir* (processed in sorted order).
        Raises FileNotFoundError if the directory contains no YAML files.
        """
        paths = sorted(Path(schemas_dir).glob("*.yml"))
        if not paths:
            raise FileNotFoundError(f"No *.yml files found in: {schemas_dir}")

        for path in paths:
            definition = load_yaml(path)
            check_no_catalog_override(definition, str(path))

        total = sum(self.apply_schema_file(p) for p in paths)
        print(
            f"[schema_builder] Done — {total} table(s) across "
            f"{len(paths)} schema file(s)."
        )
