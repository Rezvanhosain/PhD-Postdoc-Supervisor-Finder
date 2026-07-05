# 🎓 PhD & Postdoc Supervisor Finder

[![CI](https://github.com/Rezvanhosain/PhD-Postdoc-Supervisor-Finder/actions/workflows/ci.yml/badge.svg)](https://github.com/Rezvanhosain/PhD-Postdoc-Supervisor-Finder/actions/workflows/ci.yml)

**v2 — a Europe-only, workflow-chained** local desktop app for finding and pursuing
supervisor-first PhDs, direct-application PhDs, and postdocs. Instead of disconnected
tabs, v2 is a guided pipeline where each step operates only on what you selected in the
previous one:

1. **Profile** — upload CV, set research interests
2. **Search** — Europe-only opportunities (EURAXESS, FindAPhD, Academic Positions, THE Jobs)
   with field / keyword / country / PhD-vs-postdoc / university filters
3. **Classify & shortlist** — every opportunity is classified into an admission path
   (*supervisor contact mandatory · recommended · direct application · named-PI postdoc ·
   open-call postdoc*) with confidence, evidence snippet, and source URL. Official
   university pages override third-party portals. You then shortlist your targets.
4. **Supervisors** — found **only at your shortlisted universities**: official
   staff/faculty/doctoral-school pages first, plus OpenAlex authors hard-filtered to that
   institution. No generic unrelated results.
5. **Fit** — explainable scores for each opportunity/supervisor pair (topic similarity,
   level, country, deadline urgency, whether outreach is required or useful)
6. **Documents** — the *right* bundle per admission path: supervisor-first PhD (CV +
   supervisor email + concept note), direct-application PhD (CV + statement of purpose
   [+ proposal/optional email]), postdoc (CV + cover letter + research statement).
   References are **verified only** (Crossref/OpenAlex) with a source-audit file.
7. **Outreach** — semi-automatic: drafts + attachments prepared, you review and approve
   each send (Gmail/Outlook OAuth, daily limit, full log). No blind mass mail.
8. **Tracker** — lightweight CRM: statuses (draft → sent → replied/interview/admitted…),
   notes, attachment history, automatic 14-day follow-up reminders.

Everything runs **on your own computer**. Your CV, profile, and tokens never leave your machine
except for the API calls you explicitly configure.

![Dashboard](assets/screenshot_dashboard.png)

## Quick start (Windows)

1. Install [Python 3.10+](https://python.org) (tick **"Add Python to PATH"**).
2. Download / clone this repository.
3. Double-click **`scripts\install_windows.bat`** — it creates a virtual environment,
   installs dependencies, and puts a **"PhD Supervisor Finder"** icon on your Desktop.
4. Double-click the desktop icon. The app opens in your browser (it is still 100% local).

macOS/Linux: `bash scripts/install_unix.sh`, then `./run.sh` (a Linux desktop entry is created
automatically). See [docs/USAGE.md](docs/USAGE.md).

## How classification works (explainability)

For every opportunity the app stores: the admission-path **label**, a **confidence**,
the exact **evidence text** that triggered it, the **source URL**, and whether that
source is **official or third-party**. When an official page and a portal disagree, the
official page wins. Low-confidence classifications are flagged in *Logs / Manual Review*
and can be corrected by hand (edit university/country/deadline directly in Step 3).

## Works without any API keys (limited mode)

CV parsing, position search, supervisor search (OpenAlex/Semantic Scholar are free), keyword
matching, timelines, template-based CV/proposal/email drafting all work with **zero keys**.

Optional keys (Settings page or `.env` — see [`.env.example`](.env.example)):

- **OpenAI-compatible LLM key** → better wording in CV summaries, proposal sections, emails
  (facts are never invented; prompts forbid adding citations or achievements)
- **Google / Microsoft OAuth client** → send email directly from the app
- **Semantic Scholar key** → higher API rate limits

## What it does NOT do (known limitations)

- It does **not** auto-apply to positions or auto-send emails — you review and send each one.
- It does **not** bypass logins, paywalls, or CAPTCHAs, and it will not scrape a site whose
  robots.txt disallows it (those are logged under *Logs / Manual Review* instead).
- It does **not** invent citations, DOIs, or supervisor publications (see below).
- Job-board scrapers are best-effort — sites change their HTML and some block bots, so
  position search can return 0 results; supervisor search (OpenAlex/Semantic Scholar APIs) is
  the reliable path.
- The built-in PDF font is Latin-1; for non-Latin scripts use the DOCX output.
- Supervisor email addresses are rarely public — the app flags this rather than guessing.

## Sending email via Gmail / Outlook

Sending is optional. Create a free OAuth client once (Google Cloud Console for Gmail,
Entra/Azure for Outlook), paste the Client ID/Secret into **Settings**, then click *Connect*.
Gmail uses the `gmail.send` scope only and Outlook uses `Mail.Send` only — the app can send
but cannot read your mailbox. Step-by-step setup is in [docs/SECURITY.md](docs/SECURITY.md).
Tokens are stored in your OS keychain (encrypted-file fallback) and never printed to logs.

## Anti-hallucination guarantees

- References come **only** from OpenAlex / Semantic Scholar / Crossref metadata.
- Every DOI is re-verified against Crossref; failures are excluded and flagged.
- Each proposal ships with a `*_SOURCE_AUDIT.md` table showing every reference's source API,
  DOI, and VERIFIED / NEEDS MANUAL REVIEW status.
- Outreach emails cite a supervisor's publication only if it was fetched from OpenAlex.
- The LLM (if enabled) is instructed to use `[FILL IN]` placeholders rather than invent facts.

## Documentation

- [Usage guide](docs/USAGE.md) · [Architecture](docs/ARCHITECTURE.md) ·
  [Troubleshooting](docs/TROUBLESHOOTING.md) · [Security & privacy](docs/SECURITY.md)
- [ATTRIBUTION.md](ATTRIBUTION.md) — open-source libraries used and their licenses

## Tech stack

Python 3.10+ · [NiceGUI](https://nicegui.io) UI · SQLite · httpx · pdfplumber / docx2txt ·
python-docx + fpdf2 · scikit-learn (TF-IDF) · google-auth-oauthlib · MSAL · keyring + cryptography

## Ethics

This is a *personal research assistant*, not a spam tool: one email at a time, manual review
before sending, a daily send limit (default 10), polite scraping with robots.txt checks and
rate limiting, and a contact email in API User-Agent headers.

## License

[MIT](LICENSE)
