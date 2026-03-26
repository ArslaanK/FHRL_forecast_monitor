# -*- coding: utf-8 -*-
"""
Created on Sun Feb 15 23:59:18 2026

@author: akhal
"""
#test
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

# -------------------------
# Helpers
# -------------------------
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

def phase_progress(data, phase_name):
    """
    Calculate the average progress for a given phase as a float between 0 and 1.

    Args:
        data (dict): Pipeline data containing tasks for all phases.
        phase_name (str): Name of the phase ("pre", "nowcast", "forecast", "post").

    Returns:
        float: Average progress of the phase (0.0 to 1.0)
    """
    tasks = data.get(phase_name, {})
    if not tasks:
        return 0.0

    total_tasks = 0
    completed_tasks = 0
    running_progress = 0.0

    for task in tasks.values():
        total_tasks += 1
        status = task.get("status", "waiting")

        if status == "completed":
            completed_tasks += 1
        elif status == "running" and isinstance(task.get("log"), list):
            # Find the latest progress percentage in logs
            for entry in reversed(task["log"]):
                msg = entry.get("msg") if isinstance(entry, dict) else str(entry)
                match = re.search(r"([\d\.]+)%", msg)
                if match:
                    running_progress += float(match.group(1)) / 100
                    break

    if total_tasks == 0:
        return 0.0

    # Each completed task counts as 1.0, running tasks contribute partial progress
    average_progress = (completed_tasks + running_progress) / total_tasks
    return min(average_progress, 1.0)  # Ensure progress never exceeds 1.0
    

def get_progress_color(status):
    if status.lower() == "completed":
        return "#2ca02c"  # green
    elif status.lower() == "running":
        return "#1f77b4"  # blue
    elif status.lower() == "waiting":
        return "#9e9e9e"  # gray
    # elif status.lower() == "failed":
    #     return "#d62728"  # red
    else:
        return "#FFC107"  # amber for other statuses

        
# PIPELINE_ORDER = [
#     ("pre", "metforecast_processor"),
#     ("pre", "prep_simulation"),

#     ("nowcast", "run_nowcast"),

#     ("forecast", "run_forecast"),
#     ("forecast", "copy_forecast_results"),
  
#     ("post", "gen_nws_forecast"),
#     ("post", "gen_spatial_maps"),  
#     ("post", "create_timeseries"),
#     ("post", "fetch_competing_model"),
#     ("post", "gen_flood_alerts"),
#     ("post", "push_to_s3"),
#     ("post", "pipeline_completion"),

# ]

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

PHASE_WIDTHS = {
    "pre": 3.2,
    "nowcast": 14.7,
    "forecast": 68.5,
    "post": 13.6,
}

PHASE_COLORS = {
    "pre": "#2ca02c",      # green completed
    "nowcast": "#ff7f0e",  # orange running
    "forecast": "#1f77b4", # blue active
    "post": "#9467bd",     # purple
}

def render_pipeline_overview_single_bar(data):
    """
    Render a single horizontal progress bar split into 4 phases
    with visible partition lines and phase labels on top.
    """
    PHASE_WIDTHS = {
        "pre": 3.2,
        "nowcast": 14.7,
        "forecast": 68.5,
        "post": 13.6
    }

    # Determine current phase
    current_phase = "pre"
    for phase in ["pre", "nowcast", "forecast", "post"]:
        tasks = data.get(phase, {})
        if any(t.get("status") == "running" for t in tasks.values()):
            current_phase = phase
            break
        elif any(t.get("status") != "completed" for t in tasks.values()):
            current_phase = phase
            break
        else:
            current_phase = phase  # last completed phase

    # Start HTML
    html = "<div style='position:relative; width:100%; height:40px;'>"

    # Phase labels
    cumulative_width = 0
    for phase, width in PHASE_WIDTHS.items():
        label_pos = cumulative_width + width / 2
        html += f"""
        <div style='position:absolute; top:0; left:{label_pos}%; transform:translateX(-50%);
                    font-size:10px; font-weight:bold; text-align:center;'>{phase.upper()}</div>
        """
        cumulative_width += width

    # Progress bar container
    html += "<div style='position:relative; width:100%; height:20px; background-color:#e0e0e0; border-radius:6px; margin-top:18px; display:flex; overflow:hidden;'>"

    # Draw each phase segment
    for idx, (phase, width) in enumerate(PHASE_WIDTHS.items()):
        progress = phase_progress(data, phase)
        # Determine color
        if progress >= 1:
            color = "#2ca02c"  # green completed
        elif phase == current_phase:
            color = "#1f77b4"  # blue active
        else:
            color = "#9e9e9e"  # gray waiting

        html += f"""
        <div style='position:relative; width:{width}%; height:100%;'>
            <div style='width:{progress*100}%; background-color:{color}; height:100%; border-radius:3px 0 0 3px;'></div>
            <!-- Partition line except last -->
            {'<div style="position:absolute; right:0; top:0; width:1px; height:100%; background-color:white; opacity:0.7;"></div>' if idx < len(PHASE_WIDTHS)-1 else ''}
        </div>
        """

    html += "</div></div>"

    st.markdown(html, unsafe_allow_html=True)


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
        if not phase:
            continue  # skip missing phases

        for task in phase.values():
            if isinstance(task, dict):
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

