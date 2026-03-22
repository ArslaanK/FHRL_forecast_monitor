# -*- coding: utf-8 -*-
"""
Created on Sun Feb 15 23:59:18 2026

@author: akhal
"""

import streamlit as st
import yaml
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
import pandas as pd
import requests
import re
from zoneinfo import ZoneInfo
# -------------------------
# Last Refresh from GitHub commit
# -------------------------
github_api_url = "https://api.github.com/repos/ArslaanK/FHRL_forecast_monitor/commits"
file_path = "assets/iflood_status.yaml"

# Get the latest commit for this file
resp = requests.get(f"{github_api_url}?path={file_path}&page=1&per_page=1")
if resp.status_code == 200 and len(resp.json()) > 0:
    commit_data = resp.json()[0]
    # Parse UTC time from GitHub
    last_refresh_utc = datetime.fromisoformat(commit_data["commit"]["committer"]["date"].replace("Z", "+00:00"))
else:
    # fallback to current UTC time
    last_refresh_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))

# Convert to Eastern Time (EST/EDT automatically)
eastern = ZoneInfo("America/New_York")
last_refresh_est = last_refresh_utc.astimezone(eastern)


st.set_page_config(layout="wide")

st.markdown("""
<style>
.loader {
  border: 4px solid #f3f3f3;
  border-top: 4px solid #1f77b4;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  animation: spin 1s linear infinite;
  display: inline-block;
  margin-left: 10px;
}
@keyframes spin {
  100% { transform: rotate(360deg); }
}
</style>
""", unsafe_allow_html=True)

# ?? auto refresh, 10 sec
#st_autorefresh(interval=10000, key="refresh")
# ?? auto refresh every 5 minutes
st_autorefresh(interval=300000, key="refresh")

# -------------------------
# Helpers
# -------------------------

PIPELINE_ORDER = [
    ("pre", "metforecast_processor"),
    ("pre", "prep_simulation"),

    ("nowcast", "run_nowcast"),

    ("forecast", "run_forecast"),
    ("forecast", "copy_forecast_results"),
  
    ("post", "gen_nws_forecast"),
    ("post", "gen_spatial_maps"),  
    ("post", "create_timeseries"),
    ("post", "fetch_competing_model"),
    ("post", "gen_flood_alerts"),
    ("post", "push_to_s3"),
    ("post", "pipeline_completion"),

]

def get_latest_progress(data, phase_name):
    """
    Returns the last logged progress % for a given phase (nowcast or forecast)
    """
    phase = data.get(phase_name, {})
    for task_name, task in phase.items():
        if task.get("status") == "running" and isinstance(task.get("log"), list):
            # Find last msg like 'xx% completed'
            for entry in reversed(task["log"]):
                msg = entry.get("msg", "")
                if "completed" in msg and "%" in msg:
                    try:
                        progress = float(msg.split("%")[0])
                        return task_name, progress
                    except:
                        return task_name, 0
    return None, 0
  
def load_yaml(path_or_url):
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        # fetch from URL
        resp = requests.get(path_or_url)
        resp.raise_for_status()  # fail if request failed
        data = yaml.safe_load(resp.text)
    else:
        # local file
        with open(path_or_url, "r") as f:
            data = yaml.safe_load(f)
    return data

def icon(status):
    return {
        "waiting": "⚪",
        "running": "🔵",
        "completed": "🟢",
        "failed": "🔴",
    }.get(status, "⚪")

def status_badge(status):

    colors = {
        "waiting": "#9e9e9e",
        "running": "#1f77b4",
        "completed": "#2ca02c",
        "failed": "#d62728",
    }

    return f"""
    <span style="
        display:inline-flex;
        align-items:center;
        justify-content:center;
        background-color:{colors.get(status, "#9e9e9e")};
        color:white;
        padding:2px 8px;
        border-radius:6px;
        font-size:12px;
        font-weight:600;
        white-space:nowrap;
    ">
        {status.upper()}
    </span>
    """


# def duration(start, end):
#     if not start:
#         return ""
#     start = datetime.fromisoformat(start)
#     end = datetime.fromisoformat(end) if end else datetime.now()
#     return str(end - start).split(".")[0]

def pipeline_progress(data):
    total = 0
    done = 0

    for phase_name in ["pre", "nowcast", "forecast", "post"]:
        phase = data.get(phase_name, {})

        for task in phase.values():
            total += 1
            if task.get("status") == "completed":
                done += 1

    return done / total if total else 0


