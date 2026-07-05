"""PhD & Postdoc Supervisor Finder v2 — guided-workflow desktop UI (NiceGUI).

v2 restructures the app from disconnected tabs into a chained pipeline:
  1 Profile -> 2 Search -> 3 Classify & Shortlist -> 4 Supervisors ->
  5 Fit -> 6 Documents -> 7 Outreach -> 8 Tracker -> 9 Settings/Logs

Every later step operates only on what the user selected in earlier steps.
Run:  python -m app.main   (or the desktop shortcut created by the installer)
Everything runs locally; the browser window is just the UI."""
from __future__ import annotations

import json
from pathlib import Path

from nicegui import app as ng_app, run, ui

from app import db, llm
from app.config import APP_DIR, KEY_NAMES, OUTPUT_DIR, get_setting, set_setting
from app.europe import EUROPE_COUNTRIES
from app.logging_setup import log

db.init_db()

ACCENT = "#4f46e5"

CLASS_COLORS = {
    "supervisor_required": "red", "supervisor_recommended": "orange",
    "direct_application": "blue", "named_pi_postdoc": "purple",
    "open_call_postdoc": "teal",
}


# ---------------------------------------------------------------- helpers

def notify_ok(msg: str) -> None:
    ui.notify(msg, type="positive")


def notify_warn(msg: str) -> None:
    ui.notify(msg, type="warning", timeout=8000)


def profile_or_warn() -> dict | None:
    p = db.load_profile()
    if not p:
        notify_warn("No profile yet — complete Step 1 (Profile) first.")
    return p


def shortlist() -> list[dict]:
    return db.rows("SELECT * FROM positions WHERE shortlisted=1 ORDER BY id DESC")


def class_badge(pos: dict) -> None:
    from app.classify import LABELS
    label = pos.get("classification") or ""
    if not label:
        ui.badge("unclassified").props("color=grey")
        return
    color = CLASS_COLORS.get(label, "grey")
    ui.badge(LABELS.get(label, label)).props(f"color={color}")
    src = "official" if pos.get("class_source_official") else "third-party"
    ui.badge(f"{src} · conf {pos.get('class_confidence', 0)}").props("color=grey-6 outline")


# ---------------------------------------------------------------- step 0: dashboard

def dashboard() -> None:
    p = db.load_profile()
    stats = {
        "Opportunities": db.rows("SELECT COUNT(*) n FROM positions")[0]["n"],
        "Shortlisted": db.rows("SELECT COUNT(*) n FROM positions WHERE shortlisted=1")[0]["n"],
        "Supervisors": db.rows("SELECT COUNT(*) n FROM supervisors")[0]["n"],
        "Fit scores": db.rows("SELECT COUNT(*) n FROM fit_scores")[0]["n"],
        "Documents": db.rows("SELECT COUNT(*) n FROM documents")[0]["n"],
        "Applications": db.rows("SELECT COUNT(*) n FROM applications")[0]["n"],
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
        ui.label("The workflow").classes("text-lg font-semibold")
        for s in ["1. Profile — upload your CV and set interests",
                  "2. Search — Europe-only opportunities with filters",
                  "3. Classify & shortlist — admission path with evidence; pick your targets",
                  "4. Supervisors — found only at your shortlisted universities",
                  "5. Fit — explainable scores for each opportunity/supervisor pair",
                  "6. Documents — the right bundle for each admission path",
                  "7. Outreach — review-then-send, never blind mass mail",
                  "8. Tracker — statuses, notes, 14-day follow-up reminders"]:
            ui.label(s)
        mode = "LLM assistance ON" if llm.available() else \
            "Limited mode (no LLM key) — search, classification, matching and documents still work"
        ui.label(f"Mode: {mode}").classes("text-sm mt-2 text-gray-500")
    if p:
        ui.label(f"Profile loaded: {p.get('name') or 'unnamed'} ({p.get('email','')})") \
            .classes("mt-2 text-green-700")


# ---------------------------------------------------------------- step 1: profile

def step_profile() -> None:
    ui.label("Step 1 — Profile").classes("text-2xl font-bold")
    ui.label("Upload your CV (PDF/DOCX); extraction is heuristic — review everything below. "
             "Research interests drive search, supervisor discovery and fit scoring.")
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
        countries = ui.input("Target countries (comma-separated, e.g. DE, HU, NL)",
                             value=", ".join(p.get("target_countries", []))).classes("w-full")
        areas = ui.textarea("Research interests (one per line)",
                            value="\n".join(p.get("research_areas", []))) \
            .classes("w-full").props("rows=5")
        kws = ui.textarea("Extra keywords (optional, one per line)",
                          value="\n".join(p.get("keywords", []))).classes("w-full").props("rows=3")
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
                      target_countries=[c.strip() for c in countries.value.split(",") if c.strip()],
                      research_areas=[l.strip() for l in areas.value.splitlines() if l.strip()],
                      keywords=[l.strip() for l in kws.value.splitlines() if l.strip()])
            for key, widget in fields.items():
                p2[key] = [l.strip() for l in widget.value.splitlines() if l.strip()]
            db.save_profile(p2)
            notify_ok("Profile saved.")

        ui.button("Save profile", on_click=save).props("color=primary")


