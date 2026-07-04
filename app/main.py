"""PhD & Postdoc Supervisor Finder — NiceGUI desktop UI.

Run:  python -m app.main   (or the desktop shortcut created by the installer)
Everything runs locally; the browser window is just the UI."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import app as ng_app, run, ui

from app import db, llm
from app.config import (APP_DIR, KEY_NAMES, OUTPUT_DIR, get_setting, set_setting)
from app.logging_setup import log

db.init_db()

ACCENT = "#4f46e5"


# ---------------------------------------------------------------- helpers

def notify_ok(msg: str) -> None:
    ui.notify(msg, type="positive")


def notify_warn(msg: str) -> None:
    ui.notify(msg, type="warning", timeout=8000)


def profile_or_warn() -> dict | None:
    p = db.load_profile()
    if not p:
        notify_warn("No profile yet — upload your CV first (Upload CV page).")
    return p


# ---------------------------------------------------------------- sections

def dashboard() -> None:
    p = db.load_profile()
    stats = {
        "Positions": db.rows("SELECT COUNT(*) n FROM positions")[0]["n"],
        "Supervisors": db.rows("SELECT COUNT(*) n FROM supervisors")[0]["n"],
        "Matches": db.rows("SELECT COUNT(*) n FROM matches")[0]["n"],
        "Documents": db.rows("SELECT COUNT(*) n FROM documents")[0]["n"],
        "Emails sent": db.rows("SELECT COUNT(*) n FROM email_log WHERE status='sent'")[0]["n"],
        "Needs review": db.rows("SELECT COUNT(*) n FROM error_log WHERE needs_review=1 AND resolved=0")[0]["n"],
    }
    ui.label("Dashboard").classes("text-2xl font-bold")
    with ui.row().classes("gap-4 flex-wrap"):
        for name, n in stats.items():
            with ui.card().classes("w-40"):
                ui.label(str(n)).classes("text-3xl font-bold").style(f"color:{ACCENT}")
                ui.label(name).classes("text-sm text-gray-500")
    with ui.card().classes("w-full mt-4"):
        ui.label("Getting started").classes("text-lg font-semibold")
        steps = ["1. Upload your CV", "2. Check Research Interests",
                 "3. Search Positions and Supervisors", "4. Run Matching",
                 "5. Generate documents", "6. Review and send outreach emails"]
        for s in steps:
            ui.label(s)
        mode = "LLM assistance ON" if llm.available() else \
            "Limited mode (no LLM key) — parsing, search and keyword matching still work"
        ui.label(f"Mode: {mode}").classes("text-sm mt-2 text-gray-500")
    if p:
        ui.label(f"Profile loaded: {p.get('name') or 'unnamed'} ({p.get('email','')})") \
            .classes("mt-2 text-green-700")


def upload_cv() -> None:
    ui.label("Upload CV").classes("text-2xl font-bold")
    ui.label("PDF or DOCX. Extraction is heuristic — always review the result below.")
    result_area = ui.column().classes("w-full")

    async def handle_upload(e) -> None:
        tmp = APP_DIR / "uploads"
        tmp.mkdir(exist_ok=True)
        dest = tmp / e.name
        dest.write_bytes(e.content.read())
        from app.cv_parser import parse_cv
        try:
            profile, warnings = await run.io_bound(parse_cv, dest)
        except Exception as ex:
            notify_warn(f"Could not parse the file: {ex}")
            return
        db.save_profile(profile, e.name)
        result_area.clear()
        with result_area:
            if warnings:
                with ui.card().classes("w-full bg-amber-50"):
                    ui.label("Parsing warnings — please review:").classes("font-semibold")
                    for w in warnings:
                        ui.label("• " + w)
            render_profile_editor(result_area)
        notify_ok("CV parsed and profile saved. Review the fields below.")

    ui.upload(on_upload=handle_upload, auto_upload=True, max_files=1) \
        .props('accept=".pdf,.docx,.txt"').classes("w-full")
    if db.load_profile():
        render_profile_editor(result_area)


def render_profile_editor(container) -> None:
    p = db.load_profile() or {}
    with container:
        ui.label("Profile (editable)").classes("text-lg font-semibold mt-4")
        name = ui.input("Name", value=p.get("name", "")).classes("w-full")
        email = ui.input("Email", value=p.get("email", "")).classes("w-full")
        level = ui.select(["PhD", "Postdoc", "Research Fellow"], label="Target level",
                          value=p.get("target_level", "PhD")).classes("w-64")
        countries = ui.input("Target countries (comma-separated, e.g. UK, DE, AU)",
                             value=", ".join(p.get("target_countries", []))).classes("w-full")
        fields = {}
        for key, label in [("education", "Education (one per line)"),
                           ("publications", "Publications (one per line)"),
                           ("skills", "Skills (one per line)"),
                           ("teaching", "Teaching (one per line)"),
                           ("work_experience", "Work experience (one per line)")]:
            fields[key] = ui.textarea(label, value="\n".join(p.get(key, []))) \
                .classes("w-full").props("rows=4")

        def save() -> None:
            p2 = dict(p)
            p2.update(name=name.value, email=email.value, target_level=level.value,
                      target_countries=[c.strip() for c in countries.value.split(",") if c.strip()])
            for key, widget in fields.items():
                p2[key] = [l.strip() for l in widget.value.splitlines() if l.strip()]
            db.save_profile(p2)
            notify_ok("Profile saved.")

        ui.button("Save profile", on_click=save).props(f"color=primary")


def research_interests() -> None:
    ui.label("Research Interests").classes("text-2xl font-bold")
    p = db.load_profile() or {}
    ui.label("These drive search and matching. One interest per line.")
    areas = ui.textarea("Research interests",
                        value="\n".join(p.get("research_areas", []))).classes("w-full").props("rows=6")
    kws = ui.textarea("Extra keywords (optional)",
                      value="\n".join(p.get("keywords", []))).classes("w-full").props("rows=4")

    def save() -> None:
        p2 = db.load_profile() or {"target_level": "PhD", "target_countries": []}
        p2["research_areas"] = [l.strip() for l in areas.value.splitlines() if l.strip()]
        p2["keywords"] = [l.strip() for l in kws.value.splitlines() if l.strip()]
        db.save_profile(p2)
        notify_ok("Saved.")

    ui.button("Save", on_click=save).props("color=primary")


def search_positions() -> None:
    from app.sources.positions import SOURCES, search_all

    ui.label("Search Open Positions").classes("text-2xl font-bold")
    ui.label("Sources are scraped politely (robots.txt, rate limits, caching). "
             "Site layouts change — failures land in Logs / Manual Review.").classes("text-sm text-gray-500")
    p = db.load_profile() or {}
    default_kw = ", ".join(p.get("research_areas", [])[:3])
    kw = ui.input("Keywords", value=default_kw).classes("w-full")
    src = ui.select(list(SOURCES.keys()), multiple=True, value=list(SOURCES.keys()),
                    label="Sources").classes("w-full").props("use-chips")
    table_area = ui.column().classes("w-full")

    def render_table() -> None:
        table_area.clear()
        data = db.rows("SELECT * FROM positions WHERE review_status!='hidden' "
                       "ORDER BY id DESC LIMIT 200")
        with table_area:
            ui.label(f"{len(data)} stored positions").classes("font-semibold mt-2")
            ui.table(columns=[{"name": k, "label": k.replace('_', ' ').title(), "field": k,
                               "align": "left"} for k in
                              ("title", "university", "country", "deadline", "source", "source_url")],
                     rows=data, pagination=15).classes("w-full")

    async def go() -> None:
        if not kw.value.strip():
            notify_warn("Enter keywords first.")
            return
        n = ui.notification("Searching sources (rate-limited, may take a minute)...",
                            spinner=True, timeout=None)
        found = await run.io_bound(search_all, kw.value, src.value)
        n.dismiss()
        notify_ok(f"Search finished: {len(found)} results (deduplicated into the database).")
        render_table()

    ui.button("Search", on_click=go).props("color=primary")
    render_table()


def find_supervisors() -> None:
    from app.sources import openalex, semantic_scholar

    ui.label("Find Supervisors").classes("text-2xl font-bold")
    ui.label("Searches OpenAlex and Semantic Scholar (free public APIs).").classes(
        "text-sm text-gray-500")
    p = db.load_profile() or {}
    q = ui.input("Search (topic, name, discipline...)",
                 value=", ".join(p.get("research_areas", [])[:2])).classes("w-full")
    country = ui.input("Country code filter (optional, e.g. GB, DE, US)").classes("w-64")
    table_area = ui.column().classes("w-full")

    def render_table() -> None:
        table_area.clear()
        data = db.rows("SELECT id,name,university,country,email,source,profile_url "
                       "FROM supervisors ORDER BY id DESC LIMIT 300")
        with table_area:
            ui.label(f"{len(data)} stored supervisors").classes("font-semibold mt-2")
            ui.table(columns=[{"name": k, "label": k.title(), "field": k, "align": "left"}
                              for k in ("name", "university", "country", "email", "source")],
                     rows=data, pagination=15).classes("w-full")

    async def go() -> None:
        if not q.value.strip():
            notify_warn("Enter a search query.")
            return
        n = ui.notification("Querying OpenAlex + Semantic Scholar...", spinner=True, timeout=None)
        oa = await run.io_bound(openalex.search_authors, q.value,
                                country.value.strip() or None)
        s2 = await run.io_bound(semantic_scholar.search_authors, q.value)
        for s in oa + s2:
            openalex.save_supervisor(s)
        n.dismiss()
        notify_ok(f"Found {len(oa)} (OpenAlex) + {len(s2)} (Semantic Scholar). "
                  "Use 'Fetch publications' before emailing anyone.")
        render_table()

    async def fetch_pubs() -> None:
        sups = db.rows("SELECT * FROM supervisors WHERE source='openalex' "
                       "AND (publications IS NULL OR publications='[]') LIMIT 15")
        if not sups:
            notify_ok("All OpenAlex supervisors already have publications fetched "
                      "(or none stored yet).")
            return
        n = ui.notification(f"Fetching recent works for {len(sups)} supervisors...",
                            spinner=True, timeout=None)
        for s in sups:
            works = await run.io_bound(openalex.author_recent_works, s["external_id"])
            db.execute("UPDATE supervisors SET publications=? WHERE id=?",
                       (json.dumps(works), s["id"]))
        n.dismiss()
        notify_ok("Publications fetched (verified via OpenAlex).")
        render_table()

    with ui.row():
        ui.button("Search", on_click=go).props("color=primary")
        ui.button("Fetch publications (batch of 15)", on_click=fetch_pubs).props("outline")
    render_table()


def match_results() -> None:
    from app.matching import run_matching

    ui.label("Match Results").classes("text-2xl font-bold")
    results_area = ui.column().classes("w-full")

    def render() -> None:
        results_area.clear()
        matches = db.rows("SELECT * FROM matches ORDER BY score DESC LIMIT 100")
        with results_area:
            if not matches:
                ui.label("No matches yet — run matching above.").classes("text-gray-500")
                return
            for m in matches:
                r = json.loads(m["reasons"])
                target = db.rows(f"SELECT * FROM {'supervisors' if m['kind']=='supervisor' else 'positions'} "
                                 "WHERE id=?", (m["target_id"],))
                if not target:
                    continue
                t = target[0]
                title = t.get("name") or t.get("title") or "?"
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label(f"{title} — {t.get('university','')}").classes("font-semibold")
                        badge_color = "green" if m["score"] >= 60 else \
                            ("orange" if m["score"] >= 35 else "red")
                        ui.badge(f"{m['score']}").props(f"color={badge_color}")
                    ui.label(f"Type: {m['kind']}  |  Confidence: {m['confidence']}") \
                        .classes("text-xs text-gray-500")
                    ui.label("Why: " + r.get("why", ""))
                    for risk in r.get("risks", []):
                        ui.label("⚠ " + risk).classes("text-amber-700 text-sm")
                    if r.get("deadline_note"):
                        ui.label("Deadline: " + r["deadline_note"]).classes("text-sm")
                    ui.label("Suggested angle: " + r.get("email_angle", "")).classes("text-sm")
                    url = t.get("source_url") or t.get("profile_url") or ""
                    if url:
                        ui.link("Source", url, new_tab=True).classes("text-sm")

    async def go() -> None:
        p = profile_or_warn()
        if not p:
            return
        n = ui.notification("Scoring all supervisors and positions...", spinner=True, timeout=None)
        counts = await run.io_bound(run_matching, p)
        n.dismiss()
        notify_ok(f"Matched {counts['supervisors']} supervisors and "
                  f"{counts['positions']} positions.")
        render()

    ui.button("Run matching", on_click=go).props("color=primary")
    render()


def generate_documents() -> None:
    from app.docgen.generators import (TIMELINES, generate_cv, generate_email,
                                       generate_proposal, generate_timeline)
    from app.references import STYLES, collect_verified, verify_reference

    ui.label("Generate Documents").classes("text-2xl font-bold")
    ui.label(f"Output folder: {OUTPUT_DIR}").classes("text-sm text-gray-500")
    sups = db.rows("SELECT id,name,university FROM supervisors ORDER BY name LIMIT 500")
    sup_options = {s["id"]: f"{s['name']} ({s['university']})" for s in sups}

    with ui.tabs() as doc_tabs:
        t_cv = ui.tab("Tailored CV")
        t_prop = ui.tab("Research Proposal")
        t_tl = ui.tab("Timeline")
        t_em = ui.tab("Outreach Email")
    with ui.tab_panels(doc_tabs, value=t_cv).classes("w-full"):
        with ui.tab_panel(t_cv):
            ui.label("Generates DOCX + PDF from your saved profile. Facts are never invented.")

            async def gen_cv() -> None:
                p = profile_or_warn()
                if not p:
                    return
                res = await run.io_bound(generate_cv, p)
                notify_ok(f"CV saved: {res['docx']} and .pdf")
            ui.button("Generate CV", on_click=gen_cv).props("color=primary")

        with ui.tab_panel(t_prop):
            topic = ui.input("Proposal topic").classes("w-full")
            style = ui.select(list(STYLES), value="APA 7", label="Citation style").classes("w-48")
            sup_sel = ui.select(sup_options or {0: "— none —"}, label="Align with supervisor "
                                "(optional)", value=None, clearable=True).classes("w-full")
            ui.label("References are fetched from OpenAlex/Semantic Scholar and verified via "
                     "Crossref. Unverifiable items are excluded and flagged in the audit file.") \
                .classes("text-sm text-gray-500")

            async def gen_prop() -> None:
                p = profile_or_warn()
                if not p or not topic.value.strip():
                    if p:
                        notify_warn("Enter a topic.")
                    return
                n = ui.notification("Collecting and verifying references...",
                                    spinner=True, timeout=None)
                refs = await run.io_bound(collect_verified, topic.value)
                refs = [await run.io_bound(verify_reference, r) for r in refs]
                sup = None
                if sup_sel.value:
                    got = db.rows("SELECT * FROM supervisors WHERE id=?", (sup_sel.value,))
                    sup = got[0] if got else None
                res = await run.io_bound(generate_proposal, p, topic.value, refs, sup, style.value)
                n.dismiss()
                flagged = sum(1 for r in refs if not r.get("verified"))
                msg = f"Proposal saved: {res['docx']} (+PDF, +source audit)."
                if flagged:
                    msg += f" {flagged} reference(s) need manual review — see the audit file."
                notify_ok(msg)
            ui.button("Generate proposal", on_click=gen_prop).props("color=primary")

        with ui.tab_panel(t_tl):
            kind = ui.select(list(TIMELINES.keys()), value="3-year PhD",
                             label="Timeline type").classes("w-64")
            tl_topic = ui.input("Project title (optional)").classes("w-full")

            async def gen_tl() -> None:
                res = await run.io_bound(generate_timeline, kind.value, tl_topic.value)
                notify_ok(f"Timeline saved: {res['docx']} and .pdf")
            ui.button("Generate timeline", on_click=gen_tl).props("color=primary")

        with ui.tab_panel(t_em):
            em_sup = ui.select(sup_options or {0: "— add supervisors first —"},
                               label="Supervisor").classes("w-full")
            em_topic = ui.input("Proposed topic").classes("w-full")
            preview = ui.column().classes("w-full")

            async def gen_em() -> None:
                p = profile_or_warn()
                if not p or not em_sup.value or not em_topic.value.strip():
                    if p:
                        notify_warn("Pick a supervisor and enter a topic.")
                    return
                got = db.rows("SELECT * FROM supervisors WHERE id=?", (em_sup.value,))
                if not got:
                    return
                res = await run.io_bound(generate_email, p, got[0], em_topic.value)
                preview.clear()
                with preview:
                    if res.get("warning"):
                        ui.label("⚠ " + res["warning"]).classes("text-amber-700")
                    ui.label("Draft created — edit and send it from the Email Outreach page.") \
                        .classes("text-green-700")
                    ui.label("Subject: " + res["subject"]).classes("font-semibold")
                    ui.markdown(f"```\n{res['body']}\n```")
            ui.button("Create email draft", on_click=gen_em).props("color=primary")

    ui.separator().classes("my-4")
    ui.label("Generated documents").classes("text-lg font-semibold")
    docs = db.rows("SELECT * FROM documents ORDER BY id DESC LIMIT 50")
    ui.table(columns=[{"name": k, "label": k.title(), "field": k, "align": "left"}
                      for k in ("doc_type", "title", "path", "created_at")],
             rows=docs, pagination=10).classes("w-full")


def email_outreach() -> None:
    from app.emailer import gmail_oauth, outlook_oauth
    from app.emailer.sender import daily_limit, send_draft, sent_today

    ui.label("Email Outreach").classes("text-2xl font-bold")
    ui.label(f"Safe sending: manual review required; limit {daily_limit()}/day "
             f"({sent_today()} sent today). No bulk sending.").classes("text-sm text-gray-500")
    lst = ui.column().classes("w-full")

    def render() -> None:
        lst.clear()
        drafts = db.rows("SELECT * FROM email_log WHERE status='draft' ORDER BY id DESC")
        sent = db.rows("SELECT * FROM email_log WHERE status IN ('sent','failed') "
                       "ORDER BY id DESC LIMIT 30")
        with lst:
            ui.label(f"Drafts ({len(drafts)})").classes("text-lg font-semibold")
            for d in drafts:
                with ui.card().classes("w-full"):
                    to = ui.input("To", value=d["recipient"]).classes("w-full")
                    subj = ui.input("Subject", value=d["subject"]).classes("w-full")
                    body = ui.textarea("Body", value=d["body"]).classes("w-full").props("rows=10")

                    def make_send(d_id: int, to_w=to, s_w=subj, b_w=body):
                        async def do(provider: str) -> None:
                            db.execute("UPDATE email_log SET recipient=?, subject=?, body=? "
                                       "WHERE id=?", (to_w.value, s_w.value, b_w.value, d_id))
                            ok, msg = await run.io_bound(send_draft, d_id, provider)
                            (notify_ok if ok else notify_warn)(msg)
                            render()
                        return do
                    send_fn = make_send(d["id"])
                    with ui.row():
                        ui.button("Send via Gmail", on_click=lambda f=send_fn: f("gmail")) \
                            .props("color=primary" if gmail_oauth.is_connected() else "outline")
                        ui.button("Send via Outlook", on_click=lambda f=send_fn: f("outlook")) \
                            .props("color=primary" if outlook_oauth.is_connected() else "outline")

                        def save_only(d_id=d["id"], to_w=to, s_w=subj, b_w=body):
                            db.execute("UPDATE email_log SET recipient=?, subject=?, body=? "
                                       "WHERE id=?", (to_w.value, s_w.value, b_w.value, d_id))
                            notify_ok("Draft saved.")
                        ui.button("Save draft", on_click=save_only).props("flat")
            ui.label("History").classes("text-lg font-semibold mt-4")
            ui.table(columns=[{"name": k, "label": k.title(), "field": k, "align": "left"}
                              for k in ("status", "provider", "recipient", "subject", "sent_at")],
                     rows=sent, pagination=10).classes("w-full")

    render()


def settings_page() -> None:
    from app.emailer import gmail_oauth, outlook_oauth

    ui.label("Settings").classes("text-2xl font-bold")
    ui.label("Keys are stored locally (SQLite / OS keychain). You can also use a .env file. "
             "The app works in limited mode without any keys.").classes("text-sm text-gray-500")
    with ui.card().classes("w-full"):
        ui.label("API keys").classes("text-lg font-semibold")
        inputs = {}
        for name in KEY_NAMES:
            secret = "KEY" in name or "SECRET" in name
            inputs[name] = ui.input(name, value=get_setting(name) or "",
                                    password=secret, password_toggle_button=secret) \
                .classes("w-full")

        def save_keys() -> None:
            for name, w in inputs.items():
                if w.value:
                    set_setting(name, w.value)
            notify_ok("Settings saved.")
        ui.button("Save", on_click=save_keys).props("color=primary")

    with ui.card().classes("w-full mt-4"):
        ui.label("Email accounts (OAuth)").classes("text-lg font-semibold")
        status = ui.column()

        def render_status() -> None:
            status.clear()
            with status:
                ui.label(f"Gmail: {'connected ✓' if gmail_oauth.is_connected() else 'not connected'}")
                ui.label(f"Outlook: {'connected ✓' if outlook_oauth.is_connected() else 'not connected'}")

        async def connect_gmail() -> None:
            try:
                await run.io_bound(gmail_oauth.connect)
                notify_ok("Gmail connected.")
            except Exception as e:
                notify_warn(str(e))
            render_status()

        async def connect_outlook() -> None:
            code_box = ui.dialog()
            with code_box, ui.card():
                msg_label = ui.label("Starting device sign-in...")
            code_box.open()
            try:
                def show(msg: str) -> None:
                    msg_label.text = msg
                await run.io_bound(outlook_oauth.connect, show)
                notify_ok("Outlook connected.")
            except Exception as e:
                notify_warn(str(e))
            code_box.close()
            render_status()

        def disconnect_all() -> None:
            gmail_oauth.disconnect()
            outlook_oauth.disconnect()
            notify_ok("Tokens deleted.")
            render_status()

        with ui.row():
            ui.button("Connect Gmail", on_click=connect_gmail).props("outline")
            ui.button("Connect Outlook", on_click=connect_outlook).props("outline")
            ui.button("Revoke / delete tokens", on_click=disconnect_all).props("flat color=red")
        render_status()

    with ui.card().classes("w-full mt-4"):
        ui.label("Sending safety").classes("text-lg font-semibold")
        lim = ui.number("Daily send limit", value=int(get_setting("DAILY_SEND_LIMIT") or 10),
                        min=1, max=50)
        ui.button("Save limit", on_click=lambda: (set_setting("DAILY_SEND_LIMIT",
                  str(int(lim.value))), notify_ok("Saved."))).props("outline")


def logs_page() -> None:
    ui.label("Logs / Manual Review").classes("text-2xl font-bold")
    with ui.tabs() as tabs:
        t_review = ui.tab("Needs review")
        t_all = ui.tab("All errors")
    with ui.tab_panels(tabs, value=t_review).classes("w-full"):
        with ui.tab_panel(t_review):
            items = db.rows("SELECT * FROM error_log WHERE needs_review=1 AND resolved=0 "
                            "ORDER BY id DESC LIMIT 200")
            if not items:
                ui.label("Nothing needs review. 🎉").classes("text-green-700")
            for it in items:
                with ui.card().classes("w-full"):
                    ui.label(f"[{it['category']}] {it['message']}").classes("font-semibold")
                    if it["detail"]:
                        ui.label(it["detail"][:300]).classes("text-sm text-gray-500")
                    ui.label(it["created_at"]).classes("text-xs text-gray-400")

                    def resolve(i=it["id"]) -> None:
                        db.execute("UPDATE error_log SET resolved=1 WHERE id=?", (i,))
                        notify_ok("Marked resolved.")
                    ui.button("Mark resolved", on_click=resolve).props("flat dense")
        with ui.tab_panel(t_all):
            all_rows = db.rows("SELECT category,message,created_at FROM error_log "
                               "ORDER BY id DESC LIMIT 300")
            ui.table(columns=[{"name": k, "label": k.title(), "field": k, "align": "left"}
                              for k in ("category", "message", "created_at")],
                     rows=all_rows, pagination=20).classes("w-full")
    ui.label(f"Full application log file: {APP_DIR / 'app.log'}").classes(
        "text-sm text-gray-500 mt-2")


SECTIONS = [
    ("Dashboard", "dashboard", dashboard),
    ("Upload CV", "upload_file", upload_cv),
    ("Research Interests", "psychology", research_interests),
    ("Search Open Positions", "work", search_positions),
    ("Find Supervisors", "school", find_supervisors),
    ("Match Results", "join_inner", match_results),
    ("Generate Documents", "description", generate_documents),
    ("Email Outreach", "mail", email_outreach),
    ("Settings", "settings", settings_page),
    ("Logs / Manual Review", "rule", logs_page),
]


@ui.page("/")
def index() -> None:
    ui.colors(primary=ACCENT)
    with ui.header().classes("items-center"):
        ui.label("🎓 PhD & Postdoc Supervisor Finder").classes("text-lg font-bold")
    with ui.left_drawer(value=True).classes("bg-gray-50") as drawer:
        content = ui.column  # placeholder for closure clarity
        nav_buttons = []

    body = ui.column().classes("w-full p-4")

    def show(idx: int) -> None:
        body.clear()
        with body:
            try:
                SECTIONS[idx][2]()
            except Exception as e:
                log.exception("UI section failed")
                db.log_error("app", f"UI error in {SECTIONS[idx][0]}: {e}")
                ui.label(f"Something went wrong rendering this page: {e}").classes("text-red-600")

    with drawer:
        for i, (label, icon, _fn) in enumerate(SECTIONS):
            ui.button(label, icon=icon, on_click=lambda _=None, i=i: show(i)) \
                .props("flat align=left no-caps").classes("w-full justify-start")
    show(0)


def main() -> None:
    import os
    log.info("Starting PhD & Postdoc Supervisor Finder")
    # Desktop users get the browser opened automatically; PPSF_NO_SHOW=1 keeps
    # headless/CI runs from trying to spawn one.
    show = os.environ.get("PPSF_NO_SHOW") != "1"
    ui.run(title="PhD & Postdoc Supervisor Finder", host="127.0.0.1", port=8765,
           reload=False, show=show, favicon="🎓")


if __name__ in {"__main__", "__mp_main__"}:
    main()
