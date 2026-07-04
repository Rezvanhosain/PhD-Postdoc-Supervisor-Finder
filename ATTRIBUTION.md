# Attribution & open-source notices

This project deliberately builds on mature open-source libraries and free public APIs
rather than reinventing them. Thank you to all maintainers.

## Libraries (installed via pip)

| Library | Purpose here | License |
|---|---|---|
| [NiceGUI](https://github.com/zauberzeug/nicegui) | Desktop-style local web UI | MIT |
| [httpx](https://github.com/encode/httpx) | All HTTP/API calls | BSD-3-Clause |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | PDF CV text extraction | MIT |
| [docx2txt](https://github.com/ankushshah89/python-docx2txt) | DOCX CV text extraction | MIT |
| [python-docx](https://github.com/python-openxml/python-docx) | DOCX document generation | MIT |
| [fpdf2](https://github.com/py-pdf/fpdf2) | PDF document generation | LGPL-3.0 (used unmodified as a library) |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) | TF-IDF matching | BSD-3-Clause |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + lxml | Job-board HTML parsing | MIT / BSD |
| [google-auth-oauthlib / google-auth](https://github.com/googleapis/google-auth-library-python) | Gmail OAuth | Apache-2.0 |
| [MSAL for Python](https://github.com/AzureAD/microsoft-authentication-library-for-python) | Outlook OAuth (device code) | MIT |
| [keyring](https://github.com/jaraco/keyring) | OS keychain token storage | MIT |
| [cryptography](https://github.com/pyca/cryptography) | Encrypted token fallback | Apache-2.0/BSD |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | .env support | BSD-3-Clause |
| [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) | Fuzzy string utilities | MIT |
| [pytest](https://github.com/pytest-dev/pytest) | Tests | MIT |

## Public data APIs (no scraping, official endpoints)

- **[OpenAlex](https://openalex.org)** — author & work metadata. CC0 data. We send a
  `mailto:` User-Agent per their polite-pool guidance.
- **[Semantic Scholar Graph API](https://api.semanticscholar.org)** — authors/papers,
  free tier; optional API key supported. Subject to their API terms.
- **[Crossref REST API](https://api.crossref.org)** — DOI verification. Open metadata.

## Websites accessed via best-effort polite scraping

EURAXESS, FindAPhD, AcademicPositions.com, Times Higher Education Jobs — accessed with
robots.txt checks, ≥1.5 s per-host rate limiting, 24 h caching, and an identifying
User-Agent. Parsers are best-effort and fail into the Manual Review log; users should
always follow the stored source URL to the original advert.

## Design inspiration

Approach informed by existing open-source projects such as `pyalex` (OpenAlex clients)
and Semantic Scholar API examples; all code in this repository was written for this
project — no source code was copied from other repositories.
