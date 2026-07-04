# Troubleshooting

**Installer says Python not found** — install Python 3.10+ from python.org and tick
*Add Python to PATH*, then re-run `scripts\install_windows.bat`.

**Desktop icon does nothing** — run `scripts\run_windows.bat` to see the error in a console.
Most common cause: dependencies failed to install (re-run the installer).

**Browser doesn't open / "connection refused"** — the app may still be starting (10–20 s
first time), or port 8765 is taken. Open `http://127.0.0.1:8765` manually, or close the
other program using the port.

**CV parsed badly** — scanned/image PDFs contain no extractable text. Export your CV to
DOCX or a text-based PDF, or just edit the profile fields manually and Save.

**Position search returns 0 results** — job boards change their HTML often and some block
automated access via robots.txt (which this app respects). Check *Logs / Manual Review*
for the reason. Supervisor search (OpenAlex/Semantic Scholar) uses stable official APIs
and should always work.

**Semantic Scholar errors / 429** — the free tier is rate limited. Add a (free) API key in
Settings, or just rely on OpenAlex.

**Gmail "app not verified" warning** — expected for a personal OAuth client in testing
mode; click *Advanced → Continue* (you are the developer and the only user).

**Outlook connect hangs** — the device-code dialog shows a code and URL; you must complete
sign-in in your browser within ~15 minutes. Ensure *Allow public client flows* is enabled
on your app registration.

**"Daily send limit reached"** — safety feature. Wait until tomorrow or raise the limit in
Settings (be considerate).

**PDF output shows odd characters** — the built-in PDF font is Latin-1; non-Latin scripts
are replaced. Use the DOCX version for full Unicode.

**Where are logs?** — `~/.phd_finder/app.log`, plus the in-app Logs page.

**Reset everything** — close the app and delete the `~/.phd_finder` folder.