# ---------------------------------------------------------------- step 2: search

def step_search() -> None:
    from app.sources.positions import SOURCES, search_all

    ui.label("Step 2 — Search opportunities (Europe only)").classes("text-2xl font-bold")
    ui.label("Sources are scraped politely (robots.txt, rate limits, caching). Results are "
             "filtered to Europe. Site failures land in Logs / Manual Review.") \
        .classes("text-sm text-gray-500")
    p = db.load_profile() or {}
    with ui.row().classes("w-full gap-2 items-end flex-wrap"):
        kw = ui.input("Keywords", value=", ".join(p.get("research_areas", [])[:2])).classes("w-80")
        field = ui.input("Field/discipline").classes("w-56")
        country = ui.select({"": "Any European country",
                             **{c: n for c, n in sorted(EUROPE_COUNTRIES.items(),
                                                        key=lambda x: x[1])}},
                            value="", label="Country").classes("w-56")
        kind = ui.select({"": "PhD + Postdoc", "phd": "PhD only", "postdoc": "Postdoc only"},
                         value="", label="Type").classes("w-44")
        uni = ui.input("University (contains)").classes("w-56")
    src = ui.select(list(SOURCES.keys()), multiple=True, value=list(SOURCES.keys()),
                    label="Sources").classes("w-full").props("use-chips")
    table_area = ui.column().classes("w-full")

    def render_table() -> None:
        table_area.clear()
        where, args = ["review_status!='hidden'"], []
        if country.value:
            where.append("(country=? OR country='')")
            args.append(country.value)
        if kind.value:
            where.append("(kind=? OR kind='')")
            args.append(kind.value)
        if uni.value.strip():
            where.append("university LIKE ?")
            args.append(f"%{uni.value.strip()}%")
        data = db.rows(f"SELECT * FROM positions WHERE {' AND '.join(where)} "
                       "ORDER BY id DESC LIMIT 300", tuple(args))
        with table_area:
            ui.label(f"{len(data)} stored opportunities (filtered view)") \
                .classes("font-semibold mt-2")
            ui.table(columns=[{"name": k, "label": k.replace('_', ' ').title(), "field": k,
                               "align": "left"} for k in
                              ("title", "university", "country", "kind", "deadline",
                               "source")],
                     rows=data, pagination=15).classes("w-full")

    async def go() -> None:
        if not kw.value.strip():
            notify_warn("Enter keywords first.")
            return
        n = ui.notification("Searching sources (rate-limited, may take a minute)...",
                            spinner=True, timeout=None)
        filters = {"country": country.value, "kind": kind.value,
                   "university": uni.value, "field": field.value}
        found = await run.io_bound(search_all, kw.value, src.value, filters)
        n.dismiss()
        notify_ok(f"Search finished: {len(found)} Europe-matched results stored. "
                  "Continue to Step 3 to classify and shortlist.")
        render_table()

    ui.button("Search", on_click=go).props("color=primary")
    render_table()


