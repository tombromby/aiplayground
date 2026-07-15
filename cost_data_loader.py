"""Load and prepare AWS CUR 2.0 Bedrock usage data from S3 or a local parquet file.

The CUR 2.0 Data Export uses Hive-style partitioning in S3:
  s3://{bucket}/{prefix}/data/BILLING_PERIOD={YYYY-MM}/{export_name}-00001.snappy.parquet

This module discovers available billing periods, loads the parquet for a
selected period, and filters to Amazon Bedrock usage with enriched columns
for caller identity and model classification.
"""

import io
import os
import re
from pathlib import Path

import boto3
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# S3 location for CUR 2.0 export
CUR_BUCKET = os.getenv("CUR_S3_BUCKET", "cost-optimisation25")
CUR_PREFIX = os.getenv("CUR_S3_PREFIX", "2025/cost-optimsation2025/data")
CUR_EXPORT_NAME = os.getenv("CUR_EXPORT_NAME", "cost-optimsation2025")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Local fallback
LOCAL_PARQUET_PATH = Path("report_examples/cost-optimsation2025-00001.snappy.parquet")


def _get_s3_client():
    """Create an S3 client using default credential chain."""
    return boto3.client("s3", region_name=AWS_REGION)


@st.cache_data(ttl=600)
def list_available_billing_periods() -> list[str]:
    """Discover available BILLING_PERIOD partitions from S3.

    Returns a sorted list of billing period strings (e.g. ['2026-06', '2026-07']).
    Falls back to extracting period from local file metadata if S3 is unavailable.
    """
    try:
        s3 = _get_s3_client()
        prefix = f"{CUR_PREFIX}/BILLING_PERIOD="
        paginator = s3.get_paginator("list_objects_v2")
        periods: set[str] = set()

        for page in paginator.paginate(Bucket=CUR_BUCKET, Prefix=prefix, Delimiter="/"):
            for common_prefix in page.get("CommonPrefixes", []):
                # Extract period from path like: .../BILLING_PERIOD=2026-07/
                folder = common_prefix["Prefix"]
                match = re.search(r"BILLING_PERIOD=(\d{4}-\d{2})/?$", folder)
                if match:
                    periods.add(match.group(1))

        if periods:
            return sorted(periods, reverse=True)
    except Exception:
        pass

    # Fallback: if we have a local file, offer a single period based on its content
    if LOCAL_PARQUET_PATH.exists():
        try:
            df = pd.read_parquet(LOCAL_PARQUET_PATH, columns=["bill_billing_period_start_date"])
            period = pd.to_datetime(df["bill_billing_period_start_date"].iloc[0])
            return [period.strftime("%Y-%m")]
        except Exception:
            pass

    return []


@st.cache_data(ttl=300)
def _load_parquet_from_s3(billing_period: str) -> pd.DataFrame:
    """Load CUR 2.0 parquet from S3 for a given billing period."""
    s3 = _get_s3_client()
    prefix = f"{CUR_PREFIX}/BILLING_PERIOD={billing_period}/"

    # List parquet files in this partition (there may be multiple chunks)
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=CUR_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                keys.append(obj["Key"])

    if not keys:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for key in keys:
        response = s3.get_object(Bucket=CUR_BUCKET, Key=key)
        data = response["Body"].read()
        df = pd.read_parquet(io.BytesIO(data))
        frames.append(df)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_parquet_local() -> pd.DataFrame:
    """Load CUR 2.0 parquet from local file."""
    if not LOCAL_PARQUET_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(LOCAL_PARQUET_PATH)


@st.cache_data(ttl=300)
def load_cur_data(billing_period: str) -> pd.DataFrame:
    """Load raw CUR 2.0 data for a billing period.

    Attempts S3 first, falls back to local parquet file.
    """
    try:
        df = _load_parquet_from_s3(billing_period)
        if not df.empty:
            return df
    except Exception as e:
        st.toast(f"S3 load failed, using local file: {e}", icon="⚠️")

    # Fallback to local
    return _load_parquet_local()


# --- IAM Principal Parsing ---


