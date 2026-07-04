# Usage guide

## 1. Install & launch

**Windows:** run `scripts\install_windows.bat` once, then use the **PhD Supervisor Finder**
desktop icon. (Manual launch: `scripts\run_windows.bat`.)

**macOS/Linux:** `bash scripts/install_unix.sh`, then `./run.sh`. On Linux a menu entry
"PhD Supervisor Finder" is created. On macOS you can wrap `run.sh` in an Automator app to
get a Dock/desktop icon.

The app opens in your browser at `http://127.0.0.1:8765` — it is a local program, not a website.

## 2. Upload your CV

Upload CV page → drop a PDF or DOCX. Review the warnings and the editable profile fields;
fix anything the parser got wrong and click **Save profile**. Set your **target level**
(PhD / Postdoc / Research Fellow) and **target countries** (ISO codes like GB, DE, AU).

## 3. Research interests

Check the auto-extracted interests, add or refine them (one per line). These drive both
search defaults and match scores.

## 4. Search

- **Search Open Positions**: pick sources, click Search. Results are cached and stored with
  source URL + access date. If a site's layout changed, you'll see a note in Logs.
- **Find Supervisors**: queries OpenAlex + Semantic Scholar. Then click
  **Fetch publications** so matches and emails can cite real, verified papers.

## 5. Match

Match Results → **Run matching**. Every card shows the score, *why* it matched, risk
warnings (missing deadline, no public email, level mismatch…), a suggested email angle,
and the source link. Low-confidence matches are labelled.

## 6. Generate documents

- **Tailored CV** — DOCX + PDF from your saved profile only.
- **Research proposal** — enter a topic, pick a citation style (APA 7 / Harvard / Chicago /
  IEEE), optionally align with a stored supervisor. References are fetched from
  OpenAlex/Semantic Scholar and re-verified via Crossref; a `*_SOURCE_AUDIT.md` file lists
  every reference's verification status. Unverified items are excluded automatically.
- **Timeline** — 3-year PhD, 4-year PhD, or 2-year postdoc plan.
- **Outreach email** — creates a *draft* (never auto-sends).

All files land in `~/.phd_finder/generated/` (path shown in the UI).

## 7. Send emails

Settings → enter your Google and/or Microsoft OAuth client details (see
[SECURITY.md](SECURITY.md) for the 5-minute setup) → **Connect Gmail/Outlook**.
Email Outreach page → edit each draft → send. Defaults: manual review required,
10 emails/day maximum, everything logged.

## 8. Logs / Manual Review

Check this page regularly: failed scrapes, unverifiable references, CV-parsing warnings and
low-confidence data all appear here with a **Mark resolved** button.