# ---------------------------------------------------------------- step 3: classify & shortlist

def step_classify() -> None:
    from app.classify import LABELS, classify_and_store

    ui.label("Step 3 — Classify admission path & shortlist").classes("text-2xl font-bold")
    ui.label("Classification prefers official university pages over portals; the evidence "
             "snippet and source are always shown. Tick the opportunities you want to "
             "pursue — later steps only operate on your shortlist.") \
        .classes("text-sm text-gray-500")
    filter_box = ui.input("Filter list (title/university contains)").classes("w-96")
    lst = ui.column().classes("w-full")

    def render() -> None:
        lst.clear()
        flt = f"%{filter_box.value.strip()}%" if filter_box.value else "%"
        data = db.rows("SELECT * FROM positions WHERE review_status!='hidden' AND "
                       "(title LIKE ? OR university LIKE ?) ORDER BY shortlisted DESC, "
                       "id DESC LIMIT 100", (flt, flt))
        with lst:
            ui.label(f"{len(data)} opportunities · "
                     f"{sum(1 for d in data if d['shortlisted'])} shortlisted") \
                .classes("font-semibold")
            for pos in data:
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        with ui.row().classes("items-center gap-2"):
                            ui.checkbox(value=bool(pos["shortlisted"]),
                                        on_change=lambda e, pid=pos["id"]:
                                        (db.execute("UPDATE positions SET shortlisted=? WHERE id=?",
                                                    (int(e.value), pid))))
                            ui.label(f"{pos['title'][:90]}").classes("font-semibold")
                        class_badge(pos)
                    ui.label(f"{pos.get('university') or '(university unknown — edit below)'} · "
                             f"{pos.get('country') or '?'} · {pos.get('kind') or '?'} · "
                             f"deadline: {pos.get('deadline') or 'unknown'}") \
                        .classes("text-sm text-gray-600")
                    if pos.get("class_evidence"):
                        with ui.expansion("Why this classification?").classes("w-full text-sm"):
                            ui.label(f"Evidence: “…{pos['class_evidence'][:400]}…”")
                            ui.label(f"Source ({'official' if pos.get('class_source_official') else 'third-party'}): "
                                     f"{pos.get('class_source_url','')}")
                            ui.label("Rule: official pages override third-party portals; "
                                     "low-confidence results are flagged in Logs for manual review.")
                    with ui.row().classes("gap-2"):
                        async def classify_one(pid=pos["id"]):
                            n = ui.notification("Classifying (fetching official pages)...",
                                                spinner=True, timeout=None)
                            res = await run.io_bound(classify_and_store, pid, True)
                            n.dismiss()
                            if res:
                                notify_ok(f"Classified: {res['label_text']} "
                                          f"(confidence {res['confidence']})")
                            render()
                        ui.button("Classify", on_click=classify_one).props("outline dense")

                        def edit_uni(pos=pos):
                            with ui.dialog() as dlg, ui.card():
                                u = ui.input("University", value=pos.get("university", ""))
                                c = ui.input("Country (name or code)", value=pos.get("country", ""))
                                dl = ui.input("Deadline (YYYY-MM-DD)", value=pos.get("deadline", ""))

                                def save():
                                    db.execute("UPDATE positions SET university=?, country=?, "
                                               "deadline=? WHERE id=?",
                                               (u.value, c.value, dl.value, pos["id"]))
                                    dlg.close()
                                    notify_ok("Saved.")
                                    render()
                                ui.button("Save", on_click=save).props("color=primary")
                            dlg.open()
                        ui.button("Edit details", on_click=edit_uni).props("flat dense")

                        def hide(pid=pos["id"]):
                            db.execute("UPDATE positions SET review_status='hidden' WHERE id=?", (pid,))
                            render()
                        ui.button("Hide", on_click=hide).props("flat dense color=grey")
                        if pos.get("source_url"):
                            ui.link("Open source page", pos["source_url"], new_tab=True) \
                                .classes("text-sm self-center")

    async def classify_all() -> None:
        pending = db.rows("SELECT id FROM positions WHERE review_status!='hidden' "
                          "AND classification='' LIMIT 30")
        if not pending:
            notify_ok("Everything visible is already classified.")
            return
        n = ui.notification(f"Classifying {len(pending)} opportunities (rate-limited)...",
                            spinner=True, timeout=None)
        for r in pending:
            await run.io_bound(classify_and_store, r["id"], True)
        n.dismiss()
        notify_ok("Classification finished. Review evidence and shortlist your targets.")
        render()

    with ui.row():
        ui.button("Classify all unclassified (batch of 30)", on_click=classify_all) \
            .props("color=primary")
        ui.button("Refresh list", on_click=render).props("outline")
    filter_box.on("change", lambda _: render())
    render()


