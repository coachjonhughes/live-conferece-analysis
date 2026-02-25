"""
graphics.py - Generate dark-themed matplotlib charts for dashboard and social media.
All charts exported as PNG at social-media-ready resolution.
"""

import io
import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from data_model import Gender, TeamScore
from config import PLACE_POINTS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette — dark theme
# ---------------------------------------------------------------------------
DARK_BG       = "#0d1117"
PANEL_BG      = "#161b22"
ACCENT_GOLD   = "#f0c040"
ACCENT_BLUE   = "#58a6ff"
ACCENT_GREEN  = "#3fb950"
ACCENT_RED    = "#f85149"
ACCENT_PURPLE = "#bc8cff"
ACCENT_ORANGE = "#ff9a00"
TEXT_PRIMARY  = "#e6edf3"
TEXT_MUTED    = "#8b949e"
GRID_COLOR    = "#21262d"

TEAM_COLORS = [
    ACCENT_GOLD, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED,
    ACCENT_PURPLE, ACCENT_ORANGE, "#39d353", "#ff6eb4",
    "#70b8ff", "#ffa657", "#79c0ff", "#d2a8ff",
    "#ff7b72", "#56d364", "#e3b341", "#a5d6ff",
]

def _get_team_color_map(teams: list[str]) -> dict[str, str]:
    return {team: TEAM_COLORS[i % len(TEAM_COLORS)] for i, team in enumerate(teams)}


def _apply_dark_style(fig, ax_list=None):
    """Apply consistent dark theme to figure and axes."""
    fig.patch.set_facecolor(DARK_BG)
    if ax_list is None:
        ax_list = fig.get_axes()
    for ax in ax_list:
        ax.set_facecolor(PANEL_BG)
        ax.tick_params(colors=TEXT_PRIMARY, labelsize=9)
        ax.xaxis.label.set_color(TEXT_PRIMARY)
        ax.yaxis.label.set_color(TEXT_PRIMARY)
        ax.title.set_color(TEXT_PRIMARY)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COLOR)
        ax.grid(color=GRID_COLOR, linewidth=0.5, alpha=0.7)


def _fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor(), dpi=150)
    buf.seek(0)
    plt.close(fig)
    return buf.read()


def _save_fig(fig, path: str):
    fig.savefig(path, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor(), dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 1: Current Standings Bar Chart
# ---------------------------------------------------------------------------

def chart_current_standings(team_scores: list[TeamScore], gender: Gender,
                              meet_name: str = "SEC Championships") -> bytes:
    """Horizontal bar chart of current actual scores, top 12 teams."""
    top = sorted(team_scores, key=lambda x: x.actual_points, reverse=True)[:12]
    top = list(reversed(top))  # bottom-to-top for horizontal bar

    teams = [ts.team for ts in top]
    points = [ts.actual_points for ts in top]
    color_map = _get_team_color_map([ts.team for ts in reversed(top)])
    colors = [color_map[t] for t in teams]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(teams, points, color=colors, height=0.65, zorder=3)

    # Value labels
    for bar, pts in zip(bars, points):
        if pts > 0:
            ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                    f"{pts:.0f}", va="center", ha="left",
                    color=TEXT_PRIMARY, fontsize=10, fontweight="bold")

    ax.set_xlabel("Points", color=TEXT_MUTED, fontsize=10)
    ax.set_title(
        f"{meet_name}\n{gender.value} — Current Standings",
        color=TEXT_PRIMARY, fontsize=13, fontweight="bold", pad=12
    )
    ax.set_xlim(0, max(points) * 1.15 if points else 10)
    _apply_dark_style(fig)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ---------------------------------------------------------------------------
# Chart 2: Projected Final Score (grouped: actual + projection + ceiling)
# ---------------------------------------------------------------------------