def _parse_iam_principal(arn: str) -> str:
    """Extract a human-friendly caller name from an IAM principal ARN.

    Patterns handled:
      - SSO user: ...assumed-role/AWSReservedSSO_.../user@domain → user email
      - Service role with session: ...assumed-role/RoleName/SessionName → RoleName
      - Simple role: ...role/RoleName → RoleName
      - Anything else: return last meaningful segment
    """
    if not isinstance(arn, str) or not arn:
        return "Unknown"

    # Pattern: assumed-role/<role-name>/<session-name>
    match = re.search(r"assumed-role/([^/]+)/(.+)$", arn)
    if match:
        role_name = match.group(1)
        session_name = match.group(2)

        # SSO users have email as session name
        if "@" in session_name:
            return session_name

        # CI/CD pipelines often use recognisable session names
        if session_name in ("GitHubActions", "github-actions"):
            return f"{role_name} (GitHub Actions)"

        # BedrockAgentCore sessions — group by role, not individual session IDs
        if session_name.startswith("BedrockAgentCore-"):
            return role_name

        # Knowledge Base sessions
        if session_name.startswith("BKB-"):
            return role_name

        # Default: use role name (more stable than random session IDs)
        return role_name

    # Pattern: role/<role-name>
    match = re.search(r"role/([^/]+)$", arn)
    if match:
        return match.group(1)

    return arn.split("/")[-1] if "/" in arn else arn


# --- Model / Service Classification ---


def _extract_model_info(row: pd.Series) -> str:
    """Derive a model/service label from usage type and description fields."""
    description = str(row.get("line_item_line_item_description", ""))
    usage_type = str(row.get("line_item_usage_type", ""))

    if "NovaPro" in usage_type or "NovaPro" in description:
        return "Amazon Nova Pro"
    if "TitanEmbeddingV2" in usage_type or "TitanEmbeddingsV2" in description:
        return "Amazon Titan Embeddings V2"
    if "TitanEmbeddingsG1" in usage_type or "TitanEmbeddingsG1" in description:
        return "Amazon Titan Embeddings G1"

    # Marketplace models — identify by token type in description
    if "AWS Marketplace software usage" in description:
        parts = description.split("|")
        if len(parts) >= 3:
            return f"Marketplace Model ({parts[1].strip()})"

    # AgentCore services
    if "Memory" in usage_type or "MemoryStored" in description:
        return "Bedrock AgentCore (Memory)"
    if "Runtime" in usage_type:
        return "Bedrock AgentCore (Runtime)"
    if "Gateway" in usage_type:
        return "Bedrock AgentCore (Gateway)"
    if "Guardrail" in usage_type or "Guardrail" in description:
        return "Bedrock Guardrails"
    if "ToolIndex" in usage_type:
        return "Bedrock AgentCore (Tool Index)"

    # Token-based usage without specific model identification
    if "InputToken" in usage_type or "OutputToken" in usage_type:
        region = usage_type.split("-")[0] if "-" in usage_type else "Unknown"
        return f"Marketplace Model ({region})"

    return "Other"


def _classify_token_type(usage_type: str) -> str:
    """Classify a usage type into a token category."""
    usage_type = str(usage_type)
    if "CacheRead" in usage_type or "cache_read" in usage_type:
        return "Cache Read Tokens"
    if "CacheWrite" in usage_type or "cache_write" in usage_type:
        return "Cache Write Tokens"
    if "Output" in usage_type or "output" in usage_type or "Response" in usage_type:
        return "Output Tokens"
    if "Input" in usage_type or "input" in usage_type:
        return "Input Tokens"
    return "Other"


# --- Public API ---


@st.cache_data(ttl=300)
def load_bedrock_data(billing_period: str) -> pd.DataFrame:
    """Load CUR 2.0 data for a billing period and return Bedrock usage with enriched columns."""
    df = load_cur_data(billing_period)

    if df.empty:
        return pd.DataFrame()

    # Filter to Amazon Bedrock product family
    bedrock = df[df["product_product_family"] == "Amazon Bedrock"].copy()

    if bedrock.empty:
        return pd.DataFrame()

    # Parse IAM principal into a friendly caller name
    bedrock["Caller"] = bedrock["line_item_iam_principal"].apply(_parse_iam_principal)

    # Derive model/service label
    bedrock["Model"] = bedrock.apply(_extract_model_info, axis=1)

    # Classify token type
    bedrock["Token Type"] = bedrock["line_item_usage_type"].apply(_classify_token_type)

    # Ensure date column is datetime
    bedrock["Date"] = pd.to_datetime(bedrock["line_item_usage_start_date"])

    # Rename key cost columns for readability
    bedrock = bedrock.rename(columns={
        "line_item_unblended_cost": "Cost",
        "line_item_usage_amount": "Usage Amount",
        "line_item_operation": "Operation",
        "product_region_code": "Region",
        "line_item_usage_type": "Usage Type",
        "line_item_line_item_description": "Description",
        "line_item_resource_id": "Resource ID",
    })

    return bedrock
