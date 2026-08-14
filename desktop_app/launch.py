"""Start the local desktop app: pick a free port, write a PID file, launch
uvicorn on 127.0.0.1, and open the browser. Stopping is handled cleanly either
by the in-app Stop button (uvicorn should_exit) or the Stop .bat (PID file)."""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
REPO_ROOT = Path(__file__).resolve().parent.parent
PID_FILE = REPO_ROOT / ".proposal_engine_app.pid"


def _free_port(start: int, tries: int = 20) -> int:
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, p)) != 0:  # nothing listening -> free
                return p
    return start


def _wait_and_open(url: str, port: int) -> None:
    for _ in range(100):  # up to ~10s
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) == 0:
                break
        time.sleep(0.1)
    try:
        webbrowser.open(url)
    except Exception:
        pass  # browser is a convenience; the URL is printed regardless


def main() -> None:
    # Relative paths in the engine (examples/config.yaml, proposal_engine_out)
    # resolve against the repo root regardless of where the launcher was invoked.
    os.chdir(REPO_ROOT)
    # Load .env ONCE, before any worker thread is spawned, so every request the
    # server handles sees a consistent, fully-loaded environment.
    try:
        from dotenv import load_dotenv
        # override=True: .env is authoritative for the local app, so a stale
        # key in the process environment cannot mask the configured one.
        load_dotenv(REPO_ROOT / ".env", override=True)
    except ImportError:
        pass
    port = _free_port(DEFAULT_PORT)
    url = f"http://{HOST}:{port}"

    # Import after chdir so package resolution is stable.
    from .server import app

    PID_FILE.write_text(f"{os.getpid()}\n{port}\n", encoding="utf-8")
    print(f"Proposal Engine (local) -> {url}")
    print("Close this window or click 'Stop Local App' in the browser to quit.")

    config = uvicorn.Config(app, host=HOST, port=port, log_level="info")
    server = uvicorn.Server(config)
    app.state.server = server
    threading.Thread(target=_wait_and_open, args=(url, port), daemon=True).start()
    try:
        server.run()
    finally:
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
