"""
app.py - Streamlit dashboard for live meet tracking.
Run: streamlit run app.py -- https://flashresults.com/2026_Meets/Indoor/02-26_SEC

Auto-refreshes every REFRESH_INTERVAL_SECONDS and sends email on new finals.
"""

import time
import json
import logging
import os
import sys
from datetime import datetime

import streamlit as st

# Must be first Streamlit call
st.set_page_config(
    page_title="Track & Field Live Tracker",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from config import get_meet_url, REFRESH_INTERVAL_SECONDS, PLACE_POINTS
from data_model import Gender, EventStatus, RoundType
from scraper import scrape_meet
from scoring import run_all_analysis, compute_team_scenarios
from graphics import (
    chart_current_standings, chart_projected_scores,
    chart_win_probability, chart_leverage_index, chart_team_scenarios
)
from emailer import send_update_email, detect_new_finals

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS — dark theme override
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .stApp { background-color: #0d1117; color: #e6edf3; }
    .stTabs [data-baseweb="tab-list"] { background-color: #161b22; border-radius: 8px; }
    .stTabs [data-baseweb="tab"] { color: #8b949e; }
    .stTabs [aria-selected="true"] { color: #f0c040 !important; }
    .metric-card {
        background: #161b22; border: 1px solid #21262d; border-radius: 8px;
        padding: 12px 16px; text-align: center; margin: 4px;
    }
    .metric-value { font-size: 28px; font-weight: bold; color: #f0c040; }
    .metric-label { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
    .leverage-headline {
        background: #1c2128; border-left: 3px solid #f0c040;
        padding: 8px 12px; margin: 6px 0; border-radius: 0 6px 6px 0;
        font-size: 13px; color: #e6edf3;
    }
    .event-badge {
        display: inline-block; background: #21262d; border-radius: 4px;
        padding: 2px 8px; font-size: 11px; color: #8b949e; margin: 2px;
    }
    div[data-testid="stMetricValue"] { color: #f0c040; }
    h1, h2, h3 { color: #e6edf3; }
    .stSelectbox label { color: #8b949e; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _init_session_state():
    if "last_scrape_time" not in st.session_state:
        st.session_state.last_scrape_time = 0
    if "meet_state" not in st.session_state:
        st.session_state.meet_state = None
    if "women_analysis" not in st.session_state:
        st.session_state.women_analysis = None
    if "men_analysis" not in st.session_state:
        st.session_state.men_analysis = None
    if "known_finals" not in st.session_state:
        st.session_state.known_finals = set()
    if "meet_url" not in st.session_state:
        st.session_state.meet_url = get_meet_url()


def _should_refresh() -> bool:
    elapsed = time.time() - st.session_state.last_scrape_time
    return elapsed >= REFRESH_INTERVAL_SECONDS or st.session_state.meet_state is None


def _run_scrape_and_analysis():
    """Scrape meet and run all analysis layers. Update session state."""
    meet_url = st.session_state.meet_url
    with st.spinner("🔄 Fetching live results..."):
        try:
            state = scrape_meet(meet_url)
            women_analysis = run_all_analysis(state, Gender.WOMEN)
            men_analysis = run_all_analysis(state, Gender.MEN)

            # Check for new finals and send email
            new_finals, updated_finals = detect_new_finals(state, st.session_state.known_finals)
            if new_finals:
                _send_email_update(new_finals, women_analysis, men_analysis, state.meet_name)
                st.session_state.known_finals = updated_finals

            st.session_state.meet_state = state
            st.session_state.women_analysis = women_analysis
            st.session_state.men_analysis = men_analysis
            st.session_state.last_scrape_time = time.time()

        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            st.error(f"⚠️ Failed to fetch results: {e}")


def _send_email_update(new_finals, women_analysis, men_analysis, meet_name):
    """Build charts and send email."""
    try:
        chart_bytes = {}
        for analysis, prefix in [(women_analysis, "Women"), (men_analysis, "Men")]:
            ts = analysis["team_scores"]
            g = analysis["gender"]
            chart_bytes[f"{prefix} Standings"] = chart_current_standings(ts, g, meet_name)
            chart_bytes[f"{prefix} Projections"] = chart_projected_scores(ts, g, meet_name)
            chart_bytes[f"{prefix} Win Probability"] = chart_win_probability(ts, g, meet_name)
            chart_bytes[f"{prefix} Leverage Index"] = chart_leverage_index(
                analysis["leverage_index"], g, meet_name
            )

        send_update_email(
            new_event_names=new_finals,
            women_analysis=women_analysis,
            men_analysis=men_analysis,
            chart_bytes=chart_bytes,
            meet_name=meet_name,
        )
    except Exception as e:
        logger.error(f"Email send failed: {e}")


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_standings_table(analysis: dict):
    """Clean HTML standings table."""
    ts_list = analysis.get("team_scores", [])
    if not ts_list:
        st.info("No scoring data yet.")
        return

    rows_html = ""
    for i, ts in enumerate(ts_list[:16]):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        win_bar = "▓" * int(ts.win_probability / 5) + "░" * (20 - int(ts.win_probability / 5))
        rows_html += f"""
        <tr style="background:{'#1c2128' if i % 2 == 0 else '#161b22'};">
            <td style="padding:7px 12px;color:#8b949e;width:36px;">{medal}</td>
            <td style="padding:7px 12px;color:#e6edf3;font-weight:600;">{ts.team}</td>
            <td style="padding:7px 12px;color:#f0c040;text-align:right;font-weight:bold;">{round(ts.actual_points, 2):g}</td>
            <td style="padding:7px 12px;color:#58a6ff;text-align:right;">{round(ts.seed_projection, 2):g}</td>
            <td style="padding:7px 12px;color:#3fb950;text-align:right;">{round(ts.optimistic_ceiling, 2):g}</td>
            <td style="padding:7px 12px;color:#bc8cff;text-align:right;">{ts.win_probability:.1f}%</td>
        </tr>"""

    st.markdown(f"""
    <table style="border-collapse:collapse;width:100%;font-size:13px;">
        <thead>
            <tr style="background:#21262d;border-bottom:1px solid #30363d;">
                <th style="padding:8px 12px;color:#8b949e;text-align:left;">#</th>
                <th style="padding:8px 12px;color:#8b949e;text-align:left;">Team</th>
                <th style="padding:8px 12px;color:#8b949e;text-align:right;">Actual</th>
                <th style="padding:8px 12px;color:#8b949e;text-align:right;">Projected</th>
                <th style="padding:8px 12px;color:#8b949e;text-align:right;">Ceiling</th>
                <th style="padding:8px 12px;color:#8b949e;text-align:right;">Win %</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    """, unsafe_allow_html=True)


def _render_leverage_headlines(leverage_data: list[dict]):
    """Show top leverage events as styled headline cards."""
    if not leverage_data:
        st.info("No remaining events to analyze.")
        return

    st.markdown("### 🔥 Must-Watch Remaining Events")
    for item in leverage_data[:6]:
        st.markdown(
            f'<div class="leverage-headline">{item["headline"]}</div>',
            unsafe_allow_html=True
        )


def _render_scenario_builder(analysis: dict, state):
    """Interactive scenario builder — user picks a team."""
    ts_list = analysis.get("team_scores", [])
    if not ts_list:
        st.info("No data available.")
        return

    gender = analysis["gender"]
    all_teams = sorted([ts.team for ts in ts_list])

    st.markdown("### 🎯 What-If Scenario Builder")
    st.caption("Select a team to see their range of possible final scores.")

    selected_team = st.selectbox(
        "Choose a team:",
        all_teams,
        key=f"scenario_team_{gender.value}",
        label_visibility="collapsed"
    )

    if selected_team:
        actual = analysis["actual"]
        scenario = compute_team_scenarios(selected_team, actual, state, gender)

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value" style="color:#58a6ff;">{scenario['current']}</div>
                <div class="metric-label">Current Score</div>
            </div>""", unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value" style="color:#f85149;">{scenario['scenario_c']}</div>
                <div class="metric-label">Worst Case</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value" style="color:#f0c040;">{scenario['scenario_a']}</div>
                <div class="metric-label">Seeds Hold</div>
            </div>""", unsafe_allow_html=True)
        with col4:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value" style="color:#3fb950;">{scenario['scenario_b']}</div>
                <div class="metric-label">Best Case</div>
            </div>""", unsafe_allow_html=True)

        # Chart
        chart_bytes = chart_team_scenarios(scenario, state.meet_name)
        st.image(chart_bytes, use_container_width=True)

        # Event-by-event breakdown
        if scenario["breakdown"]:
            st.markdown("**Event Breakdown:**")
            for ev in scenario["breakdown"]:
                with st.expander(f"{ev['event']} — Seeds Hold: +{ev['scenario_a_pts']} pts | Best: +{ev['scenario_b_pts']} pts"):
                    for ath in ev["athletes"]:
                        st.markdown(
                            f"&nbsp;&nbsp;• **{ath['athlete']}** — "
                            f"Seed: `{ath['seed_mark']}` → "
                            f"Proj. Place: **{ath['proj_place']}** "
                            f"({ath['seed_pts']} pts)"
                        )


def _render_gender_tab(analysis: dict, state):
    """Render all content for one gender tab."""
    if not analysis:
        st.warning("Analysis not yet available. Refreshing...")
        return

    gender = analysis["gender"]
    ts_list = analysis["team_scores"]
    leverage = analysis["leverage_index"]

    # ---- Top metrics row ----
    leader = ts_list[0] if ts_list else None
    completed = len(state.get_completed_finals(gender))
    total_finals = len([e for e in state.events
                        if e.gender == gender and e.round_type == RoundType.FINAL])
    upcoming = total_finals - completed

    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
    with mcol1:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{leader.team if leader else '—'}</div>
            <div class="metric-label">Current Leader</div>
        </div>""", unsafe_allow_html=True)
    with mcol2:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{f"{leader.actual_points:g}" if leader else 0}</div>
            <div class="metric-label">Leader's Points</div>
        </div>""", unsafe_allow_html=True)
    with mcol3:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{completed}</div>
            <div class="metric-label">Finals Scored</div>
        </div>""", unsafe_allow_html=True)
    with mcol4:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{upcoming}</div>
            <div class="metric-label">Finals Remaining</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ---- Main content: standings + charts ----
    left, right = st.columns([1.2, 1])

    with left:
        st.markdown("### 📊 Live Standings")
        _render_standings_table(analysis)

        st.markdown("---")
        _render_leverage_headlines(leverage)

    with right:
        chart_tab1, chart_tab2, chart_tab3 = st.tabs(
            ["📈 Projections", "🎲 Win Probability", "🏆 Leverage"]
        )
        with chart_tab1:
            img = chart_projected_scores(ts_list, gender, state.meet_name)
            st.image(img, use_container_width=True)
        with chart_tab2:
            img = chart_win_probability(ts_list, gender, state.meet_name)
            st.image(img, use_container_width=True)
        with chart_tab3:
            if not leverage:
                st.info("No remaining events to analyze.")
            else:
                rows = ""
                for item in leverage[:8]:
                    event = item["event_name"].replace("Women ", "W ").replace("Men ", "M ")
                    pts = item["total_pts_available"]
                    n_teams = item["n_teams"]
                    contenders = ", ".join(item["top_teams_in_event"][:3]) or "—"
                    rows += f"""
                    <tr>
                        <td style="padding:8px 12px;color:#f0c040;font-weight:600;">{event}</td>
                        <td style="padding:8px 12px;text-align:center;color:#3fb950;">{pts}</td>
                        <td style="padding:8px 12px;text-align:center;color:#8b949e;">{n_teams}</td>
                        <td style="padding:8px 12px;color:#58a6ff;font-size:12px;">{contenders}</td>
                    </tr>"""
                st.markdown(f"""
                <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <thead>
                        <tr style="border-bottom:1px solid #30363d;">
                            <th style="padding:8px 12px;text-align:left;color:#8b949e;">Event</th>
                            <th style="padding:8px 12px;text-align:center;color:#8b949e;">Pts Available</th>
                            <th style="padding:8px 12px;text-align:center;color:#8b949e;">Teams</th>
                            <th style="padding:8px 12px;text-align:left;color:#8b949e;">Top Contenders</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                <p style="color:#8b949e;font-size:11px;margin-top:8px;text-align:center;">
                    Sorted by impact on final standings · Top contenders = current top-5 teams with entries
                </p>
                """, unsafe_allow_html=True)

    st.markdown("---")
    _render_scenario_builder(analysis, state)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    _init_session_state()

    # Header
    meet_name = (
        st.session_state.meet_state.meet_name
        if st.session_state.meet_state else "Track & Field Live Tracker"
    )

    st.markdown(f"""
    <h1 style="text-align:center;color:#f0c040;margin-bottom:4px;">
        🏃 {meet_name}
    </h1>
    <p style="text-align:center;color:#8b949e;font-size:13px;margin-bottom:12px;">
        Live scoring analysis · Auto-refreshes every {REFRESH_INTERVAL_SECONDS // 60} minutes
    </p>
    <div style="text-align:center;margin-bottom:20px;">
        <a href="https://buymeacoffee.com/trackandfielddata" target="_blank"
           style="display:inline-block;background-color:#FFDD00;color:#000000;
                  font-weight:700;font-size:14px;padding:10px 22px;border-radius:8px;
                  text-decoration:none;letter-spacing:0.3px;">
            ☕ Enjoying the live tracker? Buy me a coffee
        </a>
        <p style="color:#8b949e;font-size:11px;margin-top:6px;">
            This tool is free — tips help keep it running all season 🙏
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Refresh controls
    col_status, col_btn = st.columns([3, 1])
    with col_status:
        if st.session_state.last_scrape_time:
            last = datetime.fromtimestamp(st.session_state.last_scrape_time)
            elapsed = int(time.time() - st.session_state.last_scrape_time)
            next_refresh = max(0, REFRESH_INTERVAL_SECONDS - elapsed)
            st.caption(
                f"Last updated: {last.strftime('%I:%M:%S %p')} · "
                f"Next refresh in {next_refresh}s"
            )
    with col_btn:
        if st.button("🔄 Refresh Now", type="secondary"):
            st.session_state.last_scrape_time = 0

    # Auto-refresh or manual trigger
    if _should_refresh():
        _run_scrape_and_analysis()

    # Tabs
    if st.session_state.women_analysis and st.session_state.men_analysis:
        women_tab, men_tab = st.tabs(["🚺 Women's", "🚹 Men's"])

        with women_tab:
            _render_gender_tab(
                st.session_state.women_analysis,
                st.session_state.meet_state
            )

        with men_tab:
            _render_gender_tab(
                st.session_state.men_analysis,
                st.session_state.meet_state
            )
    else:
        st.info("⏳ Loading meet data for the first time...")

    # Auto-rerun timer
    elapsed = time.time() - st.session_state.last_scrape_time
    time_to_next = max(1, REFRESH_INTERVAL_SECONDS - int(elapsed))
    time.sleep(min(time_to_next, 30))  # Check every 30s max
    st.rerun()


if __name__ == "__main__":
    main()