# ---------------------------------------------------------------- step 4: supervisors

def step_supervisors() -> None:
    from app.sources.university import fetch_publications, find_supervisors_for_position

    ui.label("Step 4 — Find supervisors/PIs (shortlist-constrained)").classes("text-2xl font-bold")
    ui.label("Supervisors are searched ONLY at the university of each shortlisted "
             "opportunity: official staff/faculty/doctoral-school pages first, plus "
             "OpenAlex authors hard-filtered to that institution. No generic results.") \
        .classes("text-sm text-gray-500")
    sl = shortlist()
    if not sl:
        ui.label("Your shortlist is empty — go back to Step 3 and select opportunities first.") \
            .classes("text-amber-700")
        return
    p = db.load_profile() or {}
    topic = ui.input("Topic for supervisor matching",
                     value=", ".join(p.get("research_areas", [])[:2])).classes("w-full")
    lst = ui.column().classes("w-full")

    def render() -> None:
        lst.clear()
        with lst:
            for pos in shortlist():
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label(f"{pos['title'][:80]} — {pos.get('university') or '?'}") \
                            .classes("font-semibold")
                        class_badge(pos)
                    sups = db.rows("SELECT * FROM supervisors WHERE position_id=? "
                                   "ORDER BY source_type='official' DESC, id", (pos["id"],))
                    ui.label(f"{len(sups)} supervisors found for this opportunity") \
                        .classes("text-sm text-gray-600")
                    for s in sups[:25]:
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.badge("official" if s["source_type"] == "official" else "OpenAlex") \
                                .props(f"color={'green' if s['source_type']=='official' else 'grey'}")
                            ui.label(f"{s.get('title','')} {s['name']}".strip()) \
                                .classes("font-medium")
                            areas = json.loads(s.get("research_areas") or "[]")
                            if areas:
                                ui.label(", ".join(areas[:3])).classes("text-xs text-gray-500")
                            if s.get("email"):
                                ui.label(s["email"]).classes("text-xs text-blue-700")
                            n_pubs = len(json.loads(s.get("publications") or "[]"))
                            ui.label(f"{n_pubs} pubs").classes("text-xs text-gray-400")

                            async def pubs(sid=s["id"]):
                                nn = ui.notification("Fetching verified publications...",
                                                     spinner=True, timeout=None)
                                n2 = await run.io_bound(fetch_publications, sid, 5)
                                nn.dismiss()
                                notify_ok(f"{n2} verified publications fetched.")
                                render()
                            ui.button("Pubs", on_click=pubs).props("flat dense")
                            if s.get("profile_url"):
                                ui.link("profile", s["profile_url"], new_tab=True) \
                                    .classes("text-xs self-center")

                    async def find(pid=pos["id"]):
                        if not topic.value.strip():
                            notify_warn("Enter a topic first.")
                            return
                        n = ui.notification("Resolving institution and searching (official "
                                            "pages + OpenAlex, rate-limited)...",
                                            spinner=True, timeout=None)
                        res = await run.io_bound(find_supervisors_for_position, pid, topic.value)
                        n.dismiss()
                        if res.get("error"):
                            notify_warn(res["error"])
                        else:
                            inst = res.get("institution") or {}
                            notify_ok(f"Found {res['official']} from official pages and "
                                      f"{res['bibliometric']} via OpenAlex at "
                                      f"{inst.get('name', 'the university')}.")
                        render()
                    ui.button("Find supervisors here", on_click=find).props("color=primary dense")

    render()


