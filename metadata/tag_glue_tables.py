"""
Tag Glue Tables with Metadata
==============================
Adds table descriptions, column comments, join keys, and friendly names
to Glue Data Catalog tables. This metadata is used by the assembler
to build context for text-to-SQL.

Custom Parameters stored per table:
  - friendly_name: human-readable table name
  - join_keys: comma-separated list of columns that can be used for joins
  - domain: business domain grouping

Column Comments:
  - Stored directly on each column in the Glue schema

Usage:
  python metadata/tag_glue_tables.py
"""

import boto3
import copy

glue = boto3.client("glue")
DB = "sagemaker_featurestore"

# ---------------------------------------------------------------------------
# Define metadata for each table
# ---------------------------------------------------------------------------
TABLE_METADATA = {
    "arro_poc_interaction_history_iceberg_20260412210737_1776053259": {
        "friendly_name": "interaction_history",
        "description": "Customer interaction history with the behavioral platform including logins, sessions, lessons, nudges, and chat usage",
        "domain": "behavioral",
        "join_keys": "customer_id",
        "columns": {
            "customer_id": "Unique customer identifier (primary key across all feature groups)",
            "total_logins_30d": "Total number of logins in the last 30 days",
            "avg_session_duration_min": "Average session duration in minutes over last 30 days",
            "lessons_completed": "Number of financial literacy lessons completed",
            "nudges_received": "Number of behavioral nudges sent to the customer",
            "nudges_acted_on": "Number of nudges the customer acted on",
            "chat_interactions": "Number of AI chat interactions in last 30 days",
            "last_login_days_ago": "Days since last login (0 = today)",
            "feature_usage_breadth": "Fraction of app features used (0.0 to 1.0)",
            "mobile_usage_pct": "Percentage of sessions from mobile device (0.0 to 1.0)",
            "peak_usage_hour": "Hour of day with most activity (0-23)",
        },
    },
    "arro_poc_performance_metrics_iceberg_20260412210737_1776053288": {
        "friendly_name": "performance_metrics",
        "description": "Customer financial performance metrics including spending, credit utilization, balances, and retention target",
        "domain": "financial",
        "join_keys": "customer_id",
        "columns": {
            "customer_id": "Unique customer identifier (primary key across all feature groups)",
            "avg_transaction_amount": "Average transaction amount in USD",
            "monthly_spend": "Total monthly spend in USD",
            "payment_on_time_rate": "Fraction of payments made on time (0.0 to 1.0)",
            "credit_utilization": "Credit utilization ratio (0.0 to 1.0, lower is better)",
            "account_age_months": "Number of months since account was opened",
            "num_products": "Number of financial products held by customer",
            "avg_balance": "Average account balance in USD",
            "min_balance": "Minimum account balance in USD over period",
            "max_balance": "Maximum account balance in USD over period",
            "target": "Binary retention label: 1 = retained/active, 0 = churned/at-risk (ground truth for ML)",
        },
    },
    "arro_poc_engagement_history_iceberg_20260412210737_1776053312": {
        "friendly_name": "engagement_history",
        "description": "Customer engagement metrics across email, push notifications, in-app messages, campaigns, and rewards",
        "domain": "engagement",
        "join_keys": "customer_id",
        "columns": {
            "customer_id": "Unique customer identifier (primary key across all feature groups)",
            "email_open_rate": "Fraction of marketing emails opened (0.0 to 1.0)",
            "push_notification_ctr": "Push notification click-through rate (0.0 to 1.0)",
            "in_app_msg_response_rate": "In-app message response rate (0.0 to 1.0)",
            "campaign_participation_count": "Number of marketing campaigns participated in",
            "reward_redemption_rate": "Fraction of available rewards redeemed (0.0 to 1.0)",
            "feedback_submissions": "Number of feedback forms submitted",
            "nps_score": "Net Promoter Score (0-10, higher is better)",
            "days_since_last_engagement": "Days since last engagement activity",
            "engagement_trend": "Recent engagement direction: increasing, stable, or declining",
            "retention_flag": "Binary retention indicator: 1 = retained, 0 = churned",
        },
    },
    "arro_poc_predictive_attrs_iceberg_20260412210737_1776053336": {
        "friendly_name": "predictive_attributes",
        "description": "ML-derived predictive scores and customer segmentation attributes",
        "domain": "predictive",
        "join_keys": "customer_id",
        "columns": {
            "customer_id": "Unique customer identifier (primary key across all feature groups)",
            "churn_risk_score": "ML-predicted probability of churning (0.0 to 1.0, higher = more likely to churn)",
            "lifetime_value_estimate": "Estimated customer lifetime value in USD",
            "engagement_score": "Composite engagement score (0.0 to 1.0)",
            "satisfaction_index": "Customer satisfaction score (1.0 to 5.0)",
            "propensity_to_upgrade": "Likelihood of upgrading to premium product (0.0 to 1.0)",
            "digital_adoption_score": "Digital feature adoption level (0.0 to 1.0)",
            "support_ticket_frequency": "Average support tickets per month",
            "referral_likelihood": "Likelihood of referring others (0.0 to 1.0)",
            "segment_code": "Customer segment: premium, standard, or basic",
            "risk_tier": "Risk classification: low, medium, high, or critical",
        },
    },
}


# ---------------------------------------------------------------------------
# Apply metadata to Glue tables
# ---------------------------------------------------------------------------
def tag_table(table_name: str, meta: dict):
    """Update a Glue table with descriptions, column comments, and custom parameters."""
    resp = glue.get_table(DatabaseName=DB, Name=table_name)
    table_def = resp["Table"]

    # Build updated table input (keep only allowed fields)
    allowed_keys = {
        "Name", "Description", "Owner", "LastAccessTime", "LastAnalyzedTime",
        "Retention", "StorageDescriptor", "PartitionKeys", "ViewOriginalText",
        "ViewExpandedText", "TableType", "Parameters", "TargetTable", "ViewDefinition",
    }
    table_input = {k: v for k, v in table_def.items() if k in allowed_keys}

    # Set table description
    table_input["Description"] = meta["description"]

    # Add custom parameters (preserve existing ones like metadata_location)
    params = table_input.get("Parameters", {})
    params["friendly_name"] = meta["friendly_name"]
    params["join_keys"] = meta["join_keys"]
    params["domain"] = meta["domain"]
    table_input["Parameters"] = params

    # Add column comments
    columns = table_input["StorageDescriptor"]["Columns"]
    for col in columns:
        col_name = col["Name"]
        if col_name in meta["columns"]:
            col["Comment"] = meta["columns"][col_name]
        elif col_name == "event_time":
            col["Comment"] = "Event timestamp in ISO-8601 format (used by Feature Store for versioning)"
        elif col_name == "write_time":
            col["Comment"] = "Timestamp when record was written to offline store (auto-generated)"
        elif col_name == "api_invocation_time":
            col["Comment"] = "Timestamp of the PutRecord API call (auto-generated)"
        elif col_name == "is_deleted":
            col["Comment"] = "Soft-delete flag set by DeleteRecord API (auto-generated)"

    glue.update_table(DatabaseName=DB, TableInput=table_input)
    print(f"✓ Tagged: {table_name} → {meta['friendly_name']}")


def main():
    for table_name, meta in TABLE_METADATA.items():
        tag_table(table_name, meta)

    print(f"\nDone. Tagged {len(TABLE_METADATA)} tables in {DB}.")
    print("View in Glue console: Tables → click a table → Schema tab for column comments")


if __name__ == "__main__":
    main()
