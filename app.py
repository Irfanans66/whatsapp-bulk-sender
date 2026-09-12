
import streamlit as st
import pandas as pd
import time
import random
import urllib.parse
import json
from pathlib import Path
from datetime import date, timedelta, datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# ── Constants ─────────────────────────────────────────────────────────────────
SCHEDULE_FILE = Path("wa_schedule.json")
STOP_FILE     = Path("wa_stop.flag")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="WhatsApp Bulk Sender",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .header-title { color:#25D366; font-size:2rem; font-weight:800; margin-bottom:0; }
    .header-sub   { color:#666; font-size:0.9rem; margin-top:2px; }
    div[data-testid="metric-container"] {
        background:white; border-radius:10px; padding:12px; border:1px solid #e0e0e0;
    }
    .batch-today  { background:#25D366; color:white; padding:2px 10px;
                    border-radius:12px; font-size:0.78rem; font-weight:600; }
    .batch-done   { background:#aaa;    color:white; padding:2px 10px;
                    border-radius:12px; font-size:0.78rem; }
    .batch-future { background:#f0ad4e; color:white; padding:2px 10px;
                    border-radius:12px; font-size:0.78rem; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {"driver": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Schedule I/O ──────────────────────────────────────────────────────────────

def load_schedule() -> Optional[dict]:
    if SCHEDULE_FILE.exists():
        return json.loads(SCHEDULE_FILE.read_text())
    return None

def save_schedule(data: dict):
    SCHEDULE_FILE.write_text(json.dumps(data, indent=2, default=str))

def build_schedule(contacts: list, msgs_per_day: int, start: date,
                   template: str, warmup: bool) -> dict:
    # Warm-up ramp: 50 % → 65 % → 80 % → 100 % from day 4 onward
    ramp = [0.50, 0.65, 0.80]

    batches, i, day = [], 0, 0
    while i < len(contacts):
        factor = ramp[day] if (warmup and day < len(ramp)) else 1.0
        limit  = max(10, int(msgs_per_day * factor))
        batches.append({
            "batch_num": day + 1,
            "date":      str(start + timedelta(days=day)),
            "contacts":  contacts[i : i + limit],
            "status":    "pending",   # pending | in_progress | completed | skipped
            "sent":      0,
            "failed":    0,
            "sent_at":   None,
            "log":       [],
        })
        i   += limit
        day += 1

    return {
        "created_at":  str(datetime.now()),
        "msgs_per_day": msgs_per_day,
        "warmup":       warmup,
        "template":     template,
        "total":        len(contacts),
        "total_days":   len(batches),
        "batches":      batches,
    }

def today_batch(schedule: dict) -> Optional[dict]:
    today = str(date.today())
    for b in schedule["batches"]:
        if b["date"] == today and b["status"] in ("pending", "in_progress"):
            return b
    return None

def next_pending_batch(schedule: dict) -> Optional[dict]:
    """First pending batch after today (for the 'Next batch' info card)."""
    today = date.today()
    for b in schedule["batches"]:
        if b["status"] == "pending" and date.fromisoformat(b["date"]) > today:
            return b
    return None

# ── Selenium helpers ──────────────────────────────────────────────────────────

def clean_phone(p: str) -> str:
    return str(p).strip().replace("+","").replace(" ","").replace("-","") \
                         .replace("(","").replace(")","")

def init_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--user-data-dir=./wa_chrome_profile")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    drv = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts
    )
    drv.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    return drv

def wa_send(driver, phone: str, text: str, timeout: int = 60) -> tuple[bool, str]:
    try:
        num = clean_phone(phone)
        if not num:
            return False, "Empty number"
        url = (
            f"https://web.whatsapp.com/send"
            f"?phone={num}&text={urllib.parse.quote(text)}&app_absent=0"
        )
        driver.get(url)
        wait = WebDriverWait(driver, timeout)
        # Detect "not on WhatsApp" popup
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[contains(@class,"popup-contents")]')
                )
            )
            return False, "Not on WhatsApp"
        except Exception:
            pass
        inp = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//footer//div[@contenteditable="true"]')
            )
        )
        time.sleep(1.5)
        inp.send_keys(Keys.ENTER)
        time.sleep(2.5)
        return True, "Sent"
    except Exception as e:
        return False, str(e)[:100]

