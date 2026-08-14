# Proposal Engine — Local Desktop App

A small local browser UI around the existing `proposal_engine` pipeline. It runs
only on your machine (`http://127.0.0.1:8765`), needs no login, and does not host
anything publicly. It does **not** change how proposals are generated — it just
drives the same pipeline the CLI uses.

## How to run without command line

1. **Double-click the desktop shortcut** *(or `Start Proposal Engine.bat` in the
   project folder)*. A small console window opens and your browser opens
   automatically at `http://127.0.0.1:8765`.
2. **Use the form:**
   - *Candidate CV / profile* — optionally choose a PDF/DOCX/TXT.
   - *Research topics* — type one topic per line (optionally `id | Title`).
   - *Config file* — leave blank for the default, or point to your `config.yaml`.
   - *Output folder* — leave blank for `proposal_engine_out`.
   - Click **Generate Proposals**. Progress and any citation/quality warnings
     appear per topic.
3. **Download / open** each proposal with the **⬇ DOCX** and **⬇ PDF** buttons
   shown when a topic finishes.
4. **Click “■ Stop Local App”** in the browser when you are done (or just close
   the console window). You can also double-click `Stop Proposal Engine.bat`.

> First launch may take a minute if Python packages need installing. Later
> launches start immediately.

## Create the desktop shortcut (one time)

- Open the project folder `E:\AI Projects\PhD-Postdoc-Supervisor-Finder`.
- **Right-click `Start Proposal Engine.bat` → Send to → Desktop (create shortcut)**.
- Rename the desktop shortcut to **“Proposal Engine”**.
- *(Optional)* Right-click the shortcut → **Properties → Change Icon…** to pick an icon.

Double-clicking that shortcut is now all you need.

## What the launchers do

- **`Start Proposal Engine.bat`** — uses a local `.venv` if present (else system
  Python), installs requirements only if something is missing, then starts the
  app. The app loads `.env` automatically and opens the browser.
- **`Stop Proposal Engine.bat`** — stops **only** this app, using the PID stored
  in `.proposal_engine_app.pid` (it never touches unrelated Python processes).

## Files

```
desktop_app/
  server.py     FastAPI app (routes, safe file download, clean stop)
  jobs.py       background runner that calls the existing pipeline
  launch.py     picks a free port, writes the PID file, opens the browser
  index.html    the browser UI
Start Proposal Engine.bat
Stop Proposal Engine.bat
```
