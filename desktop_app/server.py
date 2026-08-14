"""Local-only FastAPI app for driving proposal_engine from a browser.

Bind to 127.0.0.1 only. No auth (local use). It calls the existing pipeline via
``desktop_app.jobs`` and never shells out. The Stop endpoint asks the running
uvicorn server to exit cleanly (it sets a flag — it does NOT run any OS command
and never touches unrelated processes).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# Load .env once at import — before any /api/generate spawns a worker thread —
# so the pipeline's model key is present and consistent for every request.
# override=True makes .env authoritative: a stale OPENAI_API_KEY left in the
# process environment cannot mask the key the user configured in .env.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from . import jobs

APP_DIR = Path(__file__).resolve().parent
INDEX_HTML = APP_DIR / "index.html"
UPLOAD_DIR = jobs.DEFAULT_OUT / "_uploads"

app = FastAPI(title="Proposal Engine — Local")
# app.state.server is set by launch.py to the running uvicorn Server (may be None
# under TestClient); stop_requested lets tests observe the intent without a server.
app.state.server = None
app.state.stop_requested = False


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if INDEX_HTML.is_file():
        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Proposal Engine</h1><p>index.html missing.</p>")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": "proposal-engine-local"}


@app.post("/api/upload")
async def upload_cv(file: UploadFile = File(...)) -> JSONResponse:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "cv").name  # strip any directory components
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(await file.read())
    return JSONResponse({"path": str(dest.resolve()), "name": safe_name})


@app.post("/api/generate")
async def generate(
    topics: str = Form(...),
    config_path: str = Form(""),
    out_dir: str = Form(""),
    cv_path: str = Form(""),
    force: bool = Form(True),
) -> JSONResponse:
    job_id = jobs.start_job(topics_raw=topics, config_path=config_path or None,
                            out_dir=out_dir or None, cv_path=cv_path or None,
                            force=force)
    return JSONResponse({"job_id": job_id})


@app.get("/api/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse(jobs.job_dict(job))


@app.get("/api/download/{job_id}/{topic_id}/{kind}")
def download(job_id: str, topic_id: str, kind: str) -> FileResponse:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if kind not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="kind must be docx or pdf")
    ts = next((t for t in job.topics if t.id == topic_id), None)
    if ts is None:
        raise HTTPException(status_code=404, detail="topic not found")
    # Path comes from the engine's own output (not user input) -> no traversal risk.
    path = ts.docx if kind == "docx" else ts.pdf
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail=f"{kind} not available")
    return FileResponse(path, filename=Path(path).name)


@app.post("/api/stop")
def stop(request: Request) -> JSONResponse:
    """Ask the local server to shut down cleanly. No OS commands are run and no
    other process is affected — this only flips uvicorn's should_exit flag."""
    request.app.state.stop_requested = True
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
    return JSONResponse({"stopping": True})