def duration(start_str, end_str=None):
    """
    Compute duration between start and end. 
    If end is None, use current time.
    Assumes start_str and end_str are strings like 'YYYY-MM-DD HH:MM:SS'
    """
    time_format = "%Y-%m-%d %H:%M:%S"

    start_time = datetime.strptime(start_str, time_format)

    if end_str:
        end_time = datetime.strptime(end_str, time_format)
    else:
        end_time = datetime.now()

    delta = end_time - start_time

    # format nicely
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days} day{'s' if days != 1 else ''}, {hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# -------------------------
# Load data
# -------------------------
iflood = load_yaml("https://raw.githubusercontent.com/ArslaanK/FHRL_forecast_monitor/refs/heads/main/assets/iflood_status.yaml")
hecras = load_yaml("https://raw.githubusercontent.com/ArslaanK/FHRL_forecast_monitor/refs/heads/main/assets/hecras_status.yaml")


# -------------------------
# Forecast Cycle
# -------------------------
# Read current cycle from YAML
cycle_str = iflood.get("forecast", {}).get("current_cycle", None)
if cycle_str:
    cycle_dt = datetime.fromisoformat(cycle_str)
else:
    cycle_dt = datetime.utcnow()

# Round to nearest 00Z or 12Z
hour = cycle_dt.hour

if hour < 8:
    # 00Z same day
    cycle_dt = cycle_dt.replace(hour=0, minute=0, second=0, microsecond=0)
elif hour < 23:
    # 12Z same day
    cycle_dt = cycle_dt.replace(hour=12, minute=0, second=0, microsecond=0)

# Next cycle is 12 hours later
next_cycle_dt = cycle_dt + timedelta(hours=12)

# -------------------------
# Display Header
# -------------------------
st.title("🌊 FHRL Operational Forecast Dashboard")
colA, colB = st.columns([3,1])
colB.markdown(f"**Last Refresh:** {last_refresh_est.strftime('%Y-%m-%d %H:%M:%S')}")

st.divider()

# -------------------------
# System Overview
# -------------------------
system = iflood.get("system", {})
cpu = float(system.get("cpu", 0))
ram = float(system.get("ram", 0))
usage = max(cpu, ram)

status = "Nominal"
if usage > 85:
    status = "Critical"
elif usage > 70:
    status = "High"

col1, col2, col3 = st.columns(3)

# Column 1: System
with col1:
    st.subheader("🖥 System Overview")
    st.markdown("**Specs:** 54 cores × 512GB RAM")
    st.metric("System Health", "RUNNING", delta=status)
    st.metric("System Usage", f"{usage:.1f}%", delta=status)

# Column 2: Pipeline Progress
with col2:
    st.subheader("📊 Pipeline Progress")
    st.markdown("**iFLOOD Progress**")
    st.progress(pipeline_progress(iflood))
    st.markdown("**HEC-RAS Progress**")
    st.progress(pipeline_progress(hecras))

# Column 3: Forecast Cycle
with col3:
    st.subheader("⏱ Forecast Cycle")
    st.metric("Current Cycle", f"{cycle_dt.strftime('%Y-%m-%d %HZ')}")
    st.metric("Next Cycle ETA", f"{next_cycle_dt.strftime('%Y-%m-%d %HZ')}")

st.divider()


def get_status(meta):
    return meta.get("status", "waiting")

def get_current_task(data):
    for phase_name in ["pre", "nowcast", "forecast", "post"]:
        tasks = data.get(phase_name, {})

        for name, meta in tasks.items():
            if isinstance(meta, dict) and meta.get("status") == "running":
                return phase_name, name, meta

    return None, None, None



phase, task, meta = get_current_task(iflood)

def render_pipeline(title, data):
    st.subheader(title)

    for phase, task_name in PIPELINE_ORDER:
        meta = data.get(phase, {}).get(task_name, {})

        status = meta.get("status", "waiting")
        start = meta.get("start")
        end = meta.get("end")
        log = meta.get("log")

        cols = st.columns([0.1, 0.5, 0.3, 0.3])

        # Status badge
        cols[0].markdown(status_badge(status), unsafe_allow_html=True)

        # Task name
        task_label = f"**{phase.upper()} / {task_name}**"
      
        progress_val = 0
        progress_text = ""
        
        if status == "running" and isinstance(log, list):
            for item in reversed(log):
                msg = item.get("msg") if isinstance(item, dict) else str(item)
                match = re.search(r"([\d\.]+)%", msg)
                if match:
                    progress_val = float(match.group(1)) / 100
                    progress_text = f" — {match.group(1)}%"
                    break
        
            cols[1].markdown(
                f"<span style='margin-left:10px'>{phase.upper()} / {task_name}</span> "
                f"<span class='loader'></span>{progress_text}",
                unsafe_allow_html=True
            )
        
        elif status == "completed":
            progress_val = 1.0
            cols[1].write(f"{phase.upper()} / {task_name} — 100%")
        
        else:
            cols[1].write(f"{phase.upper()} / {task_name}")

        # Timing
        if start:
            cols[2].write(f"Start: {start.split()[1]} | ⏱ {duration(start, end)}")

        # Progress bar
        cols[3].progress(progress_val)

        # Logs
        if isinstance(log, list):
            with st.expander("More info", expanded=False):
                for item in log:
                    if isinstance(item, dict):
                        st.write(f"[{item['time']}] {item['msg']}")
                    else:
                        st.write(f"- {item}")



with st.expander("Status Legend", expanded=True):

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(status_badge("waiting") + " Not started", unsafe_allow_html=True)
    c2.markdown(status_badge("running") + " In progress", unsafe_allow_html=True)
    c3.markdown(status_badge("completed") + " Finished successfully", unsafe_allow_html=True)
    c4.markdown(status_badge("failed") + " Failed – needs attention", unsafe_allow_html=True)


def yaml_to_stair_outline(data):
    rows = []

    for step, (phase, task_name) in enumerate(PIPELINE_ORDER):
        meta = data.get(phase, {}).get(task_name, {})

        rows.append({
            "Phase": phase.upper(),
            "Task": task_name,
            "Step": step,
            "Status": meta.get("status", "waiting")
        })

    return pd.DataFrame(rows)

def render_stair_chart_outline(title, data):
    df = yaml_to_stair_outline(data)
    
    color_map = {
        "waiting": "lightgrey",
        "running": "#1f77b4",
        "completed": "#2ca02c",
        "failed": "#d62728"
    }

    fig = go.Figure()
    
    # Map y positions to numeric for line calculations
    phase_order = ["PRE", "NOWCAST", "FORECAST", "POST"]
    y_map = {phase: i for i, phase in enumerate(reversed(phase_order))}  # reversed so top is PRE

    bar_width = 0.8

    # --- Draw stair-step connectors (behind bars) ---
    for phase in phase_order:
        phase_df = df[df["Phase"] == phase]
        if not phase_df.empty:
            y = y_map[phase]
            x_min = phase_df["Step"].min()
            x_max = phase_df["Step"].max() + bar_width
            # Horizontal line for phase
            fig.add_shape(
                type="line",
                x0=x_min, x1=x_max,
                y0=y, y1=y,
                line=dict(color="black", width=1),
                layer="below"
            )
    
    # Draw vertical + 90° connectors between phases
    for i in range(len(phase_order)-1):
        upper_phase = phase_order[i]
        lower_phase = phase_order[i+1]
        upper_y = y_map[upper_phase]
        lower_y = y_map[lower_phase]

        # Center x of last task in upper phase
        x_center_upper = df[df["Phase"]==upper_phase]["Step"].max() + bar_width/2
        # Center x of first task in lower phase
        x_center_lower = df[df["Phase"]==lower_phase]["Step"].min() + bar_width/2

        # Draw vertical + horizontal as L-shaped line
        # Vertical from upper phase center down to lower y
        fig.add_shape(
            type="line",
            x0=x_center_upper, x1=x_center_upper,
            y0=upper_y, y1=lower_y,
            line=dict(color="black", width=1),
            layer="below"
        )
        # Horizontal to start of lower phase
        if x_center_lower != x_center_upper:
            fig.add_shape(
                type="line",
                x0=x_center_upper, x1=x_center_lower,
                y0=lower_y, y1=lower_y,
                line=dict(color="black", width=1),
                layer="below"
            )

    # --- Draw bars ---
    for _, row in df.iterrows():
        fig.add_trace(go.Bar(
            x=[bar_width],
            y=[y_map[row["Phase"]]],
            base=row["Step"],
            orientation='h',
            marker_color=color_map.get(row["Status"], "lightgrey"),
            marker_line_color="black",
            marker_line_width=1,
            hovertext=row["Task"],
            hoverinfo="text"
        ))

    fig.update_yaxes(
        tickvals=list(y_map.values()),
        ticktext=list(y_map.keys())
    )
    fig.update_xaxes(title="Pipeline Sequence", showticklabels=False)
    fig.update_layout(
        title=title,
        height=400,
        barmode='stack',
        margin=dict(l=20,r=20,t=30,b=20),
        showlegend=False
    )
    return fig

# -------------------------
# Tabs for Forecast Groups
# -------------------------
tab1, tab2 = st.tabs([
    "🌊 iFLOOD (ADCIRC + SWAN)",
    "🌊 HEC-RAS 2D (Compound DC)"
])

# -------------------------
# Tab 1: iFLOOD
# -------------------------
with tab1:
    col1, col2 = st.columns([1,1])

    with col1:
        render_pipeline("iFLOOD – Pipeline Status", iflood)

    with col2:
        fig = render_stair_chart_outline("iFLOOD Pipeline", iflood)
        st.plotly_chart(fig, use_container_width=True)

# -------------------------
# Tab 2: HEC-RAS
# -------------------------
with tab2:
    col1, col2 = st.columns([1,1])

    with col1:
        render_pipeline("HEC-RAS 2D - Pipeline Status", hecras)

    with col2:
        fig2 = render_stair_chart_outline("HEC-RAS Pipeline", hecras)
        st.plotly_chart(fig2, use_container_width=True)