# ---------------------------------------------------------------- step 5: fit

def step_fit() -> None:
    from app.fit import run_fit_for_shortlist

    ui.label("Step 5 — Review fit").classes("text-2xl font-bold")
    ui.label("Fit is scored only for your shortlist: each opportunity alone and paired "
             "with each discovered supervisor. Every score shows its components, why, "
             "risks, and whether outreach is required/useful.").classes("text-sm text-gray-500")
    results_area = ui.column().classes("w-full")

    def render() -> None:
        results_area.clear()
        fits = db.rows(
            "SELECT f.*, p.title AS pos_title, p.university, p.classification, "
            "s.name AS sup_name, s.source_type FROM fit_scores f "
            "JOIN positions p ON p.id=f.position_id "
            "LEFT JOIN supervisors s ON s.id=f.supervisor_id "
            "ORDER BY f.score DESC LIMIT 150")
        with results_area:
            if not fits:
                ui.label("No fit scores yet — run scoring above.").classes("text-gray-500")
                return
            for m in fits:
                r = json.loads(m["reasons"])
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        who = f" + {m['sup_name']}" if m["sup_name"] else " (opportunity only)"
                        ui.label(f"{m['pos_title'][:70]}{who} — {m['university']}") \
                            .classes("font-semibold")
                        color = {"strong": "green", "moderate": "orange",
                                 "weak": "red", "avoid": "grey"}[m["recommendation"]]
                        ui.badge(f"{m['score']} · {m['recommendation']}").props(f"color={color}")
                    ui.label("Why: " + r.get("why", ""))
                    if r.get("outreach_required"):
                        ui.label("Outreach: REQUIRED for this admission path.") \
                            .classes("text-red-700 text-sm font-medium")
                    elif r.get("outreach_useful"):
                        ui.label("Outreach: recommended/useful.").classes("text-sm text-blue-700")
                    else:
                        ui.label("Outreach: optional — direct application is the main route.") \
                            .classes("text-sm text-gray-500")
                    for risk in r.get("risks", []):
                        ui.label("⚠ " + risk).classes("text-amber-700 text-sm")
                    comp = r.get("components", {})
                    ui.label("Components: " + ", ".join(f"{k}={v}" for k, v in comp.items()
                                                        if v is not None)) \
                        .classes("text-xs text-gray-400")

    async def go() -> None:
        p = profile_or_warn()
        if not p:
            return
        if not shortlist():
            notify_warn("Shortlist is empty — select opportunities in Step 3 first.")
            return
        n = ui.notification("Scoring shortlist...", spinner=True, timeout=None)
        count = await run.io_bound(run_fit_for_shortlist, p)
        n.dismiss()
        notify_ok(f"Scored {count} opportunity/supervisor combinations.")
        render()

    ui.button("Run fit scoring on shortlist", on_click=go).props("color=primary")
    render()


# ---------------------------------------------------------------- step 6: documents

