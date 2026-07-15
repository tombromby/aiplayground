"""Load Kiro usage report data from S3.

Reports are CSV files stored at paths like:
  s3://{bucket}/{prefix}/{YYYY}/{MM}/{DD}/00/{CHANNEL}_{account}_user_report_{YYYYMMDD}0000.csv

Channels: KIRO_IDE, KIRO_CLI, PLUGIN
"""

import os
from datetime import date, timedelta

import boto3
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_PREFIX = os.getenv(
    "S3_PREFIX",
    "activity/AWSLogs/282248574218/KiroLogs/user_report/us-east-1",
)
AWS_ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID", "282248574218")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Map the raw Client_Type values to friendly channel names.
CHANNEL_LABELS = {
    "KIRO_IDE": "IDE",
    "KIRO_CLI": "CLI",
    "PLUGIN": "Plugin",
}


def get_s3_client():
    """Create an S3 client using default credential chain."""
    return boto3.client("s3", region_name=AWS_REGION)


def _s3_prefix_for_date(d: date) -> str:
    """Build the S3 prefix for a given date's reports."""
    return f"{S3_PREFIX}/{d.year}/{d.month:02d}/{d.day:02d}/00/"


@st.cache_data(ttl=300)
def list_report_keys(start_date: date, end_date: date) -> list[str]:
    """List all report CSV keys between start_date and end_date (inclusive)."""
    s3 = get_s3_client()
    keys: list[str] = []

    current = start_date
    while current <= end_date:
        prefix = _s3_prefix_for_date(current)
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".csv"):
                    keys.append(key)
        current += timedelta(days=1)

    return keys


@st.cache_data(ttl=300)
def load_report(key: str) -> pd.DataFrame:
    """Load a single CSV report from S3 into a DataFrame."""
    s3 = get_s3_client()
    response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    df = pd.read_csv(response["Body"])
    return df


@st.cache_data(ttl=300)
def load_usage_data(start_date: date, end_date: date) -> pd.DataFrame:
    """Load and combine all usage reports for the given date range."""
    if not BUCKET_NAME:
        st.error("S3_BUCKET_NAME is not configured. Please set it in your .env file.")
        return pd.DataFrame()

    keys = list_report_keys(start_date, end_date)

    if not keys:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for key in keys:
        try:
            df = load_report(key)
            frames.append(df)
        except Exception as e:
            st.warning(f"Failed to load {key}: {e}")

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # Parse date column
    df["Date"] = pd.to_datetime(df["Date"])

    # Create a friendly channel label
    df["Channel"] = df["Client_Type"].map(CHANNEL_LABELS).fillna(df["Client_Type"])

    # Extract user display name from email (part before @)
    if "User_Email" in df.columns:
        df["User"] = df["User_Email"].str.split("@").str[0].str.replace(".", " ").str.title()

    return df
