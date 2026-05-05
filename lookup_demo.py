"""
Quick demo — look up a customer's features from the online store in real time.

Usage:
  python lookup_demo.py <feature-group-name> <customer-id>

Example:
  python lookup_demo.py arro-poc-interaction-history-20260412 C003
"""

import sys
import boto3

def main():
    if len(sys.argv) < 3:
        print("Usage: python lookup_demo.py <feature-group-name> <customer-id>")
        sys.exit(1)

    fg_name = sys.argv[1]
    customer_id = sys.argv[2]

    client = boto3.client("sagemaker-featurestore-runtime")

    resp = client.get_record(
        FeatureGroupName=fg_name,
        RecordIdentifierValueAsString=customer_id,
    )

    if "Record" not in resp:
        print(f"No record found for {customer_id} in {fg_name}")
        return

    print(f"\nFeatures for {customer_id} in {fg_name}:")
    for feat in resp["Record"]:
        print(f"  {feat['FeatureName']}: {feat['ValueAsString']}")


if __name__ == "__main__":
    main()
