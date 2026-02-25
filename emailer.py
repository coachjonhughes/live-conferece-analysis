"""
emailer.py - Send graphics via Gmail SMTP after each new final result.
Falls back to attaching a text summary if images exceed Gmail's 25MB limit.
"""

import os
import io
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Optional

from config import get_email_config

logger = logging.getLogger(__name__)

MAX_ATTACH_BYTES = 20 * 1024 * 1024   # 20MB safety limit before warning


def send_update_email(
    new_event_names: list[str],
    women_analysis: dict,
    men_analysis: dict,
    chart_bytes: dict[str, bytes],   # key: description, value: PNG bytes
    meet_name: str = "SEC Championships"
):
    """
    Send an email with meet update after new finals post.

    chart_bytes keys should be descriptive, e.g.:
        "Women Standings", "Men Win Probability", etc.
    """
    cfg = get_email_config()
    if not cfg["sender"] or not cfg["password"]:
        logger.warning("Email credentials not configured — skipping email send.")
        return

    try:
        subject = _build_subject(new_event_names, meet_name)
        html_body = _build_html_body(new_event_names, women_analysis, men_analysis, meet_name)

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = cfg["recipient"]

        # HTML alternative
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(html_body, "html"))
        msg.attach(alt)

        # Attach images
        total_size = sum(len(b) for b in chart_bytes.values())
        if total_size > MAX_ATTACH_BYTES:
            logger.warning(
                f"Charts total {total_size / 1e6:.1f}MB — over limit. "
                "Attaching compressed versions only."
            )

        for label, img_bytes in chart_bytes.items():
            if not img_bytes:
                continue
            image = MIMEImage(img_bytes, name=f"{label.replace(' ', '_')}.png")
            image.add_header("Content-Disposition", "attachment",
                             filename=f"{label.replace(' ', '_')}.png")
            msg.attach(image)

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(cfg["sender"], cfg["password"])
            smtp.sendmail(cfg["sender"], cfg["recipient"], msg.as_string())

        logger.info(f"Email sent: {subject}")

    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def _build_subject(new_events: list[str], meet_name: str) -> str:
    ts = datetime.now().strftime("%I:%M %p")
    if len(new_events) == 1:
        return f"📊 {meet_name} Update — {new_events[0]} Final Posted ({ts})"
    elif len(new_events) <= 3:
        return f"📊 {meet_name} Update — {', '.join(new_events)} ({ts})"
    else:
        return f"📊 {meet_name} Update — {len(new_events)} new finals posted ({ts})"


def _build_html_body(
    new_events: list[str],
    women_analysis: dict,
    men_analysis: dict,
    meet_name: str
) -> str:
    """Generate a clean HTML email body with top standings summary."""

    def standings_table(analysis: dict, gender_label: str) -> str:
        ts_list = analysis.get("team_scores", [])
        if not ts_list:
            return "<p>No data available yet.</p>"

        rows = ""
        for i, ts in enumerate(ts_list[:8]):
            rank_emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"][i]
            rows += f"""
            <tr style="background:{'#1c2128' if i % 2 == 0 else '#161b22'}">
                <td style="padding:6px 10px;color:#e6edf3;">{rank_emoji}</td>
                <td style="padding:6px 10px;color:#e6edf3;font-weight:bold;">{ts.team}</td>
                <td style="padding:6px 10px;color:#f0c040;text-align:right;">{ts.actual_points}</td>
                <td style="padding:6px 10px;color:#58a6ff;text-align:right;">{ts.seed_projection}</td>
                <td style="padding:6px 10px;color:#3fb950;text-align:right;">{ts.win_probability:.1f}%</td>
            </tr>"""

        return f"""
        <h3 style="color:#f0c040;margin-top:20px;">{gender_label} Top 8</h3>
        <table style="border-collapse:collapse;width:100%;max-width:500px;">
            <thead>
                <tr style="background:#21262d;">
                    <th style="padding:6px 10px;color:#8b949e;text-align:left;">#</th>
                    <th style="padding:6px 10px;color:#8b949e;text-align:left;">Team</th>
                    <th style="padding:6px 10px;color:#8b949e;text-align:right;">Actual</th>
                    <th style="padding:6px 10px;color:#8b949e;text-align:right;">Projected</th>
                    <th style="padding:6px 10px;color:#8b949e;text-align:right;">Win %</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>"""

    new_events_html = "".join(f"<li style='color:#e6edf3;'>{e}</li>" for e in new_events)

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="background:#0d1117;font-family:Arial,sans-serif;padding:20px;">
        <div style="max-width:600px;margin:0 auto;">
            <h2 style="color:#f0c040;border-bottom:1px solid #21262d;padding-bottom:10px;">
                📊 {meet_name} — Live Update
            </h2>
            <p style="color:#8b949e;font-size:12px;">
                Updated: {datetime.now().strftime('%A, %B %d at %I:%M %p')}
            </p>

            <h3 style="color:#e6edf3;">New Finals Posted:</h3>
            <ul>{new_events_html}</ul>

            {standings_table(women_analysis, "🚺 Women's")}
            {standings_table(men_analysis, "🚹 Men's")}

            <p style="color:#8b949e;font-size:11px;margin-top:20px;border-top:1px solid #21262d;padding-top:10px;">
                Charts attached as PNG files. Live dashboard updating automatically.
                <br>Projected scores based on seed marks. Win % from Monte Carlo simulation (10,000 iterations).
            </p>
        </div>
    </body>
    </html>
    """


def detect_new_finals(
    current_state,
    previous_finals: set[str]
) -> tuple[list[str], set[str]]:
    """
    Compare current finalized events against previously known finals.
    Returns (list of new event names, updated set of all known finals).
    """
    from data_model import EventStatus, RoundType

    current_finals = {
        event.event_name
        for event in current_state.events
        if event.status == EventStatus.FINAL and event.round_type == RoundType.FINAL
    }

    # Also include completed combined events
    for combined in current_state.combined_events:
        if combined.is_complete:
            current_finals.add(combined.event_name)

    new_finals = sorted(current_finals - previous_finals)
    return new_finals, current_finals