# ── Core send loop ────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_preview_html(contacts: list, template: str, max_bubbles: int = 5) -> str:
    """Render up to max_bubbles WhatsApp-style chat bubbles as HTML."""
    bubbles = ""
    for row in contacts[:max_bubbles]:
        name   = str(row.get("name",  "")).strip()
        phone  = str(row.get("phone", "")).strip()
        custom = str(row.get("message", "")).strip()
        raw    = custom if custom else template
        try:    msg = raw.format(name=name)
        except KeyError: msg = raw

        name_h  = _esc(name)
        phone_h = _esc(phone)
        msg_h   = _esc(msg).replace("\n", "<br>")
        bubbles += f"""
        <div style="display:flex;flex-direction:column;align-items:flex-end;">
          <div style="font-size:0.72rem;color:#555;margin-bottom:3px;margin-right:4px;">
            <b>{name_h}</b> &nbsp;·&nbsp; {phone_h}
          </div>
          <div style="background:#dcf8c6;border-radius:8px 0 8px 8px;padding:10px 15px;
                      max-width:78%;font-size:0.88rem;line-height:1.55;
                      box-shadow:0 1px 3px rgba(0,0,0,0.12);">
            {msg_h}
            <div style="font-size:0.68rem;color:#9aaa97;text-align:right;margin-top:5px;">✓✓</div>
          </div>
        </div>"""

    return (
        '<div style="background:#e5ddd5;border-radius:12px;padding:18px 20px;'
        'display:flex;flex-direction:column;gap:16px;">'
        + bubbles
        + "</div>"
    )


