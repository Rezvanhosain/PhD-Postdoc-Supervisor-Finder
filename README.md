# 🎓 PhD & Postdoc Supervisor Finder

A **local desktop app** that helps you find open PhD/postdoc positions and suitable academic
supervisors — especially in business, accounting, finance, management, leadership, education,
social sciences, NGO/nonprofit studies, public policy, and development studies — then helps you
generate a tailored CV, a research proposal with **verified references only**, a project
timeline, and a professional outreach email you can send via Gmail or Outlook.

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

## What it does

| Section | What happens |
|---|---|
| Upload CV | PDF/DOCX parsing → editable profile (name, education, publications, skills…) |
| Research Interests | The keywords that drive search & matching |
| Search Open Positions | EURAXESS, FindAPhD, Academic Positions, THE Jobs (polite scraping: robots.txt, rate limits, caching) |
| Find Supervisors | OpenAlex + Semantic Scholar APIs (free, no key needed) |
| Match Results | Explainable scores: TF-IDF similarity (+optional embeddings), country/level fit, deadline urgency, with "why" and "risks" |
| Generate Documents | ATS-friendly CV (DOCX+PDF), research proposal with **Crossref-verified references + source audit file**, 3/4-year PhD & 2-year postdoc timelines, outreach email drafts |
| Email Outreach | Manual review required, daily send limit, Gmail/Outlook OAuth, full send log |
| Logs / Manual Review | Failed scrapes, unverifiable references, low-confidence data |

## Works without any API keys (limited mode)

CV parsing, position search, supervisor search (OpenAlex/Semantic Scholar are free), keyword
matching, timelines, template-based CV/proposal/email drafting all work with **zero keys**.

Optional keys (Settings page or `.env` — see [`.env.example`](.env.example)):

- **OpenAI-compatible LLM key** → better wording in CV summaries, proposal sections, emails
  (facts are never invented; prompts forbid adding citations or achievements)
- **Google / Microsoft OAuth client** → send email directly from the app
- **Semantic Scholar key** → higher API rate limits

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
