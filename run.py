# -*- coding: utf-8 -*-
"""
Created on Sun Feb 15 23:59:18 2026

@author: akhal
"""
#test
import streamlit as st
import yaml
from datetime import datetime, timedelta, timezone
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
import pandas as pd
import requests
import re
from zoneinfo import ZoneInfo
import pytz
import json
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
#st_autorefresh(interval=300000, key="refresh")
st_autorefresh(interval=60000, key="nws_refresh")

# -------------------------
# send slack alerts
# -------------------------

def send_slack_instability_alert(task_name):
    # Retrieve URL from secrets
    webhook_url = st.secrets["SLACK_WEBHOOK_URL"]
    
    payload = {
        "text": f"⚠️ *MODEL INSTABILITY DETECTED*\n"
                f"*Task:* {task_name}\n"
                f"The ADCIRC model has crashed due to an elevation/velocity blow-up. "
                f"Check the dashboard for details: https://fhrlforecastmonitor.streamlit.app/"
                f"Model needs a restart.",
    }
    
    try:
        response = requests.post(
            webhook_url, 
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'}
        )
        return response.status_code == 200
    except Exception as e:
        st.error(f"Failed to send Slack alert: {e}")
        return False
        
# -------------------------
# Helpers
# -------------------------
        
def is_nws_published(iflood):
    try:
        logs = iflood["post"]["gen_nws_forecast"]["log"]
        return any("iFLOOD forecasts uploaded for NWS" in l["msg"] for l in logs)
    except:
        return False
        
def format_countdown(target_dt):
    now = datetime.now(timezone.utc)
    remaining = target_dt - now

    if remaining.total_seconds() <= 0:
        return "Publishing..."

    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours}h {minutes}m {seconds}s"    


# Define timezones
utc = pytz.utc
est = pytz.timezone("US/Eastern")

def format_dual_time(dt):
    if dt is None:
        return "Unavailable"
    
    dt_utc = dt.astimezone(utc)
    dt_est = dt.astimezone(est)
    
    #return f"{dt_utc.strftime('%Y-%m-%d %HZ')} / {dt_est.strftime('%Y-%m-%d %I:%M %p ET')}"
    return f"{dt_utc.strftime('%Y-%m-%d %H:%MZ')}"


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
    elif status.lower() == "crashed":
        return "#d62728"  # red
    elif status.lower() == "waiting":
        return "#9e9e9e"  # gray
    elif status.lower() == "failed":
        return "#d62728"  # red     
    else:
        return "#FFC107"

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

# -------------------------
# Compute NWS ETA from first PRE log
# -------------------------
from datetime import datetime, timedelta, timezone
import pytz

et = pytz.timezone("US/Eastern")

