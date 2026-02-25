"""
config.py - Central configuration for SEC Track Tracker
Reads meet URL from CLI argument or environment variable.
All credentials come from environment / Streamlit secrets - never hardcoded.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Meet URL
# ---------------------------------------------------------------------------
def get_meet_url() -> str:
    """
    Priority:
    1. Command-line argument:  python run.py https://flashresults.com/...
    2. Environment variable:   MEET_URL=https://...
    3. Fallback to SEC 2026 for development
    """
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        return sys.argv[1].rstrip("/")
    env = os.environ.get("MEET_URL", "")
    if env:
        return env.rstrip("/")
    return "https://flashresults.com/2026_Meets/Indoor/02-26_SEC"

# ---------------------------------------------------------------------------
# Email settings  (populated from Streamlit secrets or env vars)
# ---------------------------------------------------------------------------
def get_email_config() -> dict:
    """
    Reads Gmail credentials from Streamlit secrets (preferred when deployed)
    or from environment variables (local dev).

    Streamlit secrets.toml format:
        [email]
        sender   = "youremail@gmail.com"
        password = "your_app_password"
        recipient = "coachjonhughes@gmail.com"
    """
    try:
        import streamlit as st
        cfg = st.secrets.get("email", {})
        if cfg:
            return {
                "sender":    cfg.get("sender", ""),
                "password":  cfg.get("password", ""),
                "recipient": cfg.get("recipient", "coachjonhughes@gmail.com"),
            }
    except Exception:
        pass

    return {
        "sender":    os.environ.get("EMAIL_SENDER", ""),
        "password":  os.environ.get("EMAIL_PASSWORD", ""),
        "recipient": os.environ.get("EMAIL_RECIPIENT", "coachjonhughes@gmail.com"),
    }

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------
PLACE_POINTS = {1: 10, 2: 8, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}

# Sprint events where we use the PRELIM time as the seed into the final
SPRINT_EVENTS_USE_PRELIM = {"60m", "200m", "400m", "60m hurdles"}

# Refresh interval in seconds for Streamlit auto-rerun
REFRESH_INTERVAL_SECONDS = 300  # 5 minutes

# Monte Carlo iterations for win probability
MONTE_CARLO_ITERATIONS = 10_000

# ---------------------------------------------------------------------------
# Event code → human-readable name mapping (built from index parsing,
# but we define known SEC codes here as a fallback reference)
# ---------------------------------------------------------------------------
COMBINED_EVENT_PREFIXES = {"017", "037"}  # Pentathlon, Heptathlon
