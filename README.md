# Kiro User Activity Report Dashboard

Reads Kiro daily usage reports from S3 and displays a dashboard for tracking credit usage by users across IDE, CLI, and Plugin channels.

## Prerequisites

- Python 3.11+
- AWS credentials configured (via `~/.aws/credentials`, SSO, or environment variables) with read access to the `cevo-qdev-pro-activity-us-east-1` bucket

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Running the Dashboard

```bash
streamlit run app.py
```

Opens at http://localhost:8501

## S3 Report Structure

Reports are CSV files stored at:
```
s3://cevo-qdev-pro-activity-us-east-1/activity/AWSLogs/{account}/KiroLogs/user_report/us-east-1/{YYYY}/{MM}/{DD}/00/{CHANNEL}_{account}_user_report_{YYYYMMDD}0000.csv
```

Channels: `KIRO_IDE`, `KIRO_CLI`, `PLUGIN`

## Project Structure

```
├── app.py              # Streamlit dashboard
├── data_loader.py      # S3 data fetching and caching
├── report_examples/    # Sample CSVs for reference
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── README.md
```
