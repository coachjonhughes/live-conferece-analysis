# 🏃 Track & Field Live Meet Tracker

Live scoring analysis for FlashResults meets. Built for SEC Indoor Championships but works
for any FlashResults meet by passing the URL as a command-line argument.

## Features

| Layer | Description |
|---|---|
| **Live Standings** | Real-time points from completed finals only |
| **Optimistic Ceiling** | Mathematical elimination check — can a team still win? |
| **Seed Projection** | Expected final score based on seed marks |
| **Leverage Index** | Which remaining events swing the meet most |
| **Win Probability** | Monte Carlo simulation (10,000 iterations) |
| **Scenario Builder** | Interactive what-if tool — pick any team |

Auto-emails updated charts after each new final result posts.

---

## Setup (one time)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up Gmail App Password
1. Go to **myaccount.google.com → Security → 2-Step Verification** and enable it
2. Go to **myaccount.google.com/apppasswords**
3. Create a new App Password named "Track Tracker"
4. Copy the 16-character password (no spaces)

### 3. Configure secrets
Edit `.streamlit/secrets.toml`:
```toml
[email]
sender    = "your_gmail@gmail.com"     # Gmail account sending the emails
password  = "abcd efgh ijkl mnop"      # 16-char app password from step above
recipient = "coachjonhughes@gmail.com"  # Where to send updates
```
⚠️ **Never commit secrets.toml to GitHub** — it's already in .gitignore

---

## Running Locally

```bash
# SEC Indoor 2026 (default)
streamlit run app.py

# Any other FlashResults meet — pass URL as argument
streamlit run app.py -- https://flashresults.com/2026_Meets/Indoor/02-28_BIG12/
```

The dashboard auto-refreshes every 5 minutes. Leave it running and go about your day.

---

## Deploying to Streamlit Cloud (public URL, free)

1. Push this repo to GitHub (secrets.toml is gitignored — it won't upload)
2. Go to **share.streamlit.io** → New app → select your repo → `app.py`
3. Under **Advanced settings → Secrets**, paste the contents of your secrets.toml
4. Click Deploy — you get a public URL like `yourname-sec-tracker.streamlit.app`
5. Share that URL. It stays live without your laptop.

**Note on Streamlit Cloud + meet URL:**
Add to your secrets.toml (or Streamlit Cloud secrets):
```toml
[meet]
url = "https://flashresults.com/2026_Meets/Indoor/02-26_SEC"
```
Or hardcode it temporarily in config.py's fallback URL.

---

## Social Media Workflow

The dashboard displays all charts live. For social posts:
1. Screenshot individual charts from the dashboard (they're sized for social)
2. Or use the **Refresh Now** button right before a big final to get latest data

Charts are also emailed to you automatically after each final — 8 PNGs per email
(4 charts × 2 genders): Standings, Projections, Win Probability, Leverage Index.

---

## Project Structure

```
sec_tracker/
├── app.py          Streamlit dashboard
├── scraper.py      FlashResults HTML parser (no browser needed)
├── scoring.py      All 5 analytical layers
├── graphics.py     Dark-themed matplotlib charts
├── emailer.py      Gmail SMTP with HTML email
├── config.py       Settings, constants, credential loading
├── data_model.py   Dataclasses for all meet entities
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── secrets.toml  ← credentials (never committed)
```

---

## Seeding Logic

| Event | Seed Used for Projection |
|---|---|
| 60m, 200m, 400m, 60m Hurdles | Athlete's **prelim result** (if prelims ran) |
| 800m, Mile, 3000m, 5000m, DMR | Athlete's **season best** from start list |
| Field events | Season best from start list |
| Relays | Team's seed mark from start list |
| Pentathlon / Heptathlon | Scored only when all events complete |

---

## Notes

- Only **finals** count toward team score (prelims ignored)
- Pent/Hep points only added after the final standings page shows complete results
- Win probability uses event-type-calibrated NCAA D1 assumptions
- The scraper is polite — 0.5s delay between requests