def step_documents() -> None:
    from app.docgen.bundles import BUNDLE_FOR, BUNDLE_NAMES, generate_bundle
    from app.references import STYLES

    ui.label("Step 6 — Generate documents (by admission path)").classes("text-2xl font-bold")
    ui.label(f"Output folder: {OUTPUT_DIR}. The document set follows the classification: "
             "supervisor-first PhD, direct-application PhD, or postdoc each get their own "
             "bundle. Facts are never invented; references are verified or excluded.") \
        .classes("text-sm text-gray-500")
    sl = shortlist()
    if not sl:
        ui.label("Shortlist is empty — select opportunities in Step 3 first.") \
            .classes("text-amber-700")
        return
    p = db.load_profile() or {}
    pos_options = {x["id"]: f"{x['title'][:60]} — {x.get('university','?')}" for x in sl}
    pos_sel = ui.select(pos_options, label="Shortlisted opportunity",
                        value=next(iter(pos_options))).classes("w-full")
    sup_area = ui.column().classes("w-full")
    topic = ui.input("Topic / proposed focus",
                     value=", ".join(p.get("research_areas", [])[:1])).classes("w-full")
    style = ui.select(list(STYLES), value="APA 7", label="Citation style").classes("w-48")
    proposal_cb = ui.checkbox("Include full research proposal (only when required "
                              "or strategically useful)")
    info = ui.column().classes("w-full")
    sup_sel = {"widget": None}

    def refresh_sup() -> None:
        sup_area.clear()
        info.clear()
        pid = pos_sel.value
        pos = next((x for x in shortlist() if x["id"] == pid), None)
        if not pos:
            return
        with info:
            bundle = BUNDLE_FOR.get(pos.get("classification") or "direct_application", "B")
            ui.label(f"Bundle for this opportunity: {BUNDLE_NAMES[bundle]}") \
                .classes("text-sm font-medium text-indigo-700")
            if not pos.get("classification"):
                ui.label("⚠ Not classified yet — defaulting to direct application. "
                         "Classify in Step 3 for the correct bundle.") \
                    .classes("text-amber-700 text-sm")
        sups = db.rows("SELECT id,name,title,source_type,university FROM supervisors "
                       "WHERE position_id=? ORDER BY source_type='official' DESC", (pid,))
        opts = {0: "— no supervisor —"}
        opts.update({s["id"]: f"{s.get('title','')} {s['name']} "
                     f"[{s['source_type']}]".strip() for s in sups})
        with sup_area:
            sup_sel["widget"] = ui.select(opts, label="Supervisor/PI (from Step 4)",
                                          value=0).classes("w-full")

    pos_sel.on_value_change(lambda _: refresh_sup())
    refresh_sup()

    result_area = ui.column().classes("w-full")

    async def go() -> None:
        prof = profile_or_warn()
        if not prof:
            return
        pid = pos_sel.value
        pos = db.rows("SELECT * FROM positions WHERE id=?", (pid,))
        if not pos:
            return
        pos = pos[0]
        sup = None
        sid = sup_sel["widget"].value if sup_sel["widget"] else 0
        if sid:
            got = db.rows("SELECT * FROM supervisors WHERE id=?", (sid,))
            sup = got[0] if got else None
        fit = None
        fr = db.rows("SELECT reasons FROM fit_scores WHERE position_id=? AND supervisor_id=?",
                     (pid, sid or 0))
        if fr:
            fit = json.loads(fr[0]["reasons"])
        n = ui.notification("Generating document bundle (references are verified — "
                            "this can take a minute)...", spinner=True, timeout=None)
        res = await run.io_bound(generate_bundle, prof, pos, sup,
                                 topic.value or pos.get("title", ""), style.value,
                                 proposal_cb.value or None, fit)
        n.dismiss()
        result_area.clear()
        with result_area:
            with ui.card().classes("w-full bg-green-50"):
                ui.label(f"Generated bundle {res['bundle']}: {res['bundle_name']}") \
                    .classes("font-semibold")
                for d in res["documents"]:
                    ui.label(f"• {d.get('kind','doc')}: {d.get('docx','')}").classes("text-sm")
                if res["email_id"]:
                    ui.label("• Outreach email draft created — review it in Step 7.") \
                        .classes("text-sm text-blue-700")
                for note in res["notes"]:
                    ui.label("ℹ " + note).classes("text-sm text-amber-700")
                ui.label("A tracker row was created/updated in Step 8.").classes("text-xs text-gray-500")
        notify_ok("Bundle generated.")

    ui.button("Generate bundle", on_click=go).props("color=primary")

    ui.separator().classes("my-4")
    ui.label("Generated documents").classes("text-lg font-semibold")
    docs = db.rows("SELECT * FROM documents ORDER BY id DESC LIMIT 50")
    ui.table(columns=[{"name": k, "label": k.title(), "field": k, "align": "left"}
                      for k in ("doc_type", "title", "path", "created_at")],
             rows=docs, pagination=10).classes("w-full")