def chart_projected_scores(team_scores: list[TeamScore], gender: Gender,
                             meet_name: str = "SEC Championships") -> bytes:
    """
    Grouped bar chart showing actual / seed projection / optimistic ceiling
    for top 8 teams by projection.
    """
    top = sorted(team_scores, key=lambda x: x.seed_projection, reverse=True)[:8]
    teams = [ts.team for ts in top]
    actual = [ts.actual_points for ts in top]
    proj = [ts.seed_projection for ts in top]
    ceil = [ts.optimistic_ceiling for ts in top]

    x = np.arange(len(teams))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 6))

    b1 = ax.bar(x - width, actual, width, label="Current Score",
                color=ACCENT_BLUE, alpha=0.9, zorder=3)
    b2 = ax.bar(x, proj, width, label="Seed Projection",
                color=ACCENT_GOLD, alpha=0.9, zorder=3)
    b3 = ax.bar(x + width, ceil, width, label="Optimistic Ceiling",
                color=ACCENT_GREEN, alpha=0.6, zorder=3, hatch="//")

    ax.set_xticks(x)
    ax.set_xticklabels(teams, rotation=20, ha="right", fontsize=9, color=TEXT_PRIMARY)
    ax.set_ylabel("Points", color=TEXT_MUTED)
    ax.set_title(
        f"{meet_name}\n{gender.value} — Projected Final Scores",
        color=TEXT_PRIMARY, fontsize=13, fontweight="bold", pad=12
    )
    ax.legend(facecolor=PANEL_BG, labelcolor=TEXT_PRIMARY, fontsize=9,
              edgecolor=GRID_COLOR)

    _apply_dark_style(fig)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ---------------------------------------------------------------------------
# Chart 3: Win Probability Donut/Bar
# ---------------------------------------------------------------------------

def chart_win_probability(team_scores: list[TeamScore], gender: Gender,
                           meet_name: str = "SEC Championships") -> bytes:
    """
    Horizontal bar chart of win probability % for teams with >1% chance.
    """
    contenders = [ts for ts in team_scores if ts.win_probability >= 1.0]
    contenders.sort(key=lambda x: x.win_probability, reverse=True)
    contenders = contenders[:10]

    if not contenders:
        # Nothing meaningful to show
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "Insufficient data for win probability",
                ha="center", va="center", color=TEXT_MUTED, fontsize=12)
        _apply_dark_style(fig)
        return _fig_to_bytes(fig)

    contenders_rev = list(reversed(contenders))
    teams = [ts.team for ts in contenders_rev]
    probs = [ts.win_probability for ts in contenders_rev]
    color_map = _get_team_color_map([ts.team for ts in contenders])
    colors = [color_map[t] for t in teams]

    fig, ax = plt.subplots(figsize=(10, max(4, len(teams) * 0.7)))
    bars = ax.barh(teams, probs, color=colors, height=0.6, zorder=3)

    for bar, pct in zip(bars, probs):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", ha="left",
                color=TEXT_PRIMARY, fontsize=10, fontweight="bold")

    ax.set_xlabel("Win Probability (%)", color=TEXT_MUTED)
    ax.set_xlim(0, max(probs) * 1.2 if probs else 100)
    ax.set_title(
        f"{meet_name}\n{gender.value} — Championship Win Probability",
        color=TEXT_PRIMARY, fontsize=13, fontweight="bold", pad=12
    )
    _apply_dark_style(fig)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ---------------------------------------------------------------------------
# Chart 4: Leverage Index
# ---------------------------------------------------------------------------