def get_nws_eta(iflood, estimated_runtime=4):
    try:
        cycle_start = datetime.fromisoformat(iflood["cycle_start"])

        # Get first log entry (ET time)
        pre_logs = iflood["pre"]["metforecast_processor"]["log"]
        first_time_str = pre_logs[0]["time"]

        # Combine date + time (still naive)
        first_dt = datetime.combine(
            cycle_start.date(),
            datetime.strptime(first_time_str, "%H:%M:%S").time()
        )

        # LOCALIZE to ET (IMPORTANT FIX)
        first_dt_et = et.localize(first_dt)

        # Add runtime hours
        nws_publish_et = first_dt_et + timedelta(hours=estimated_runtime)

        # Convert to UTC
        nws_publish_utc = nws_publish_et.astimezone(timezone.utc)

        return nws_publish_utc

    except Exception:
        return None


 def render_pipeline_overview_single_bar(data):
    PHASE_WIDTHS = {
        "pre": 5.0,
        "nowcast": 15.0,
        "forecast": 65.0,
        "post": 15.0
    }

    total_progress = sum(phase_progress(data, phase) for phase in PHASE_WIDTHS)
    has_progress = total_progress > 0

    # Determine current active phase
    current_phase = None
    if has_progress:
        for phase in ["pre", "nowcast", "forecast", "post"]:
            tasks = data.get(phase, {})
            if any(t.get("status") == "running" for t in tasks.values()):
                current_phase = phase
                break
            elif any(t.get("status") == "waiting" for t in tasks.values()):
                current_phase = phase
                break

    # Labels row (same as before)
    labels_html = "<div style='display:flex; width:100%; margin-bottom:4px;'>"
    for phase, width in PHASE_WIDTHS.items():
        color = "#000000" if current_phase == phase else "#555"
        weight = "700" if current_phase == phase else "400"
        labels_html += f"<div style='width:{width}%; text-align:center; font-size:10px; font-weight:{weight}; color:{color}; text-transform:uppercase;'>{phase}</div>"
    labels_html += "</div>"

    # Progress bar row
    bar_html = "<div style='display:flex; width:100%; height:24px; border-radius:4px; overflow:hidden; border:1px solid #ddd;'>"
    for phase, width in PHASE_WIDTHS.items():
        progress = phase_progress(data, phase)
        
        # --- NEW: Check for instability in this specific phase ---
        phase_crashed = False
        tasks = data.get(phase, {})
        for t_meta in tasks.values():
            log = t_meta.get("log", [])
            if isinstance(log, list):
                if any("CRASHED" in (l.get("msg", "") if isinstance(l, dict) else str(l)) for l in log):
                    phase_crashed = True
                    break

        if phase == current_phase and progress == 0:
            visible_progress = 0.03
        else:
            visible_progress = max(progress, 0.02) if progress > 0 else 0

        # --- UPDATED: Fill Style Logic ---
        if phase_crashed:
            # Solid red to indicate the phase failed/stopped prematurely
            fill_style = "background-color:#d62728;" 
        elif progress >= 1.0:
            fill_style = "background-color:#2ca02c;"  # Completed green
        elif phase == current_phase:
            fill_style = "background: repeating-linear-gradient(45deg, #2ca02c, #2ca02c 6px, #1f7a1f 6px, #1f7a1f 12px);"
        else:
            fill_style = "background-color:#e0e0e0;"

        bar_html += f"<div style='width:{width}%; background-color:#f0f0f0; position:relative; border-right:1px solid white;'>"
        bar_html += f"<div style='width:{visible_progress*100}%; height:100%; {fill_style} transition: width 0.5s;'></div>"
        bar_html += "</div>"

    bar_html += "</div>"
    st.markdown(f"" + labels_html + bar_html, unsafe_allow_html=True)

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