# ---------------------------------------------------------------- step 7: outreach

def step_outreach() -> None:
    from app.emailer import gmail_oauth, outlook_oauth
    from app.emailer.sender import daily_limit, send_draft, sent_today
    from app.tracker import mark_sent_from_email

    ui.label("Step 7 — Outreach (review, then send)").classes("text-2xl font-bold")
    ui.label(f"Semi-automatic by default: the app prepares drafts + attachments, you review "
             f"and approve each send. Daily limit {daily_limit()} ({sent_today()} sent today). "
             "Blind mass outreach is intentionally not supported.").classes("text-sm text-gray-500")
    lst = ui.column().classes("w-full")

    def render() -> None:
        lst.clear()
        drafts = db.rows(
            "SELECT e.*, p.title AS pos_title, p.university, s.name AS sup_name "
            "FROM email_log e LEFT JOIN positions p ON p.id=e.position_id "
            "LEFT JOIN supervisors s ON s.id=e.supervisor_id "
            "WHERE e.status='draft' ORDER BY e.id DESC")
        sent = db.rows("SELECT * FROM email_log WHERE status IN ('sent','failed') "
                       "ORDER BY id DESC LIMIT 30")
        with lst:
            ui.label(f"Prepared drafts ({len(drafts)}) — guided review") \
                .classes("text-lg font-semibold")
            for d in drafts:
                with ui.card().classes("w-full"):
                    ctx = " · ".join(filter(None, [d.get("pos_title") or "",
                                                   d.get("university") or "",
                                                   d.get("sup_name") or ""]))
                    if ctx:
                        ui.label(ctx).classes("text-sm text-indigo-700")
                    atts = json.loads(d.get("attachments") or "[]")
                    if atts:
                        ui.label("Attachments to send manually with this email: "
                                 + "; ".join(Path(a).name for a in atts)) \
                            .classes("text-xs text-gray-500")
                    to = ui.input("To", value=d["recipient"]).classes("w-full")
                    subj = ui.input("Subject", value=d["subject"]).classes("w-full")
                    body = ui.textarea("Body", value=d["body"]).classes("w-full").props("rows=10")

                    def make_send(d_id: int, to_w=to, s_w=subj, b_w=body):
                        async def do(provider: str) -> None:
                            db.execute("UPDATE email_log SET recipient=?, subject=?, body=? "
                                       "WHERE id=?", (to_w.value, s_w.value, b_w.value, d_id))
                            ok, msg = await run.io_bound(send_draft, d_id, provider)
                            if ok:
                                mark_sent_from_email(d_id)
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

                        def discard(d_id=d["id"]):
                            db.execute("UPDATE email_log SET status='discarded' WHERE id=?",
                                       (d_id,))
                            render()
                        ui.button("Discard", on_click=discard).props("flat color=red")
            ui.label("History").classes("text-lg font-semibold mt-4")
            ui.table(columns=[{"name": k, "label": k.title(), "field": k, "align": "left"}
                              for k in ("status", "provider", "recipient", "subject", "sent_at")],
                     rows=sent, pagination=10).classes("w-full")

    render()


# ---------------------------------------------------------------- step 8: tracker

