"""Kiro User Activity Report Dashboard."""

from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from cost_data_loader import list_available_billing_periods, load_bedrock_data
from data_loader import load_usage_data

st.set_page_config(
    page_title="Kiro Usage Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Kiro Usage Dashboard")

# --- Tabs ---
tab_kiro, tab_bedrock = st.tabs(["Kiro Activity", "Bedrock Usage"])

# =============================================================================
# TAB 1: Kiro Activity (original dashboard)
# =============================================================================
with tab_kiro:
    st.markdown("Credit usage across IDE, CLI, and Plugin channels.")

    # --- Sidebar: filters ---
    st.sidebar.header("Kiro Activity Filters")

    default_end = date.today()
    default_start = default_end - timedelta(days=30)

    start_date = st.sidebar.date_input("Start date", value=default_start)
    end_date = st.sidebar.date_input("End date", value=default_end)

    if start_date > end_date:
        st.sidebar.error("Start date must be before end date.")
        st.stop()

    # --- Load data ---
    with st.spinner("Loading usage data from S3..."):
        df = load_usage_data(start_date, end_date)

    if df.empty:
        st.warning("No usage data found for the selected date range.")
        st.info(
            "Make sure your `.env` file has the correct S3_BUCKET_NAME and that "
            "reports exist for the selected dates."
        )
    else:
        # --- Channel filter ---
        channels = sorted(df["Channel"].unique())
        selected_channels = st.sidebar.multiselect(
            "Channels",
            options=channels,
            default=channels,
        )
        df = df[df["Channel"].isin(selected_channels)]

        # --- User filter ---
        users = sorted(df["User"].unique())
        selected_users = st.sidebar.multiselect(
            "Users",
            options=users,
            default=users,
        )
        df = df[df["User"].isin(selected_users)]

        # --- Summary metrics ---
        col1, col2, col3, col4 = st.columns(4)

        total_credits = df["Credits_Used"].sum()
        total_messages = df["Total_Messages"].sum()
        unique_users = df["User"].nunique()
        days_in_range = (end_date - start_date).days or 1

        with col1:
            st.metric("Total Credits Used", f"{total_credits:,.1f}")
        with col2:
            st.metric("Active Users", unique_users)
        with col3:
            st.metric("Total Messages", f"{total_messages:,.0f}")
        with col4:
            st.metric("Avg Credits/Day", f"{total_credits / days_in_range:,.1f}")

        st.divider()

        # --- Charts row 1 ---
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.subheader("Credits by Channel")
            channel_usage = df.groupby("Channel")["Credits_Used"].sum().reset_index()
            fig = px.pie(
                channel_usage,
                values="Credits_Used",
                names="Channel",
                color="Channel",
                color_discrete_map={"IDE": "#636EFA", "CLI": "#EF553B", "Plugin": "#00CC96"},
            )
            st.plotly_chart(fig, use_container_width=True)

        with chart_col2:
            st.subheader("Top Users by Credits")
            user_usage = (
                df.groupby("User")["Credits_Used"]
                .sum()
                .sort_values(ascending=False)
                .head(15)
                .reset_index()
            )
            fig = px.bar(
                user_usage,
                x="User",
                y="Credits_Used",
                color_discrete_sequence=["#636EFA"],
                labels={"Credits_Used": "Credits"},
            )
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)

        # --- Daily usage trend ---
        st.subheader("Daily Credit Usage")
        daily_usage = df.groupby(["Date", "Channel"])["Credits_Used"].sum().reset_index()
        fig = px.line(
            daily_usage,
            x="Date",
            y="Credits_Used",
            color="Channel",
            markers=True,
            color_discrete_map={"IDE": "#636EFA", "CLI": "#EF553B", "Plugin": "#00CC96"},
            labels={"Credits_Used": "Credits"},
        )
        fig.update_layout(xaxis_title="Date", yaxis_title="Credits")
        st.plotly_chart(fig, use_container_width=True)

        # --- Per-user breakdown ---
        st.subheader("Credits by User and Channel")
        user_channel = (
            df.groupby(["User", "Channel"])["Credits_Used"]
            .sum()
            .reset_index()
            .sort_values("Credits_Used", ascending=False)
        )
        fig = px.bar(
            user_channel,
            x="User",
            y="Credits_Used",
            color="Channel",
            barmode="stack",
            color_discrete_map={"IDE": "#636EFA", "CLI": "#EF553B", "Plugin": "#00CC96"},
            labels={"Credits_Used": "Credits"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        # --- All users ranked by credits ---
        st.subheader("All Users by Credits Used")
        all_users_credits = (
            df.groupby("User")["Credits_Used"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        all_users_credits.index = range(1, len(all_users_credits) + 1)
        all_users_credits.columns = ["User", "Credits Used"]
        all_users_credits["Credits Used"] = all_users_credits["Credits Used"].map("{:,.2f}".format)
        st.dataframe(all_users_credits, use_container_width=True)

        # --- Messages breakdown ---
        st.subheader("Messages by User")
        user_messages = (
            df.groupby(["User", "Channel"])["Total_Messages"]
            .sum()
            .reset_index()
            .sort_values("Total_Messages", ascending=False)
        )
        fig = px.bar(
            user_messages,
            x="User",
            y="Total_Messages",
            color="Channel",
            barmode="stack",
            color_discrete_map={"IDE": "#636EFA", "CLI": "#EF553B", "Plugin": "#00CC96"},
            labels={"Total_Messages": "Messages"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        # --- Raw data table ---
        with st.expander("📋 Raw Data"):
            display_cols = [
                "Date", "User", "User_Email", "Channel", "Credits_Used",
                "Total_Messages", "Chat_Conversations", "Subscription_Tier",
                "Overage_Credits_Used", "New_User",
            ]
            available_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[available_cols].sort_values(["Date", "User"]),
                use_container_width=True,
            )

# =============================================================================
# TAB 2: Bedrock Usage
# =============================================================================
with tab_bedrock:
    st.markdown("AWS Bedrock spend breakdown by caller identity (IAM principal).")

    # --- Billing period selector ---
    available_periods = list_available_billing_periods()

    if not available_periods:
        st.warning("No billing periods found. Check your S3 credentials and CUR export configuration.")
        st.stop()

    st.sidebar.markdown("---")
    st.sidebar.header("Bedrock Filters")

    selected_period = st.sidebar.selectbox(
        "Billing Period",
        options=available_periods,
        index=0,
        key="bedrock_period",
        help="Select a monthly billing period (data loaded from S3 with local fallback)",
    )

    # --- Load data ---
    with st.spinner(f"Loading Bedrock data for {selected_period}..."):
        bedrock_df = load_bedrock_data(selected_period)

    if bedrock_df.empty:
        st.warning(f"No Bedrock usage data found for billing period {selected_period}.")
        st.stop()

    callers = sorted(bedrock_df["Caller"].unique())
    selected_callers = st.sidebar.multiselect(
        "Callers (IAM Principal)",
        options=callers,
        default=callers,
        key="bedrock_callers",
    )

    models = sorted(bedrock_df["Model"].unique())
    selected_models = st.sidebar.multiselect(
        "Model / Service",
        options=models,
        default=models,
        key="bedrock_models",
    )

    # Apply filters
    bdf = bedrock_df[
        bedrock_df["Caller"].isin(selected_callers)
        & bedrock_df["Model"].isin(selected_models)
    ]

    # --- Summary metrics ---
    col1, col2, col3, col4 = st.columns(4)

    total_cost = bdf["Cost"].sum()
    unique_callers = bdf["Caller"].nunique()
    total_requests = len(bdf)
    date_range = (bdf["Date"].max() - bdf["Date"].min()).days or 1

    with col1:
        st.metric("Total Bedrock Cost", f"${total_cost:,.2f}")
    with col2:
        st.metric("Unique Callers", unique_callers)
    with col3:
        st.metric("Line Items", f"{total_requests:,}")
    with col4:
        st.metric("Avg Cost/Day", f"${total_cost / date_range:,.2f}")

    st.divider()

    # --- Charts row 1: Cost by caller + Cost by model ---
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("Cost by Caller")
        caller_cost = (
            bdf.groupby("Caller")["Cost"]
            .sum()
            .sort_values(ascending=False)
            .head(15)
            .reset_index()
        )
        fig = px.bar(
            caller_cost,
            x="Caller",
            y="Cost",
            color_discrete_sequence=["#636EFA"],
            labels={"Cost": "Cost (USD)"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    with chart_col2:
        st.subheader("Cost by Model / Service")
        model_cost = bdf.groupby("Model")["Cost"].sum().reset_index()
        fig = px.pie(
            model_cost,
            values="Cost",
            names="Model",
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- Daily cost trend ---
    st.subheader("Daily Bedrock Cost")
    daily_cost = bdf.groupby(["Date", "Caller"])["Cost"].sum().reset_index()
    # Only show top callers in the line chart to keep it readable
    top_callers = (
        bdf.groupby("Caller")["Cost"].sum().sort_values(ascending=False).head(5).index
    )
    daily_top = daily_cost[daily_cost["Caller"].isin(top_callers)]
    fig = px.line(
        daily_top,
        x="Date",
        y="Cost",
        color="Caller",
        markers=True,
        labels={"Cost": "Cost (USD)"},
    )
    fig.update_layout(xaxis_title="Date", yaxis_title="Cost (USD)")
    st.plotly_chart(fig, use_container_width=True)

    # --- Cost by operation ---
    st.subheader("Cost by Operation")
    op_cost = (
        bdf.groupby(["Operation", "Caller"])["Cost"]
        .sum()
        .reset_index()
        .sort_values("Cost", ascending=False)
    )
    fig = px.bar(
        op_cost,
        x="Operation",
        y="Cost",
        color="Caller",
        barmode="stack",
        labels={"Cost": "Cost (USD)"},
    )
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

    # --- Token usage breakdown ---
    st.subheader("Token Usage by Caller")
    token_df = bdf[bdf["Token Type"] != "Other"]
    if not token_df.empty:
        token_usage = (
            token_df.groupby(["Caller", "Token Type"])["Usage Amount"]
            .sum()
            .reset_index()
            .sort_values("Usage Amount", ascending=False)
        )
        # Show top callers by token volume
        top_token_callers = (
            token_usage.groupby("Caller")["Usage Amount"]
            .sum()
            .sort_values(ascending=False)
            .head(10)
            .index
        )
        token_usage_top = token_usage[token_usage["Caller"].isin(top_token_callers)]
        fig = px.bar(
            token_usage_top,
            x="Caller",
            y="Usage Amount",
            color="Token Type",
            barmode="stack",
            labels={"Usage Amount": "Tokens"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No token-level usage data available with current filters.")

    # --- Raw data table ---
    with st.expander("📋 Raw Bedrock Data"):
        display_cols = [
            "Date", "Caller", "Model", "Operation", "Cost",
            "Usage Amount", "Token Type", "Region", "Resource ID", "Description",
        ]
        available_cols = [c for c in display_cols if c in bdf.columns]
        st.dataframe(
            bdf[available_cols].sort_values(["Date", "Caller"]),
            use_container_width=True,
        )