def render_pipeline(title, pipeline_data):
    st.subheader(title)

    for phase in ["pre", "nowcast", "forecast", "post"]:
        tasks = pipeline_data.get(phase, {})   # get phase tasks

        if not tasks:
            continue

        # --- Sort tasks by start time ---
        def parse_start(meta):
            start_str = meta.get("start")
            if start_str:
                try:
                    return datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except:
                    return datetime.max  # put invalid/missing start at the end
            else:
                return datetime.max

        sorted_tasks = sorted(tasks.items(), key=lambda x: parse_start(x[1]))

        # --- Render sorted tasks ---
        for task_name, meta in sorted_tasks:
            status = meta.get("status", "waiting")
            start = meta.get("start")
            end = meta.get("end")
            log = meta.get("log")

            cols = st.columns([0.1, 0.5, 0.3, 0.3])
            cols[0].markdown(status_badge(status), unsafe_allow_html=True)

            base_label = f"{phase.upper()} / {task_name}"

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
                cols[1].markdown(f"&nbsp;&nbsp;&nbsp;**{base_label}**{progress_text}", unsafe_allow_html=True)
            elif status == "completed":
                progress_val = 1.0
                cols[1].markdown(f"&nbsp;&nbsp;&nbsp;**{base_label} — 100%**", unsafe_allow_html=True)
            else:
                cols[1].markdown(f"&nbsp;&nbsp;&nbsp;**{base_label}**", unsafe_allow_html=True)

            # Timing
            if start:
                cols[2].write(f"Start: {start.split()[1]} | ⏱ {duration(start, end)}")

            # Progress bar
            color = get_progress_color(status)
            progress_html = f"""
            <div style='background-color:#e0e0e0; border-radius:4px; height:16px; width:100%;'>
                <div style='width:{progress_val*100}%; background-color:{color}; height:16px; border-radius:4px;'></div>
            </div>
            """
            cols[3].markdown(progress_html, unsafe_allow_html=True)

            # Logs
            if isinstance(log, list):
                with st.expander("More info", expanded=False):
                    for item in log:
                        if isinstance(item, dict):
                            st.write(f"[{item['time']}] {item['msg']}")
                        else:
                            st.write(f"- {item}")


# Helper: get fraction of a phase completed
def get_phase_progress(phase_data):
    """
    Returns 0-1 fraction based on completed tasks in this phase.
    If all tasks completed, returns 1.0.
    """
    if not phase_data:
        return 0
    total_tasks = len(phase_data)
    done_tasks = sum(1 for t in phase_data.values() if t.get("status") == "completed")
    return done_tasks / total_tasks if total_tasks else 0

# Fixed phase widths (percent of total bar)
PHASE_WIDTHS = {
    "pre": 5,
    "nowcast": 15,
    "forecast": 70,
    "post": 15,
}

# Colors for each phase
PHASE_COLORS = {
    "pre": "#1f77b4",       # blue
    "nowcast": "#ff7f0e",   # orange
    "forecast": "#2ca02c",  # green
    "post": "#d62728",      # red
}



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
    st.metric("System Health", "RUNNING")
    st.metric("System Usage", f"{usage:.1f}%", delta=status,delta_color='inverse')

# Column 2: Pipeline Progress
# with col2:
#     st.subheader("📊 Pipeline Progress")
#     st.markdown("**iFLOOD**")
#     st.progress(pipeline_progress(iflood))
#     st.markdown("**Compound DC**")
#     st.progress(pipeline_progress(hecras))
# Column 2: Pipeline Progress
with col2:
    st.subheader("📊 Pipeline Progress")
    st.markdown("**iFLOOD**")
    render_pipeline_overview_single_bar(iflood)
    

    st.markdown("**Compound DC**")
    render_pipeline_overview_single_bar(hecras)
        
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


with st.expander("Status Legend", expanded=False):

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(status_badge("waiting") + " Not started", unsafe_allow_html=True)
    c2.markdown(status_badge("running") + " In progress", unsafe_allow_html=True)
    c3.markdown(status_badge("completed") + " Finished successfully", unsafe_allow_html=True)
    c4.markdown(status_badge("failed") + " Failed – needs attention", unsafe_allow_html=True)

def yaml_to_stair_outline(data):
    rows = []
    step = 0

    for phase in ["pre", "nowcast", "forecast", "post"]:
        tasks = data.get(phase, {})

        if not tasks:
            continue

        # --- Sort tasks by start time ---
        def parse_start(meta):
            start_str = meta.get("start")
            if start_str:
                try:
                    return datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except:
                    return datetime.max  # put invalid/missing start at the end
            else:
                return datetime.max

        sorted_tasks = sorted(tasks.items(), key=lambda x: parse_start(x[1]))

        for task_name, meta in sorted_tasks:
            rows.append({
                "Phase": phase.upper(),
                "Task": task_name,
                "Step": step,
                "Status": meta.get("status", "waiting")
            })
            step += 1

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
    
    # Only keep phases that actually have tasks
    phases_present = [p for p in phase_order if not df[df["Phase"] == p].empty]
    
    y_map = {phase: i for i, phase in enumerate(reversed(phases_present))}

    bar_width = 0.8

    # --- Draw stair-step connectors (behind bars) ---
    for phase in phases_present:
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
    for i in range(len(phases_present)-1):
        upper_phase = phases_present[i]
        lower_phase = phases_present[i+1]
    
        upper_df = df[df["Phase"] == upper_phase]
        lower_df = df[df["Phase"] == lower_phase]
    
        if upper_df.empty or lower_df.empty:
            continue
    
        upper_y = y_map[upper_phase]
        lower_y = y_map[lower_phase]
    
        x_center_upper = upper_df["Step"].max() + bar_width/2
        x_center_lower = lower_df["Step"].min() + bar_width/2

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
    "🌧️ Compound DC (HEC-RAS 2D)"
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
        render_pipeline("Compound DC - Pipeline Status", hecras)

    with col2:
        fig2 = render_stair_chart_outline("Compound DC Pipeline", hecras)
        st.plotly_chart(fig2, use_container_width=True)

