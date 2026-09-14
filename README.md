# 💬 WhatsApp Bulk Sender

Send personalised WhatsApp messages to hundreds of contacts by importing a simple CSV file — no coding required.

Built with Streamlit + Selenium. Runs entirely on your local machine using your own WhatsApp account.

---

## Features

- **Quick Send** — import a CSV and send to everyone in one click
- **Scheduled Sending** — spread messages across multiple days to avoid bans
- **Warm-up Mode** — gradually ramps up volume (50% → 65% → 80% → 100%) to protect new accounts
- **Personalisation** — use `{name}` in your message to greet each contact by name
- **Per-contact messages** — optionally override the message for individual contacts in the CSV
- **Anti-block delays** — random delays between messages, configurable micro-batch pauses
- **Live progress** — real-time send/fail counter and message log
- **History tab** — track all past batches with downloadable CSV reports

---

## Requirements

- Mac (tested on macOS)
- Python 3.8+
- Google Chrome installed
- An active WhatsApp account

---

## Quick Start (no coding needed)

1. Click the green **Code** button on this page → **Download ZIP**
2. Unzip the downloaded file (double-click it)
3. Open **Terminal** — press `Cmd + Space`, type `Terminal`, press Enter
4. Type `bash ` (with a space), then drag the `run.command` file from Finder into the Terminal window, then press **Enter**

Terminal will install all dependencies and open the app in your browser automatically.

> **Why not just double-click?** macOS removes execute permissions from files downloaded as a ZIP. Running via `bash` bypasses this. After the first run you can double-click normally.
>
> **If Mac still blocks it:** right-click `run.command` → **Open** → **Open**

---

## Manual Start (for developers)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501)

---

## How to Use

### Step 1 — Launch WhatsApp Web
Click **Launch WhatsApp Web** in the sidebar. A Chrome window opens — scan the QR code with your phone. You only need to do this once (your session is saved).

### Step 2 — Prepare your CSV

Your CSV needs at minimum a `phone` column. Add a `name` column for personalisation.

| name | phone | message |
|------|-------|---------|
| Alice | +919876543210 | _(optional per-contact override)_ |
| Bob | +14155551234 | |

Phone numbers can include or omit the `+` prefix — the app cleans them automatically.

Download a sample CSV from inside the app.

### Step 3 — Write your message

Use `{name}` anywhere in your message to insert the contact's name:

```
Hi {name}! 👋

We have an exciting update for you. Reply to learn more!
```

### Step 4 — Send

**Quick Send tab** → upload CSV → write message → tick confirmation → click **Send**

For large lists, use the **Schedule tab** to spread sending across multiple days.

---

## Daily Sending Limits

| Account Type | Recommended / day |
|---|---|
| Personal (new account) | 50 – 80 |
| Personal (established) | 150 – 200 |
| WhatsApp Business | 200 – 250 |
| Business API | 1,000+ |

Exceeding these limits risks a temporary or permanent account ban.

---

## How It Works

The app uses **Selenium** to automate WhatsApp Web in a Chrome window on your computer. It opens each chat via the `web.whatsapp.com/send?phone=...` URL, waits for the message box to load, and hits Enter to send.

Because it runs through your own browser and account, no API keys or third-party services are needed.

---

## Important Notes

- This tool is for **personal/business outreach** — do not use it for spam
- WhatsApp may flag accounts that send too many messages too quickly
- The app **cannot be deployed to the cloud** (Vercel, Railway, etc.) — it must run locally since it controls your browser
- Your WhatsApp session is stored in `wa_chrome_profile/` — do not share this folder

---

## Project Structure

```
.
├── app.py                # Main Streamlit application
├── requirements.txt      # Python dependencies
├── run.command           # Double-click launcher for Mac
├── sample_contacts.csv   # Example CSV file
└── wa_chrome_profile/    # Chrome session (auto-created, gitignored)
```
