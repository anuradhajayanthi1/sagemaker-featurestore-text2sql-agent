"""
Central configuration for the Feature Store POC.
Update these values for your environment.
"""

import os
import boto3

# AWS Region
REGION = os.environ.get("FS_POC_REGION", "us-east-1")

# Auto-detect account ID from credentials
def get_account_id():
    try:
        return boto3.client("sts").get_caller_identity()["Account"]
    except Exception:
        return os.environ.get("FS_POC_ACCOUNT_ID", "REPLACE_WITH_YOUR_ACCOUNT_ID")

ACCOUNT_ID = get_account_id()

# SageMaker Feature Store
DATABASE = "sagemaker_featurestore"
SAGEMAKER_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/SageMakerFeatureStoreRole"

# S3
S3_BUCKET = f"sagemaker-featurestore-arro-poc-{ACCOUNT_ID}-{REGION}"
ATHENA_OUTPUT = f"s3://{S3_BUCKET}/athena-results/"
ATHENA_EVAL_OUTPUT = f"s3://{S3_BUCKET}/athena-eval-results/"

# Feature group suffix (from creation timestamp)
FG_SUFFIX = "20260412210737"

# Models
AGENT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
JUDGE_MODEL = "us.anthropic.claude-sonnet-4-20250514-v1:0"
