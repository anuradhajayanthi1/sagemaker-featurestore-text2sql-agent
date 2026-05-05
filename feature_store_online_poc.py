"""
SageMaker Feature Store POC — Online Store Only
================================================
Creates 4 feature groups from CSV files and ingests records
into the SageMaker Feature Store online store for real-time lookups.

Uses sagemaker SDK v3 (sagemaker.core) API.

Prerequisites:
  pip install sagemaker boto3 pandas
  - AWS credentials configured (Isengard / env vars / profile)

Usage:
  cd feature-store-poc
  python feature_store_online_poc.py
"""

import time
import pandas as pd
import boto3
from sagemaker.core.resources import FeatureGroup
from sagemaker.core.shapes.shapes import (
    FeatureDefinition,
    OnlineStoreConfig,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Set to your IAM role ARN — for Isengard: "arn:aws:iam::<ACCOUNT_ID>:role/Admin"
# Leave None to auto-detect from caller identity.
SAGEMAKER_ROLE = None

PREFIX = "arro-poc"
FEATURE_GROUP_SUFFIX = time.strftime("%Y%m%d%H%M%S")

DATA_DIR = "data"
DATASETS = {
    "interaction-history": "interaction_history.csv",
    "performance-metrics": "performance_metrics.csv",
    "engagement-history": "engagement_history.csv",
    "predictive-attributes": "predictive_attributes.csv",
}

RECORD_ID = "customer_id"
EVENT_TIME = "event_time"

# Feature Store type mapping
TYPE_MAP = {
    "int64": "Integral",
    "float64": "Fractional",
    "object": "String",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_role() -> str:
    if SAGEMAKER_ROLE:
        return SAGEMAKER_ROLE
    sts = boto3.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    role = f"arn:aws:iam::{account_id}:role/Admin"
    print(f"Auto-detected role: {role}")
    return role


def prepare_df(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df[RECORD_ID] = df[RECORD_ID].astype(str)
    # event_time in ISO-8601 format (required by Feature Store)
    from datetime import datetime, timezone
    df[EVENT_TIME] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return df


def build_feature_definitions(df: pd.DataFrame) -> list:
    """Map DataFrame columns to FeatureDefinition objects."""
    definitions = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        ft = TYPE_MAP.get(dtype, "String")
        definitions.append(FeatureDefinition(feature_name=col, feature_type=ft))
    return definitions


def create_feature_group(name: str, df: pd.DataFrame, role: str) -> FeatureGroup:
    """Create an online-only feature group and wait until active."""
    feature_defs = build_feature_definitions(df)

    print(f"\n>>> Creating feature group: {name}")
    fg = FeatureGroup.create(
        feature_group_name=name,
        record_identifier_feature_name=RECORD_ID,
        event_time_feature_name=EVENT_TIME,
        feature_definitions=feature_defs,
        online_store_config=OnlineStoreConfig(enable_online_store=True),
        role_arn=role,
        description=f"POC - {name}",
    )

    # Wait for feature group to become active
    _wait_for_feature_group(name)
    return fg


def _wait_for_feature_group(name: str, timeout: int = 300):
    sm_client = boto3.client("sagemaker")
    elapsed = 0
    while True:
        resp = sm_client.describe_feature_group(FeatureGroupName=name)
        status = resp["FeatureGroupStatus"]
        if status == "Created":
            print(f"    status: {status} ✓")
            return
        elif status == "CreateFailed":
            raise RuntimeError(
                f"Feature group {name} failed: {resp.get('FailureReason', 'unknown')}"
            )
        print(f"    status: {status} … waiting")
        time.sleep(5)
        elapsed += 5
        if elapsed > timeout:
            raise TimeoutError(f"Feature group {name} stuck in {status}")


def ingest_records(fg_name: str, df: pd.DataFrame):
    """Ingest all rows into the online store using PutRecord API."""
    client = boto3.client("sagemaker-featurestore-runtime")
    print(f"    ingesting {len(df)} records into {fg_name} …")

    for _, row in df.iterrows():
        record = []
        for col in df.columns:
            record.append({
                "FeatureName": col,
                "ValueAsString": str(row[col]),
            })
        client.put_record(
            FeatureGroupName=fg_name,
            Record=record,
            TargetStores=["OnlineStore"],
        )
    print(f"    done.")


def verify_online_lookup(fg_name: str, customer_id: str):
    """Read one record back from the online store."""
    client = boto3.client("sagemaker-featurestore-runtime")
    print(f"\n>>> Verifying online lookup for {customer_id} in {fg_name}")

    try:
        resp = client.get_record(
            FeatureGroupName=fg_name,
            RecordIdentifierValueAsString=customer_id,
        )
        if "Record" in resp:
            for feat in resp["Record"]:
                print(f"    {feat['FeatureName']}: {feat['ValueAsString']}")
        else:
            print("    ⚠ No record returned")
    except Exception as e:
        print(f"    ⚠ Lookup failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    role = get_role()
    region = boto3.Session().region_name
    print(f"Region: {region}")

    feature_group_names = {}

    for short_name, csv_file in DATASETS.items():
        fg_name = f"{PREFIX}-{short_name}-{FEATURE_GROUP_SUFFIX}"
        df = prepare_df(f"{DATA_DIR}/{csv_file}")

        print(f"\nDataset '{csv_file}': {df.shape[0]} rows, {df.shape[1]} cols")
        print(f"  Columns: {list(df.columns)}")

        create_feature_group(fg_name, df, role)
        ingest_records(fg_name, df)
        feature_group_names[short_name] = fg_name

    # Verify — pull C001 from each group
    for short_name, fg_name in feature_group_names.items():
        verify_online_lookup(fg_name, "C001")

    print("\n✅ All feature groups created and data ingested (online store).")
    print(f"\nTimestamp suffix: {FEATURE_GROUP_SUFFIX}")
    print("Feature group names:")
    for short_name, fg_name in feature_group_names.items():
        print(f"  {short_name}: {fg_name}")


if __name__ == "__main__":
    main()
