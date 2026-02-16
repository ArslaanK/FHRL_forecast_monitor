# -*- coding: utf-8 -*-
"""
Created on Sun Feb 15 23:59:18 2026

@author: akhal
"""

# pseudo code


# forecast_scheduled = date1, date2

# # in each forecast scheduled

# 2 sequential forecasts

# StormSurge through ADCIRC+SWAN called iFLOOD
# Riverforecast through HECRAS2D called Compound DC

# # in iflood

# config yml file with preloaded options
# change the key value from waiting to running based on the process started.
# when process ends, change status from running to completed
# keep doing the same until you get to the end
# pre
#     tide construct: waiting
#     metforecast processor: waiting
# nowcast    
#     nowcast sim for next forecast cycle called hotstart file: waiting
#     attach hotstart: waiting
# forecast
#     forecast cycle start: waiting
#     copy forecast results: waiting
# post
#     gen NWS forecasts: waiting
#     create forecasted timeseries: waiting
#     fetch competing model forecast: waiting
#     gen spatial maps: waiting
#     gen flood alerts: waiting
#     push forecast to S3: waiting
#     forecast pipleline completion: waiting 
# nowcast status
#     0
# forecast status
#     0

# # in hecras2d

# config yml file with preloaded options
# change the key value from waiting to running based on the process started.
# when process ends, change status from running to completed
# keep doing the same until you get to the end
# pre
#     BC construct: waiting
#     metforecast processor: waiting
# nowcast    
#     nowcast sim for next forecast cycle called hotstart file: waiting
#     attach hotstart: waiting
# forecast
#     forecast cycle start: waiting
#     copy forecast results: waiting
# post
#     create forecasted timeseries: waiting
#     fetch competing model forecast: waiting
#     gen spatial maps: waiting
#     push forecast to S3: waiting
#     forecast pipleline completion: waiting 
# nowcast status
#     0
# forecast status
#     0 

import streamlit as st
import yaml
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
import pandas as pd


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

# 🔄 auto refresh, 10 sec
#st_autorefresh(interval=10000, key="refresh")
# 🔄 auto refresh every 5 minutes
st_autorefresh(interval=300000, key="refresh")
# -------------------------
# Helpers
# -------------------------
def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)

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
    for phase in data.values():
        for task in phase.values():
            total += 1
            if task["status"] == "completed":
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
# Header
# -------------------------
st.title("🌊 FHRL Operational Forecast Dashboard")


colA, colB = st.columns([2,1])
#colA.markdown("**Forecast Cycle:** 2026-02-16 06Z")
colB.markdown(f"**Last Refresh:** {datetime.now().strftime('%H:%M:%S')}")

st.divider()

# -------------------------
# Load data
# -------------------------
iflood = load_yaml("iflood_status.yaml")
hecras = load_yaml("hecras_status.yaml")

# -------------------------
# Top progress bars
# -------------------------
c1, c2, c3 = st.columns(3)

# ------------------ Column 1: System Overview ------------------
c1.subheader("🖥 System Overview\nSpecs: 54 cores × 512GB RAM")
c1.metric("System Health", "RUNNING", "Nominal")
c1.metric("System Usage", "80%", "High")            # CPU/memory load
# c1.metric("System Specs", "54 cores × 512GB RAM", "")  # total cores & memory

# ------------------ Column 2: Jobs / Queues ------------------
c2.subheader("📊 Job Status")
c2.metric("iFLOOD Jobs", "2 running", "")
c2.metric("HEC-RAS Jobs", "0 running", "")


# ------------------ Column 3: Timing / Forecast Cycle ------------------
c3.subheader("⏱ Forecast Cycle")
c3.metric("Current Cycle", "2026-02-16 06Z", "")
c3.metric("Next Cycle ETA", "12:00 UTC", "")


c2.markdown("**iFLOOD Progress**")
c2.progress(pipeline_progress(iflood))

c3.markdown("**HEC-RAS Progress**")
c3.progress(pipeline_progress(hecras))

st.divider()


def get_status(meta):
    return meta.get("status", "waiting")

def get_current_task(data):
    for phase, tasks in data.items():
        for name, meta in tasks.items():
            if get_status(meta) == "running":
                return phase, name, meta
    return None, None, None



phase, task, meta = get_current_task(iflood)

# if task:
#     #st.warning(f"🟡 CURRENT PROCESS → {phase.upper()} / {task}")

#     cols = st.columns([1,2])

#     with cols[0]:
#         with st.spinner("Running"):
#             st.write("Processing...")

#     with cols[1]:
#         if meta.get("log"):
#             st.write(meta["log"])

#         if meta.get("start"):
#             st.write(f"⏱ Running for {duration(meta['start'], None)}")



def render_pipeline(title, data):

    st.subheader(title)

    for phase_name, tasks in data.items():

        with st.expander(phase_name.upper(), expanded=True):

            for task_name, meta in tasks.items():

                status = get_status(meta)
                start = meta.get("start")
                end = meta.get("end")
                log = meta.get("log")

                cols = st.columns([0.05, 0.55, 0.4])
                cols = st.columns([0.1, 0.6, 0.3])

                #cols[0].markdown(icon(status))
                cols[0].markdown(status_badge(status), unsafe_allow_html=True)


                # 🔄 RUNNING TASK
                if status == "running":
                    cols[1].markdown(
                        f"**&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{task_name}** <span class='loader'></span>",
                        unsafe_allow_html=True
                    )
                else:
                    cols[1].write(f"**{task_name}**")

                # ⏱ timing
                if start:
                    cols[2].write(
                        f"Start: {start.split()[1]} | ⏱ {duration(start, end)}"
                    )

                # 📜 MORE INFO PANEL
                # if log:
                #     with st.expander("More info", expanded=False):
                #         st.write(log)
                        
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


# left, right = st.columns(2)

# with left:
#     render_pipeline("iFLOOD – ADCIRC + SWAN", iflood)

# with right:
#     render_pipeline("HEC-RAS 2D – Compound DC", hecras)


def yaml_to_stair_outline(data):
    rows = []
    step_counter = 0
    for phase in ["pre", "nowcast", "forecast", "post"]:
        tasks = data.get(phase, {})
        for task_name, meta in tasks.items():
            rows.append({
                "Phase": phase.upper(),
                "Task": task_name,
                "Step": step_counter,
                "Status": meta.get("status", "waiting")
            })
            step_counter += 1
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


left, right = st.columns([1,1])

with left:
    render_pipeline("iFLOOD – ADCIRC + SWAN", iflood)

with right:
    fig = render_stair_chart_outline("iFLOOD Stair-Step Pipeline", iflood)
    st.plotly_chart(fig, use_container_width=True)

st.divider()

left2, right2 = st.columns([1,1])
with left2:
    render_pipeline("HEC-RAS 2D – Compound DC", hecras)

with right2:
    fig2 = render_stair_chart_outline("HEC-RAS Stair-Step Pipeline", hecras)
    st.plotly_chart(fig2, use_container_width=True)