def run_batch(driver, schedule: dict, batch_idx: int,
              min_d: float, max_d: float,
              msg_batch_sz: int, msg_batch_pause: float, use_msg_batches: bool):
    """
    Send every contact in schedule['batches'][batch_idx].
    Persists progress to SCHEDULE_FILE after every message.
    Returns (sent, failed).
    """
    batch    = schedule["batches"][batch_idx]
    contacts = batch["contacts"]
    template = schedule["template"]
    total    = len(contacts)

    batch["status"] = "in_progress"
    save_schedule(schedule)

    prog  = st.progress(0, text="Starting…")
    stat  = st.empty()
    table = st.empty()
    sent = failed = 0

    for i, row in enumerate(contacts):
        if STOP_FILE.exists():
            st.warning(f"Stopped at message {i + 1}.")
            STOP_FILE.unlink()
            break

        name   = str(row.get("name",  "")).strip()
        phone  = str(row.get("phone", "")).strip()
        custom = str(row.get("message", "")).strip()
        raw    = custom if custom else template
        try:
            msg = raw.format(name=name)
        except KeyError:
            msg = raw

        ok, note = wa_send(driver, phone, msg)
        sent   += int(ok)
        failed += int(not ok)

        log_row = {
            "#":      i + 1,
            "Name":   name,
            "Phone":  phone,
            "Status": "✅ Sent" if ok else "❌ Failed",
            "Note":   "" if ok else note,
        }
        batch["log"].append(log_row)
        batch["sent"]   = sent
        batch["failed"] = failed
        save_schedule(schedule)

        pct = (i + 1) / total
        prog.progress(pct, text=f"{'✅' if ok else '❌'} {name} ({phone}) — {i+1}/{total}")
        stat.markdown(
            f"**Sent:** {sent} &nbsp;|&nbsp; **Failed:** {failed} "
            f"&nbsp;|&nbsp; **Remaining:** {total - i - 1}"
        )
        table.dataframe(pd.DataFrame(batch["log"]).tail(12), use_container_width=True)

        if i < total - 1:
            if use_msg_batches and msg_batch_sz > 0 and (i + 1) % msg_batch_sz == 0:
                for s in range(int(msg_batch_pause), 0, -1):
                    prog.progress(pct, text=f"Batch pause — resuming in {s}s…")
                    time.sleep(1)
            else:
                time.sleep(random.uniform(min_d, max_d))

    batch["status"]  = "completed"
    batch["sent_at"] = str(datetime.now())
    save_schedule(schedule)
    return sent, failed

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    st.markdown("### Anti-Block Delays")
    min_delay = st.slider("Min delay per msg (sec)", 3, 20, 5)
    max_delay = st.slider("Max delay per msg (sec)", min_delay, 90, 15)

    st.markdown("### Message Batch Pauses")
    use_msg_batches = st.checkbox("Enable micro-batch pauses", value=True)
    msg_batch_sz    = st.number_input("Messages per micro-batch", 5, 100, 30,
                                       disabled=not use_msg_batches)
    msg_batch_pause = st.slider("Micro-batch pause (sec)", 30, 600, 120,
                                 disabled=not use_msg_batches)

    st.markdown("### WhatsApp Session")
    if st.session_state.driver is None:
        if st.button("Launch WhatsApp Web", use_container_width=True, type="primary"):
            with st.spinner("Starting Chrome…"):
                try:
                    drv = init_driver()
                    drv.get("https://web.whatsapp.com")
                    st.session_state.driver = drv
                    st.rerun()
                except Exception as e:
                    st.error(f"Chrome error: {e}")
    else:
        st.success("Chrome is running")
        st.info("Scan QR code in Chrome if prompted.")
        if st.button("Close Browser", use_container_width=True):
            try: st.session_state.driver.quit()
            except Exception: pass
            st.session_state.driver = None
            st.rerun()

    st.divider()
    st.markdown("### Daily Limits Guide")
    st.markdown("""
| Account        | Safe/day |
|----------------|----------|
| Personal (new) | 50–80    |
| Personal (old) | 150–200  |
| WA Business    | 200–250  |
| Business API   | 1 000+   |
    """)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<p class="header-title">💬 WhatsApp Bulk Sender</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="header-sub">Import contacts · build a daily schedule · send safely without getting blocked.</p>',
    unsafe_allow_html=True,
)
st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_quick, tab_setup, tab_schedule, tab_send, tab_history = st.tabs(
    ["⚡  Quick Send", "📋  Setup", "📅  Schedule", "🚀  Send Today", "📊  History"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 0 – QUICK SEND
# ═══════════════════════════════════════════════════════════════════════════════
with tab_quick:
    st.subheader("Quick Send — Import CSV & Send Now")
    st.caption("No scheduling needed. Upload your contacts, write your message, and send in one click.")

    if st.session_state.driver is None:
        st.warning("Click **Launch WhatsApp Web** in the sidebar first and scan the QR code.")

    col_q1, col_q2 = st.columns([3, 1])
    with col_q1:
        q_uploaded = st.file_uploader(
            "CSV must have a **phone** column. Optional: **name** (for personalisation).",
            type=["csv"],
            key="quick_csv",
        )
    with col_q2:
        q_sample = pd.DataFrame({
            "name":  ["Alice", "Bob"],
            "phone": ["+919876543210", "+14155551234"],
        })
        st.markdown("&nbsp;")
        st.download_button(
            "Sample CSV",
            q_sample.to_csv(index=False),
            "quick_sample.csv",
            mime="text/csv",
            use_container_width=True,
        )

    q_contacts = []
    if q_uploaded:
        try:
            q_df = pd.read_csv(q_uploaded, dtype=str).fillna("")
            q_df.columns = [c.strip().lower() for c in q_df.columns]
            if "phone" not in q_df.columns:
                st.error("CSV must have a **phone** column.")
            else:
                if "name" not in q_df.columns:
                    q_df["name"] = ""
                q_contacts = q_df[["name", "phone"]].to_dict("records")
                st.success(f"Loaded **{len(q_contacts):,}** contacts.")
                with st.expander("Preview contacts"):
                    st.dataframe(q_df.head(20), use_container_width=True)
        except Exception as ex:
            st.error(f"Could not read CSV: {ex}")

    q_col1, q_col2 = st.columns(2)
    with q_col1:
        q_template = st.text_area(
            "Message — use `{name}` to personalise",
            value="Hi {name}! 👋\n\nJust reaching out — reply to learn more.",
            height=160,
            key="quick_template",
        )
    with q_col2:
        q_prev_name = st.text_input("Preview name", "Alex", key="quick_prev_name")
        st.markdown("**Live preview:**")
        try:
            st.info(q_template.format(name=q_prev_name) or "_empty_")
        except KeyError as ke:
            st.warning(f"Unknown placeholder: `{{{ke.args[0]}}}`")

    if q_contacts:
        st.markdown(
            build_preview_html(q_contacts, q_template, max_bubbles=3),
            unsafe_allow_html=True,
        )

    st.divider()
    q_confirmed = st.checkbox(
        "I've reviewed the messages and I'm ready to send",
        key="quick_confirm",
    )

    q_col_s, q_col_x = st.columns([3, 1])
    with q_col_s:
        q_send_btn = st.button(
            f"Send to {len(q_contacts):,} contacts" if q_contacts else "Send",
            type="primary",
            use_container_width=True,
            disabled=(not q_contacts or not q_confirmed or st.session_state.driver is None),
            key="quick_send_btn",
        )
    with q_col_x:
        if st.button("Stop", use_container_width=True, key="quick_stop_btn"):
            STOP_FILE.touch()
            st.warning("Stop requested.")

    if q_send_btn:
        if STOP_FILE.exists():
            STOP_FILE.unlink()

        total_q   = len(q_contacts)
        q_prog    = st.progress(0, text="Starting…")
        q_stat    = st.empty()
        q_table   = st.empty()
        q_log     = []
        q_sent = q_failed = 0

        for i, row in enumerate(q_contacts):
            if STOP_FILE.exists():
                st.warning(f"Stopped at message {i + 1}.")
                STOP_FILE.unlink()
                break

            name  = str(row.get("name", "")).strip()
            phone = str(row.get("phone", "")).strip()
            try:
                msg = q_template.format(name=name)
            except KeyError:
                msg = q_template

            ok, note = wa_send(st.session_state.driver, phone, msg)
            q_sent   += int(ok)
            q_failed += int(not ok)

            q_log.append({
                "#":      i + 1,
                "Name":   name,
                "Phone":  phone,
                "Status": "Sent" if ok else "Failed",
                "Note":   "" if ok else note,
            })

            pct = (i + 1) / total_q
            q_prog.progress(pct, text=f"{'OK' if ok else 'FAIL'} {name} ({phone}) — {i+1}/{total_q}")
            q_stat.markdown(
                f"**Sent:** {q_sent} &nbsp;|&nbsp; **Failed:** {q_failed} "
                f"&nbsp;|&nbsp; **Remaining:** {total_q - i - 1}"
            )
            q_table.dataframe(pd.DataFrame(q_log).tail(12), use_container_width=True)

            if i < total_q - 1:
                time.sleep(random.uniform(min_delay, max_delay))

        if q_failed == 0:
            st.balloons()
        st.success(f"Done — Sent: **{q_sent}** | Failed: **{q_failed}**")
        result_df = pd.DataFrame(q_log)
        st.dataframe(result_df, use_container_width=True)
        st.download_button(
            "Download Results CSV",
            result_df.to_csv(index=False),
            "quick_send_results.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – SETUP
# ═══════════════════════════════════════════════════════════════════════════════
with tab_setup:
    st.subheader("Upload Contacts")
    col_a, col_b = st.columns([3, 1])
    with col_a:
        uploaded = st.file_uploader(
            "CSV columns: **name**, **phone** — optional: **message** (per-contact override)",
            type=["csv"],
        )
    with col_b:
        sample = pd.DataFrame({
            "name":    ["Alice", "Bob", "Carol"],
            "phone":   ["+919876543210", "+14155551234", "+971501234567"],
            "message": ["", "", ""],
        })
        st.markdown("&nbsp;")
        st.download_button(
            "Download Sample CSV",
            sample.to_csv(index=False),
            "sample_contacts.csv",
            mime="text/csv",
            use_container_width=True,
        )

    df = None
    if uploaded:
        try:
            df = pd.read_csv(uploaded, dtype=str).fillna("")
            df.columns = [c.strip().lower() for c in df.columns]
            assert "name" in df.columns and "phone" in df.columns
            st.success(f"Loaded **{len(df):,}** contacts.")
            with st.expander("Preview (first 20 rows)"):
                st.dataframe(df.head(20), use_container_width=True)
            st.session_state["df"] = df.to_dict("records")
        except AssertionError:
            st.error("CSV must have **name** and **phone** columns.")
    elif "df" in st.session_state:
        st.info(f"Using previously uploaded contacts ({len(st.session_state['df']):,} rows).")

    st.divider()
    st.subheader("Message Template")
    col1, col2 = st.columns(2)
    with col1:
        template = st.text_area(
            "Use `{name}` for personalisation",
            value=st.session_state.get("template",
                "Hi {name}! 👋\n\nWe have an exciting update for you.\n\nReply to learn more!"),
            height=200,
        )
        st.session_state["template"] = template
    with col2:
        preview_name = st.text_input("Preview with name", "Alex")
        st.markdown("**Live preview:**")
        try:
            st.info(template.format(name=preview_name) or "_empty_")
        except KeyError as ke:
            st.warning(f"Unknown placeholder: `{{{ke.args[0]}}}`")

    st.divider()
    if "df" in st.session_state:
        st.success(f"✅  {len(st.session_state['df']):,} contacts loaded — go to **📅 Schedule** to build your daily plan.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 – SCHEDULE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_schedule:
    contacts = st.session_state.get("df", [])
    template = st.session_state.get("template", "")

    if not contacts:
        st.warning("Upload contacts in the **📋 Setup** tab first.")
    else:
        st.subheader("Build Daily Schedule")

        col1, col2, col3 = st.columns(3)
        with col1:
            msgs_per_day = st.number_input(
                "Max messages per day", min_value=10, max_value=1000,
                value=200, step=10,
            )
        with col2:
            start_date = st.date_input("Start date", value=date.today())
        with col3:
            warmup = st.toggle(
                "Warm-up mode",
                value=True,
                help="Day 1: 50 %, Day 2: 65 %, Day 3: 80 %, Day 4+: 100 % of daily limit",
            )

        total_days = -(-len(contacts) // msgs_per_day)  # ceiling division
        end_date   = start_date + timedelta(days=total_days - 1)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total Contacts", f"{len(contacts):,}")
        col_b.metric("Total Days",     total_days)
        col_c.metric("End Date",       str(end_date))

        if warmup:
            st.caption(
                "Warm-up ramp: Day 1 = "
                f"{max(10,int(msgs_per_day*0.50))} msgs · "
                f"Day 2 = {max(10,int(msgs_per_day*0.65))} · "
                f"Day 3 = {max(10,int(msgs_per_day*0.80))} · "
                f"Day 4+ = {msgs_per_day}"
            )

        if st.button("Create / Rebuild Schedule", type="primary", use_container_width=True):
            sched = build_schedule(contacts, msgs_per_day, start_date, template, warmup)
            save_schedule(sched)
            st.success(f"Schedule created — {sched['total_days']} days, {sched['total']:,} contacts.")
            st.rerun()

        # ── Show existing schedule ────────────────────────────────────────────
        sched = load_schedule()
        if sched:
            st.divider()
            st.subheader("Your Schedule")
            today_str = str(date.today())
            rows = []
            for b in sched["batches"]:
                if   b["date"] == today_str:            day_label = "🟢 Today"
                elif b["date"] <  today_str:            day_label = "✅ Done"
                elif b["status"] == "completed":        day_label = "✅ Done"
                else:                                   day_label = "⏳ Upcoming"

                rows.append({
                    "Day":      b["batch_num"],
                    "Date":     b["date"],
                    "Contacts": len(b["contacts"]),
                    "Status":   b["status"].capitalize(),
                    "Day Type": day_label,
                    "Sent":     b["sent"],
                    "Failed":   b["failed"],
                })

            sched_df = pd.DataFrame(rows)
            st.dataframe(sched_df, use_container_width=True, hide_index=True)

            # Download per-batch CSV
            st.markdown("**Download a specific day's contacts:**")
            day_opts = {
                f"Day {b['batch_num']} — {b['date']} ({len(b['contacts'])} contacts)": idx
                for idx, b in enumerate(sched["batches"])
            }
            chosen = st.selectbox("Select day", list(day_opts.keys()))
            if chosen:
                idx = day_opts[chosen]
                batch_df = pd.DataFrame(sched["batches"][idx]["contacts"])
                st.download_button(
                    f"Download Day {idx+1} CSV",
                    batch_df.to_csv(index=False),
                    file_name=f"batch_day{idx+1}.csv",
                    mime="text/csv",
                )

            st.divider()
            if st.button("Delete Schedule", use_container_width=True):
                SCHEDULE_FILE.unlink(missing_ok=True)
                st.info("Schedule deleted.")
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 – SEND TODAY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_send:
    sched = load_schedule()

    if sched is None:
        st.warning("No schedule found. Go to **📅 Schedule** and create one first.")
    elif st.session_state.driver is None:
        st.warning("Click **Launch WhatsApp Web** in the sidebar and scan the QR code.")
    else:
        tb = today_batch(sched)
        nb = next_pending_batch(sched)

        if tb is None:
            # Check if today's batch was already completed
            today_str = str(date.today())
            done_today = next(
                (b for b in sched["batches"] if b["date"] == today_str and b["status"] == "completed"),
                None,
            )
            if done_today:
                st.success(f"Today's batch is done — **{done_today['sent']}** sent, **{done_today['failed']}** failed.")
            else:
                st.info("No batch is scheduled for today.")

            if nb:
                st.markdown(f"**Next batch:** Day {nb['batch_num']} on **{nb['date']}** — {len(nb['contacts'])} contacts")
        else:
            batch_idx = sched["batches"].index(tb)

            # Info cards
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Today's Batch",  f"Day {tb['batch_num']}")
            c2.metric("Contacts",        len(tb["contacts"]))
            avg_d   = (min_delay + max_delay) / 2
            est_sec = len(tb["contacts"]) * avg_d
            if use_msg_batches and int(msg_batch_sz) > 0:
                est_sec += (len(tb["contacts"]) // int(msg_batch_sz)) * msg_batch_pause
            c3.metric("Est. Time",      f"~{est_sec/60:.0f} min")
            c4.metric("Date",            tb["date"])

            # Resumed from partial?
            already_sent = tb.get("sent", 0)
            if already_sent > 0:
                st.info(
                    f"Resuming — {already_sent} already sent in a previous run today. "
                    "Remaining contacts will be sent."
                )
                remaining = tb["contacts"][already_sent:]
            else:
                remaining = tb["contacts"]

            # ── Message Preview ───────────────────────────────────────────────
            st.divider()
            st.subheader("Message Preview")

            n_preview = min(5, len(remaining))
            st.caption(
                f"Showing {n_preview} of {len(remaining)} personalised messages "
                "— scroll down to preview all."
            )
            st.markdown(
                build_preview_html(remaining, sched["template"], max_bubbles=n_preview),
                unsafe_allow_html=True,
            )

            with st.expander(f"Preview all {len(remaining)} messages as table"):
                all_prev = []
                for row in remaining:
                    name   = str(row.get("name",  "")).strip()
                    phone  = str(row.get("phone", "")).strip()
                    custom = str(row.get("message", "")).strip()
                    raw    = custom if custom else sched["template"]
                    try:    msg = raw.format(name=name)
                    except KeyError: msg = raw
                    all_prev.append({"Name": name, "Phone": phone, "Message": msg})
                st.dataframe(pd.DataFrame(all_prev), use_container_width=True, hide_index=True)

            st.divider()
            confirmed = st.checkbox(
                "Messages look correct — I'm ready to send",
                help="Tick this after reviewing the preview above.",
            )

            col_s, col_x = st.columns([3, 1])
            with col_s:
                send_btn = st.button(
                    f"Send Today's Batch ({len(remaining)} messages)",
                    type="primary",
                    use_container_width=True,
                    disabled=(len(remaining) == 0 or not confirmed),
                )
            with col_x:
                if st.button("Stop", use_container_width=True):
                    STOP_FILE.touch()
                    st.warning("Stop requested.")

            if send_btn:
                if STOP_FILE.exists():
                    STOP_FILE.unlink()

                sent, failed = run_batch(
                    st.session_state.driver,
                    sched,
                    batch_idx,
                    min_delay, max_delay,
                    int(msg_batch_sz), msg_batch_pause,
                    use_msg_batches,
                )

                if failed == 0:
                    st.balloons()
                st.success(f"Done — Sent: **{sent}** | Failed: **{failed}**")

                if nb:
                    st.info(f"Next batch: Day {nb['batch_num']} on **{nb['date']}** ({len(nb['contacts'])} contacts)")

                log_df = pd.DataFrame(sched["batches"][batch_idx]["log"])
                st.dataframe(log_df, use_container_width=True)
                st.download_button(
                    "Download Today's Results CSV",
                    log_df.to_csv(index=False),
                    file_name=f"results_day{tb['batch_num']}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 – HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_history:
    sched = load_schedule()
    if sched is None:
        st.info("No schedule yet.")
    else:
        completed = [b for b in sched["batches"] if b["status"] == "completed"]

        if not completed:
            st.info("No batches completed yet.")
        else:
            total_sent   = sum(b["sent"]   for b in completed)
            total_failed = sum(b["failed"] for b in completed)
            total_days   = len(completed)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Days Completed",  total_days)
            c2.metric("Total Sent",      f"{total_sent:,}")
            c3.metric("Total Failed",    f"{total_failed:,}")
            pending_left = sum(
                len(b["contacts"]) for b in sched["batches"] if b["status"] == "pending"
            )
            c4.metric("Still Pending",   f"{pending_left:,}")

            st.divider()
            st.subheader("Completed Batches")
            summary = pd.DataFrame([{
                "Day":      b["batch_num"],
                "Date":     b["date"],
                "Sent":     b["sent"],
                "Failed":   b["failed"],
                "Total":    len(b["contacts"]),
                "Sent At":  b.get("sent_at",""),
            } for b in completed])
            st.dataframe(summary, use_container_width=True, hide_index=True)

            st.subheader("Full Message Log")
            all_logs = []
            for b in completed:
                for row in b.get("log", []):
                    all_logs.append({"Day": b["batch_num"], "Date": b["date"], **row})

            if all_logs:
                log_df = pd.DataFrame(all_logs)
                # Filter controls
                status_filter = st.multiselect(
                    "Filter by status",
                    ["✅ Sent", "❌ Failed"],
                    default=["✅ Sent", "❌ Failed"],
                )
                filtered = log_df[log_df["Status"].isin(status_filter)]
                st.dataframe(filtered, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download Full History CSV",
                    filtered.to_csv(index=False),
                    "wa_full_history.csv",
                    mime="text/csv",
                    use_container_width=True,
                )