def chart_leverage_index(leverage_data: list[dict], gender: Gender,
                          meet_name: str = "SEC Championships") -> bytes:
    """
    Horizontal bar chart of top leverage events, colored by total points available.
    """
    if not leverage_data:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No remaining events to analyze",
                ha="center", va="center", color=TEXT_MUTED, fontsize=12)
        _apply_dark_style(fig)
        return _fig_to_bytes(fig)

    top = leverage_data[:8]
    top_rev = list(reversed(top))

    event_names = [d["event_name"].replace("Women ", "W ").replace("Men ", "M ")
                   for d in top_rev]
    scores = [d["leverage_score"] for d in top_rev]
    pts_available = [d["total_pts_available"] for d in top_rev]

    # Color by points available
    norm_pts = np.array(pts_available, dtype=float)
    if norm_pts.max() > 0:
        norm_pts = norm_pts / norm_pts.max()
    cmap = plt.cm.YlOrRd
    bar_colors = [cmap(p * 0.7 + 0.2) for p in norm_pts]

    fig, ax = plt.subplots(figsize=(11, max(4, len(top) * 0.8)))
    bars = ax.barh(event_names, scores, color=bar_colors, height=0.6, zorder=3)

    for bar, d in zip(bars, reversed(top)):
        label = f"{d['total_pts_available']} pts"
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                label, va="center", ha="left", color=TEXT_MUTED, fontsize=8)

    ax.set_xlabel("Leverage Score", color=TEXT_MUTED)
    ax.set_title(
        f"{meet_name}\n{gender.value} — 🔥 High-Leverage Remaining Events",
        color=TEXT_PRIMARY, fontsize=13, fontweight="bold", pad=12
    )

    # Subtitle annotation
    ax.annotate(
        "Higher score = more impact on final standings",
        xy=(0.5, -0.08), xycoords="axes fraction",
        ha="center", color=TEXT_MUTED, fontsize=8
    )

    _apply_dark_style(fig)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ---------------------------------------------------------------------------
# Chart 5: Scenario Builder for one team
# ---------------------------------------------------------------------------

def chart_team_scenarios(scenario: dict, meet_name: str = "SEC Championships") -> bytes:
    """
    Waterfall-style grouped bar for one team: current / worst / seeds hold / best case.
    """
    team = scenario["team"]
    current = scenario["current"]
    worst = scenario["scenario_c"]
    seeds = scenario["scenario_a"]
    best = scenario["scenario_b"]

    categories = ["Current\nScore", "Worst\nCase", "Seeds\nHold", "Best\nCase"]
    values = [current, worst, seeds, best]
    colors = [ACCENT_BLUE, ACCENT_RED, ACCENT_GOLD, ACCENT_GREEN]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(categories, values, color=colors, width=0.5, zorder=3)

    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{val:.0f}", ha="center", va="bottom",
                color=TEXT_PRIMARY, fontsize=12, fontweight="bold")

    ax.set_ylabel("Total Points", color=TEXT_MUTED)
    ax.set_title(
        f"{meet_name}\n{team} — Score Scenarios",
        color=TEXT_PRIMARY, fontsize=13, fontweight="bold", pad=12
    )
    ax.set_ylim(0, max(values) * 1.15 if values else 10)
    _apply_dark_style(fig)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ---------------------------------------------------------------------------
# Social media bundle: 4 charts saved to disk
# ---------------------------------------------------------------------------

def generate_social_bundle(
    women_analysis: dict,
    men_analysis: dict,
    output_dir: str = ".",
    meet_name: str = "SEC Championships"
) -> list[str]:
    """
    Generate 4 PNG files for social media posting.
    Returns list of file paths.
    """
    import os
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    for analysis, gender_label in [(women_analysis, "W"), (men_analysis, "M")]:
        ts = analysis["team_scores"]
        lev = analysis["leverage_index"]
        gname = analysis["gender"].value
        mn = meet_name

        # Standings
        p = os.path.join(output_dir, f"standings_{gender_label}.png")
        fig, ax = plt.subplots(figsize=(10, 6))
        data = _fig_to_bytes  # reuse helper
        img_bytes = chart_current_standings(ts, analysis["gender"], mn)
        with open(p, "wb") as f:
            f.write(img_bytes)
        paths.append(p)

        # Projections
        p = os.path.join(output_dir, f"projections_{gender_label}.png")
        img_bytes = chart_projected_scores(ts, analysis["gender"], mn)
        with open(p, "wb") as f:
            f.write(img_bytes)
        paths.append(p)

        # Win probability
        p = os.path.join(output_dir, f"winprob_{gender_label}.png")
        img_bytes = chart_win_probability(ts, analysis["gender"], mn)
        with open(p, "wb") as f:
            f.write(img_bytes)
        paths.append(p)

        # Leverage
        p = os.path.join(output_dir, f"leverage_{gender_label}.png")
        img_bytes = chart_leverage_index(lev, analysis["gender"], mn)
        with open(p, "wb") as f:
            f.write(img_bytes)
        paths.append(p)

    return paths
