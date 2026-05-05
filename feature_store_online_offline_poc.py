"""
SageMaker Feature Store POC — Online + Offline (Iceberg)
========================================================
Creates 4 feature groups with both online and offline store enabled.
Offline store uses Apache Iceberg table format on S3.

This keeps the existing online-only groups intact and creates
new groups with the '-iceberg' suffix.

Prerequisites:
  pip install sagemaker boto3 pandas
  AWS credentials configured

Usage:
  cd feature-store-poc
  python feature_store_offline_poc.py
"""

import time
from datetime import datetime, timezone
import pandas as pd
import boto3
from sagemaker.core.resources import FeatureGroup
from sagemaker.core.shapes.shapes import (
    FeatureDefinition,
    OnlineStoreConfig,
    OfflineStoreConfig,
    S3StorageConfig,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SAGEMAKER_ROLE = None  # Will be set from config

PREFIX = "arro-poc"
FEATURE_GROUP_SUFFIX = time.strftime("%Y%m%d%H%M%S")

DATA_DIR = "data"
DATASETS = {
    "interaction-history-iceberg": "interaction_history.csv",
    "performance-metrics-iceberg": "performance_metrics.csv",
    "engagement-history-iceberg": "engagement_history.csv",
    "predictive-attrs-iceberg": "predictive_attributes.csv",
}

RECORD_ID = "customer_id"
EVENT_TIME = "event_time"

# S3 bucket for offline store — will be created if it doesn't exist
S3_BUCKET_PREFIX = "sagemaker-featurestore-arro-poc"

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


def ensure_s3_bucket(bucket_name: str, region: str):
    """Create the S3 bucket if it doesn't exist."""
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f"S3 bucket exists: {bucket_name}")
    except Exception:
        print(f"Creating S3 bucket: {bucket_name}")
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        print(f"S3 bucket created: {bucket_name}")


def prepare_df(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df[RECORD_ID] = df[RECORD_ID].astype(str)
    # Iceberg requires event_time as String type in ISO-8601 format
    df[EVENT_TIME] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return df


def build_feature_definitions(df: pd.DataFrame) -> list:
    definitions = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        ft = TYPE_MAP.get(dtype, "String")
        # Iceberg requirement: event_time must be String type
        if col == EVENT_TIME:
            ft = "String"
        definitions.append(FeatureDefinition(feature_name=col, feature_type=ft))
    return definitions


def create_feature_group(
    name: str, df: pd.DataFrame, role: str, s3_uri: str
) -> FeatureGroup:
    """Create a feature group with online + offline (Iceberg) store."""
    feature_defs = build_feature_definitions(df)

    print(f"\n>>> Creating feature group: {name}")
    print(f"    Online: enabled | Offline: enabled (Iceberg) | S3: {s3_uri}")

    fg = FeatureGroup.create(
        feature_group_name=name,
        record_identifier_feature_name=RECORD_ID,
        event_time_feature_name=EVENT_TIME,
        feature_definitions=feature_defs,
        online_store_config=OnlineStoreConfig(enable_online_store=True),
        offline_store_config=OfflineStoreConfig(
            s3_storage_config=S3StorageConfig(s3_uri=s3_uri),
            table_format="Iceberg",
        ),
        role_arn=role,
        description=f"POC (Iceberg) - {name}",
    )

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
    """Ingest records — goes to both online and offline stores."""
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
        )
    print(f"    done (records sent to online + offline stores).")


def verify_online_lookup(fg_name: str, customer_id: str):
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
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    print(f"Region:  {region}")
    print(f"Account: {account_id}")

    # S3 bucket for offline store
    bucket_name = f"{S3_BUCKET_PREFIX}-{account_id}-{region}"
    s3_uri = f"s3://{bucket_name}/feature-store"
    ensure_s3_bucket(bucket_name, region)

    feature_group_names = {}

    for short_name, csv_file in DATASETS.items():
        fg_name = f"{PREFIX}-{short_name}-{FEATURE_GROUP_SUFFIX}"
        df = prepare_df(f"{DATA_DIR}/{csv_file}")

        print(f"\nDataset '{csv_file}': {df.shape[0]} rows, {df.shape[1]} cols")
        create_feature_group(fg_name, df, role, s3_uri)
        ingest_records(fg_name, df)
        feature_group_names[short_name] = fg_name

    # Verify online lookups
    for short_name, fg_name in feature_group_names.items():
        verify_online_lookup(fg_name, "C001")

    print("\n" + "=" * 60)
    print("✅ All feature groups created (online + offline/Iceberg)")
    print(f"\nS3 bucket: {bucket_name}")
    print(f"S3 path:   {s3_uri}")
    print(f"Suffix:    {FEATURE_GROUP_SUFFIX}")
    print("\nFeature group names:")
    for short_name, fg_name in feature_group_names.items():
        print(f"  {short_name}: {fg_name}")

    print("\n📝 Offline data takes ~5 minutes to appear in S3.")
    print("   Once available, query via Athena in the SageMaker console:")
    print("   Feature Store → select a group → Run query")


if __name__ == "__main__":
    main()
