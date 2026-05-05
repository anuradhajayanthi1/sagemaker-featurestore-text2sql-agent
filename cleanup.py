"""
Cleanup — delete all feature groups created by the POC.

Usage:
  python cleanup.py <suffix>

Example:
  python cleanup.py 20260412143022
"""

import sys
import boto3

PREFIX = "arro-poc"
GROUPS = [
    "interaction-history",
    "performance-metrics",
    "engagement-history",
    "predictive-attributes",
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python cleanup.py <timestamp-suffix>")
        print("  The suffix is printed at the end of feature_store_online_poc.py")
        sys.exit(1)

    suffix = sys.argv[1]
    client = boto3.client("sagemaker")

    for g in GROUPS:
        name = f"{PREFIX}-{g}-{suffix}"
        print(f"Deleting {name} …", end=" ")
        try:
            client.delete_feature_group(FeatureGroupName=name)
            print("done")
        except client.exceptions.ResourceNotFound:
            print("not found, skipping")


if __name__ == "__main__":
    main()