def step_tracker() -> None:
    from app.tracker import STATUSES, add_note, overview, set_status

    ui.label("Step 8 — Tracker").classes("text-2xl font-bold")
    ui.label("One row per application/outreach. 'Sent' rows automatically become "
             "'reminder_due' after 14 days without a status change.") \
        .classes("text-sm text-gray-500")
    lst = ui.column().classes("w-full")

    def render() -> None:
        lst.clear()
        apps = overview()
        with lst:
            due = [a for a in apps if a["status"] == "reminder_due"]
            if due:
                with ui.card().classes("w-full bg-amber-50"):
                    ui.label(f"⏰ {len(due)} follow-up(s) due").classes("font-semibold")
            if not apps:
                ui.label("No tracked applications yet — generate a bundle in Step 6 "
                         "to create tracker rows automatically.").classes("text-gray-500")
            for a in apps:
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label(f"{a['program'][:60]} — {a['university']} "
                                 f"({a['country'] or '?'})").classes("font-semibold")
                        color = {"draft": "grey", "ready": "blue", "sent": "indigo",
                                 "reminder_due": "orange", "replied": "green",
                                 "no_response": "grey", "interview": "purple",
                                 "rejected": "red", "admitted": "green"}.get(a["status"], "grey")
                        ui.badge(a["status"]).props(f"color={color}")
                    detail = " · ".join(filter(None, [
                        a.get("supervisor_name") or "", a.get("faculty") or "",
                        a.get("classification") or "",
                        f"sent {a['sent_at'][:10]}" if a.get("sent_at") else "",
                        f"follow-up {a['follow_up_due']}" if a.get("follow_up_due") else "",
                    ]))
                    ui.label(detail).classes("text-sm text-gray-600")
                    if a.get("notes"):
                        ui.label(a["notes"]).classes("text-xs text-gray-500 whitespace-pre-line")
                    atts = json.loads(a.get("attachments") or "[]")
                    if atts:
                        ui.label("Documents: " + "; ".join(Path(x).name for x in atts)) \
                            .classes("text-xs text-gray-400")
                    with ui.row().classes("items-center gap-2"):
                        st = ui.select(STATUSES, value=a["status"], label="Status") \
                            .classes("w-44").props("dense")

                        def apply_status(aid=a["id"], w=st):
                            set_status(aid, w.value)
                            notify_ok("Status updated.")
                            render()
                        ui.button("Update", on_click=apply_status).props("dense outline")
                        note = ui.input("Add note").classes("w-64").props("dense")

                        def save_note(aid=a["id"], w=note):
                            if w.value.strip():
                                add_note(aid, w.value.strip())
                                notify_ok("Note added.")
                                render()
                        ui.button("Note", on_click=save_note).props("dense flat")

    ui.button("Refresh", on_click=render).props("outline")
    render()


# ---------------------------------------------------------------- settings & logs (kept from v1)

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
    ("1 · Profile", "upload_file", step_profile),
    ("2 · Search", "search", step_search),
    ("3 · Classify & Shortlist", "rule", step_classify),
    ("4 · Supervisors", "school", step_supervisors),
    ("5 · Fit", "join_inner", step_fit),
    ("6 · Documents", "description", step_documents),
    ("7 · Outreach", "mail", step_outreach),
    ("8 · Tracker", "table_view", step_tracker),
    ("Settings", "settings", settings_page),
    ("Logs / Manual Review", "bug_report", logs_page),
]


@ui.page("/")
def index() -> None:
    ui.colors(primary=ACCENT)
    with ui.header().classes("items-center"):
        ui.label("🎓 PhD & Postdoc Supervisor Finder v2 — Europe").classes("text-lg font-bold")
    with ui.left_drawer(value=True).classes("bg-gray-50") as drawer:
        pass

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
    log.info("Starting PhD & Postdoc Supervisor Finder v2")

    @ng_app.on_connect
    def _on_connect(client) -> None:
        log.info("client connected (websocket up): %s", getattr(client, "id", "?"))

    @ng_app.on_disconnect
    def _on_disconnect(client) -> None:
        log.info("client disconnected: %s", getattr(client, "id", "?"))

    @ng_app.on_exception
    def _on_exception(exc: Exception) -> None:
        log.exception("unhandled app exception: %s", exc)

    @ng_app.on_startup
    def _on_startup() -> None:
        log.info("NiceGUI startup complete; server ready for connections")

    show = os.environ.get("PPSF_NO_SHOW") != "1"
    ui.run(title="PhD & Postdoc Supervisor Finder v2", host="127.0.0.1", port=8765,
           reload=False, show=show, favicon="🎓")


if __name__ in {"__main__", "__mp_main__"}:
    main()
