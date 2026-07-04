# Security & data privacy

## Where your data lives

Everything is stored locally in `~/.phd_finder/` (Windows: `C:\Users\<you>\.phd_finder\`):
`app.db` (SQLite), `generated/` documents, `cache/` of web responses, `app.log`.
Delete that folder and everything is gone. Nothing is uploaded anywhere except the API
calls you configure (OpenAlex/Semantic Scholar/Crossref queries, optional LLM, optional
email sending).

## Secrets

- OAuth tokens are stored in the **OS keychain** (Windows Credential Manager / macOS
  Keychain / Secret Service) via `keyring`. If no keychain is available, tokens are
  **encrypted with Fernet** using a locally generated key (`~/.phd_finder/.secret.key`).
- **Revoke/delete tokens** anytime: Settings → "Revoke / delete tokens". Also revoke app
  access at https://myaccount.google.com/permissions and https://account.live.com/consent/Manage.
- Log output passes through a redaction filter that masks anything shaped like a token.
- `.gitignore` excludes `.env`, `*.enc`, `.secret.key`, `*.db`, `*.log`. Never commit them.
- No secrets are hardcoded anywhere; `.env.example` contains placeholders only.

## Setting up OAuth clients (one-time, free)

**Gmail:** Google Cloud Console → create project → enable Gmail API → OAuth consent screen
(External, add yourself as test user) → Credentials → *OAuth client ID → Desktop app* →
copy Client ID/Secret into Settings. Scope used: `gmail.send` only (the app cannot read
your mail).

**Outlook:** entra.microsoft.com → App registrations → New (accounts: personal + org) →
Authentication → *Allow public client flows: Yes* → API permissions → delegated
`Mail.Send` → copy Application (client) ID into Settings. Sign-in uses the device-code
flow. Scope used: `Mail.Send` only.

## LLM privacy note

If you set an LLM key, parts of your profile and the target supervisor's public metadata
are sent to that provider to improve wording. Skip the key to keep everything offline
(template mode).

## Responsible use

Scraping is rate-limited, cached, and robots.txt-aware. Email sending requires per-message
manual review and is capped per day. Please keep it that way — mass-emailing academics is
counterproductive and may violate provider terms and anti-spam law (CAN-SPAM/GDPR/PECR).