def status_badge(status):
    """Return an HTML badge for the given status with inline styles."""
    
    if status == "running":
        # striped green running badge (inline)
        background_style = "background: repeating-linear-gradient(45deg, #2ca02c, #2ca02c 6px, #1f7a1f 6px, #1f7a1f 12px);"
    elif status == "completed":
        background_style = "background-color: #2ca02c;"
    elif status == "waiting":
        background_style = "background-color: #9e9e9e;"
    elif status == "failed":
        background_style = "background-color: #d62728;"
    else:
        background_style = "background-color: #9e9e9e;"

    return f"""
    <span style="
        display:inline-flex;
        align-items:center;
        justify-content:center;
        {background_style}
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
    # --- Check for instability across all tasks in this pipeline first ---
    is_unstable = False
    unstable_task = ""
    # 2. Re-insert the missing helper function
    def parse_start(meta):
        start_str = meta.get("start")
        if start_str:
            try:
                return datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.max
        return datetime.max
    for phase in ["nowcast", "forecast"]:
        for t_name, t_meta in pipeline_data.get(phase, {}).items():
            log = t_meta.get("log", [])
            if isinstance(log, list):
                if any("CRASHED" in (l.get("msg", "") if isinstance(l, dict) else str(l)) for l in log):
                    is_unstable = True
                    unstable_task = f"{phase.upper()} / {t_name}"
                    break

    # --- Render the Header and Unstable Banner ---
    st.subheader(title)
    if is_unstable:
        st.error(f"⚠️ **MODEL INSTABILITY DETECTED**: {unstable_task} has stopped due to elevation/velocity blow-up.")

    # --- Rest of your sorting and task rendering logic ---
    for phase in ["pre", "nowcast", "forecast", "post"]:
        tasks = pipeline_data.get(phase, {})
        if not tasks:
            continue

        # (Insert your existing sorting code here)
        sorted_tasks = sorted(tasks.items(), key=lambda x: parse_start(x[1]))

        for task_name, meta in sorted_tasks:
            status = meta.get("status", "waiting")
            log = meta.get("log", [])
            
            # Identify if THIS specific task crashed
            task_crashed = False
            if isinstance(log, list):
                task_crashed = any("CRASHED" in (l.get("msg", "") if isinstance(l, dict) else str(l)) for l in log)


            if is_unstable:
                # Use session state to ensure you only get ONE notification per browser session
                if f"alert_sent_{unstable_task}" not in st.session_state:
                    send_slack_instability_alert(unstable_task)
                    st.session_state[f"alert_sent_{unstable_task}"] = True
            
            cols = st.columns([0.1, 0.5, 0.3, 0.3])
  
            # Badge logic: Force FAILED if crashed
            badge_type = "failed" if task_crashed else status
            cols[0].markdown(status_badge(badge_type), unsafe_allow_html=True)

            # Bar logic: Force Red if crashed
            if task_crashed:
                fill_style = "background-color:#d62728;"
                progress_val = 0.95 # Keep bar nearly full to show where it stopped
            elif status == "running":
                fill_style = "background: repeating-linear-gradient(45deg, #2ca02c, #2ca02c 8px, #1f7a1f 8px, #1f7a1f 16px);"
                # ... (your progress calculation)
            else:
                fill_style = "background-color:#2ca02c;" if status == "completed" else "background-color:#e0e0e0;"

            # Render UI
            cols[1].markdown(f"&nbsp;&nbsp;&nbsp;**{phase.upper()} / {task_name}**")
            # ... (render timing and progress bar using the fill_style above)

            # Logs (Expander kept collapsed as requested)
            if isinstance(log, list):
                with st.expander("More info", expanded=False):
                    for item in log:
                        msg_text = item['msg'] if isinstance(item, dict) else str(item)
                        st.write(f"- {msg_text}")

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



# -------------------------
# Load data
# -------------------------
iflood = load_yaml("https://raw.githubusercontent.com/ArslaanK/FHRL_forecast_monitor/refs/heads/main/assets/iflood_status.yaml")
hecras = load_yaml("https://raw.githubusercontent.com/ArslaanK/FHRL_forecast_monitor/refs/heads/main/assets/hecras_status.yaml")


# -------------------------
# Forecast Cycle
# -------------------------
# Read current cycle from YAML (top-level key)
cycle_str = iflood.get("cycle_start", None)
if cycle_str:
    cycle_dt = datetime.fromisoformat(cycle_str)
else:
    #st.warning("cycle_start not found in YAML!")
    cycle_dt = datetime.utcnow()  # fallback

# -------------------------
# Round to nearest 00Z or 12Z
# -------------------------
hour = cycle_dt.hour
if hour < 8:
    # Round to 00Z same day
    cycle_dt = cycle_dt.replace(hour=0, minute=0, second=0, microsecond=0)
elif hour < 23:
    # Round to 12Z same day
    cycle_dt = cycle_dt.replace(hour=12, minute=0, second=0, microsecond=0)

# Next cycle is always 12 hours later
next_cycle_dt = cycle_dt + timedelta(hours=12)

# st.write(f"Current forecast cycle (rounded): {cycle_dt} UTC")
# st.write(f"Next forecast cycle: {next_cycle_dt} UTC")

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
with col2:
    st.subheader("📊 Pipeline Progress")
    st.markdown("**iFLOOD**")
    render_pipeline_overview_single_bar(iflood)
    

    st.markdown("**Compound DC**")
    render_pipeline_overview_single_bar(hecras)
        
# Column 3: Forecast Cycle
nws_eta = get_nws_eta(iflood,estimated_runtime=4)
with col3:
    st.subheader("⏱ Forecast Cycle")
    
    st.metric("Current Cycle", format_dual_time(cycle_dt))
    st.metric("Next Cycle", format_dual_time(next_cycle_dt))

    if nws_eta:
    
        if is_nws_published(iflood):
            st.metric("NWS Forecast", "PUBLISHED")
            st.link_button(
            "View Published Forecast",
            "https://data.iflood.vse.gmu.edu/?prefix=Forecast/ChesapeakeBay_ADCIRCSWAN/iflood_Advisories_for_NWS"
        )
    
        else:
            st.metric(
                "NWS Forecast ETA",
                nws_eta.strftime('%Y-%m-%d %H:%MZ'),
                delta=f"⏳ {format_countdown(nws_eta)} remaining"
            )
    
    else:
        st.metric("NWS Forecast ETA", "Unavailable")


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


# -------------------------
# 1️⃣ Convert YAML-style task data to a structured DataFrame
# -------------------------
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
                    return datetime.max
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


# -------------------------
# 2️⃣ Render stair-step chart with hatching for running
# -------------------------
def render_stair_chart_outline(title, data):
    df = yaml_to_stair_outline(data)

    color_map = {
        "waiting": "lightgrey",
        "running": "#2ca02c",
        "completed": "#2ca02c",
        "failed": "#d62728"
    }

    pattern_map = {
        "running": "/",  # diagonal hatch
        "waiting": "",   # solid
        "completed": "", # solid
        "failed": ""     # solid
    }

    fig = go.Figure()

    # Map y positions to numeric
    phase_order = ["PRE", "NOWCAST", "FORECAST", "POST"]
    phases_present = [p for p in phase_order if not df[df["Phase"] == p].empty]
    y_map = {phase: i for i, phase in enumerate(reversed(phases_present))}
    bar_width = 0.8

    # --- Draw stair-step connectors ---
    for phase in phases_present:
        phase_df = df[df["Phase"] == phase]
        if not phase_df.empty:
            y = y_map[phase]
            x_min = phase_df["Step"].min()
            x_max = phase_df["Step"].max() + bar_width
            fig.add_shape(
                type="line",
                x0=x_min, x1=x_max,
                y0=y, y1=y,
                line=dict(color="black", width=1),
                layer="below"
            )

    # Draw vertical + horizontal L-shaped connectors
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

        # vertical
        fig.add_shape(
            type="line",
            x0=x_center_upper, x1=x_center_upper,
            y0=upper_y, y1=lower_y,
            line=dict(color="black", width=1),
            layer="below"
        )
        # horizontal
        if x_center_lower != x_center_upper:
            fig.add_shape(
                type="line",
                x0=x_center_upper, x1=x_center_lower,
                y0=lower_y, y1=lower_y,
                line=dict(color="black", width=1),
                layer="below"
            )

    # --- Draw bars with hatching for running ---
    for _, row in df.iterrows():
        pattern_shape = pattern_map.get(row["Status"], "")
        pattern_size = 5 if row["Status"] == "running" else 6  # wider for running
        
        fig.add_trace(go.Bar(
            x=[bar_width],
            y=[y_map[row["Phase"]]],
            base=row["Step"],
            orientation='h',
            marker_color=color_map.get(row["Status"], "lightgrey"),
            marker_line_color="black",
            marker_line_width=1,
            marker_pattern_shape=pattern_shape,
            marker_pattern_size=pattern_size,
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
