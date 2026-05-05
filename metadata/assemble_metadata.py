"""
Metadata Assembler
==================
Auto-discovers schema from Glue Data Catalog + Feature Store,
combines with tagged metadata (descriptions, join keys),
and outputs a structured context for text-to-SQL prompts.

Scales to 40+ tables — just tag new tables with tag_glue_tables.py
and this assembler picks them up automatically.

Usage:
  python metadata/assemble_metadata.py                  # print to stdout
  python metadata/assemble_metadata.py --output schema  # save to metadata/schema_context.json
"""

import argparse
import json
import boto3
from collections import defaultdict

glue = boto3.client("glue")
sm = boto3.client("sagemaker")

DB = "sagemaker_featurestore"


def get_all_tables() -> list:
    """Fetch all tables from the Glue database."""
    tables = []
    paginator = glue.get_paginator("get_tables")
    for page in paginator.paginate(DatabaseName=DB):
        tables.extend(page["TableList"])
    return tables


def get_feature_group_primary_keys() -> dict:
    """Pull record_identifier from SageMaker Feature Store for each group."""
    pk_map = {}
    paginator = sm.get_paginator("list_feature_groups")
    for page in paginator.paginate():
        for fg in page["FeatureGroupSummaries"]:
            name = fg["FeatureGroupName"]
            try:
                desc = sm.describe_feature_group(FeatureGroupName=name)
                pk_map[name] = desc["RecordIdentifierFeatureName"]
            except Exception:
                pass
    return pk_map


def assemble_table_metadata(table: dict, pk_map: dict) -> dict:
    """Build metadata for a single table."""
    params = table.get("Parameters", {})
    columns = table["StorageDescriptor"]["Columns"]

    # Skip system metadata columns for text-to-SQL context
    skip_cols = {"write_time", "api_invocation_time", "is_deleted"}

    col_list = []
    for col in columns:
        if col["Name"] in skip_cols:
            continue
        col_list.append({
            "name": col["Name"],
            "type": col["Type"],
            "description": col.get("Comment", ""),
        })

    # Try to match to a Feature Store group for primary key
    primary_key = None
    for fg_name, pk in pk_map.items():
        # Glue table name is the FG name with hyphens→underscores + numeric suffix
        if table["Name"].startswith(fg_name.replace("-", "_")):
            primary_key = pk
            break

    return {
        "glue_table_name": table["Name"],
        "friendly_name": params.get("friendly_name", table["Name"]),
        "description": table.get("Description", ""),
        "domain": params.get("domain", ""),
        "primary_key": primary_key or params.get("join_keys", ""),
        "join_keys": [k.strip() for k in params.get("join_keys", "").split(",") if k.strip()],
        "columns": col_list,
    }


def infer_relationships(tables_meta: list) -> list:
    """Auto-detect join relationships by matching join_keys across tables."""
    # Build index: join_key → list of tables that have it
    key_to_tables = defaultdict(list)
    for t in tables_meta:
        for key in t["join_keys"]:
            key_to_tables[key].append(t["friendly_name"])

    relationships = []
    for key, table_names in key_to_tables.items():
        if len(table_names) > 1:
            relationships.append({
                "join_key": key,
                "tables": table_names,
                "type": "shared_key",
                "description": f"Tables can be joined on '{key}'"
            })
    return relationships


def build_sql_prompt_context(catalog: dict) -> str:
    """Format the catalog as a text block for LLM system prompts."""
    lines = []
    lines.append(f"DATABASE: {catalog['database']}")
    lines.append(f"TABLES: {len(catalog['tables'])}")
    lines.append("")

    for t in catalog["tables"]:
        lines.append(f"TABLE: {t['glue_table_name']}")
        lines.append(f"  Friendly name: {t['friendly_name']}")
        lines.append(f"  Description: {t['description']}")
        lines.append(f"  Primary key: {t['primary_key']}")
        lines.append(f"  Domain: {t['domain']}")
        lines.append(f"  Columns:")
        for col in t["columns"]:
            desc = f" -- {col['description']}" if col["description"] else ""
            lines.append(f"    {col['name']} ({col['type']}){desc}")
        lines.append("")

    if catalog["relationships"]:
        lines.append("RELATIONSHIPS:")
        for rel in catalog["relationships"]:
            lines.append(f"  Join key '{rel['join_key']}' shared by: {', '.join(rel['tables'])}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", choices=["json", "schema", "prompt"], default="prompt",
                        help="Output format: json, schema (save file), or prompt (print)")
    args = parser.parse_args()

    print("Discovering tables from Glue Data Catalog...", flush=True)
    tables = get_all_tables()
    print(f"Found {len(tables)} tables in {DB}")

    print("Fetching Feature Store primary keys...", flush=True)
    pk_map = get_feature_group_primary_keys()
    print(f"Found {len(pk_map)} feature groups")

    # Assemble metadata for each table
    tables_meta = [assemble_table_metadata(t, pk_map) for t in tables]

    # Infer relationships
    relationships = infer_relationships(tables_meta)

    catalog = {
        "database": DB,
        "tables": tables_meta,
        "relationships": relationships,
    }

    if args.output == "json":
        print(json.dumps(catalog, indent=2))
    elif args.output == "schema":
        out_path = "metadata/schema_context.json"
        with open(out_path, "w") as f:
            json.dumps(catalog, indent=2)
            json.dump(catalog, f, indent=2)
        print(f"\nSaved to {out_path}")

        # Also save the prompt-ready version
        prompt_path = "metadata/schema_prompt.txt"
        with open(prompt_path, "w") as f:
            f.write(build_sql_prompt_context(catalog))
        print(f"Saved prompt context to {prompt_path}")
    else:
        print("\n" + build_sql_prompt_context(catalog))


if __name__ == "__main__":
    main()
