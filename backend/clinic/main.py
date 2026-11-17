"""FastAPI application factory and the local server entry point."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, Paths, default_home
from .logging_setup import setup_logging
from .services.backup_service import BackupError, BackupService
from .services.common import Conflict, NotFound, ValidationFailed
from .state import AppState

log = logging.getLogger("clinic")

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
# What a phone (any non-loopback client) may reach.
REMOTE_ALLOWED = (
    "/mobile", "/api/health", "/api/system/status", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    "/api/mobile/", "/api/sync/pair", "/api/sync/push", "/api/sync/pull", "/api/sync/files",
)


def _ui_dir() -> Path | None:
    """Built React UI, if present (lets the app run in a normal browser too)."""
    env = os.environ.get("CLINIC_UI_DIR")
    candidates = [Path(env)] if env else []
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    candidates += [base / "ui", base / "desktop" / "dist", Path(__file__).resolve().parents[2] / "desktop" / "dist"]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


def auto_backup_tick(state: AppState) -> str | None:
    hours = state.settings.auto_backup_hours
    if not hours or state.db is None or state.data_key is None:
        return None
    svc = BackupService(state.paths, state.keystore)
    age = svc.last_backup_age_hours()
    if age is not None and age < hours:
        return None
    with state.lock:
        if state.db is None:
            return None
        path = svc.create_backup(state.data_key, "auto")
        svc.prune(state.settings.backup_retention)
    return path.name


def _backup_loop(state: AppState, stop: threading.Event) -> None:
    while not stop.wait(600):
        try:
            name = auto_backup_tick(state)
            if name:
                log.info("automatic backup %s", name)
        except Exception:
            log.exception("automatic backup failed")


def _parent_alive(pid: int) -> bool:
    """True unless we can positively tell that process ``pid`` has ended."""
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        SYNCHRONIZE = 0x00100000
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            # 87 = ERROR_INVALID_PARAMETER: no such process. Anything else
            # (e.g. access denied) is not proof that the shell has gone.
            return ctypes.get_last_error() != 87
        try:
            return k32.WaitForSingleObject(h, 0) != 0  # 0 = WAIT_OBJECT_0: process ended
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _parent_watchdog(pid: int) -> None:
    """Exit when the desktop shell that started us has gone away (three
    consecutive checks, so a transient error never stops the server)."""
    misses = 0
    while True:
        time.sleep(2)
        try:
            alive = _parent_alive(pid)
        except Exception:  # never let the watchdog itself kill the server
            log.exception("parent check failed")
            alive = True
        misses = 0 if alive else misses + 1
        if misses >= 3:
            log.info("desktop shell (pid %s) exited; stopping server", pid)
            os._exit(0)


def create_app(home: Path | None = None, background: bool = True) -> FastAPI:
    paths = Paths(home or default_home())
    paths.ensure()
    setup_logging(paths.log_file)
    state = AppState(paths)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("%s %s starting, data in %s", APP_NAME, APP_VERSION, paths.home)
        if background:
            threading.Thread(target=_backup_loop, args=(state, stop), daemon=True, name="auto-backup").start()
        yield
        stop.set()
        state.close_database()
        log.info("server stopped")

    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.clinic = state

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(tauri://localhost|https?://tauri\.localhost|http://(localhost|127\.0\.0\.1)(:\d+)?)$",
        allow_methods=["*"],
        allow_headers=["*"],
        # WebView2/Chromium send a Private Network Access preflight when the
        # app page (tauri.localhost) calls the local server; without this the
        # server answers 400 and the UI shows "Cannot reach the server".
        allow_private_network=True,
    )

    @app.middleware("http")
    async def restrict_remote(request: Request, call_next):
        host = request.client.host if request.client else ""
        remote = host not in LOCAL_HOSTS
        request.state.remote = remote
        if remote and not request.url.path.startswith(REMOTE_ALLOWED):
            return JSONResponse({"detail": "Not available over the network"}, status_code=403)
        if remote and request.url.path.startswith("/api/mobile/") and request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "Read-only"}, status_code=405)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        return response

    @app.exception_handler(NotFound)
    async def _nf(_, e):
        return JSONResponse({"detail": str(e) or "Not found"}, status_code=404)

    @app.exception_handler(ValidationFailed)
    async def _vf(_, e):
        return JSONResponse({"detail": str(e)}, status_code=422)

    @app.exception_handler(Conflict)
    async def _cf(_, e):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(BackupError)
    async def _be(_, e):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, e: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Unexpected error. See logs/clinic.log."}, status_code=500)

    from .api import clinical, sync, system

    app.include_router(system.router)
    app.include_router(clinical.router)
    app.include_router(sync.router)

    @app.get("/mobile", include_in_schema=False)
    def mobile_page():
        html = resources.files("clinic.mobile").joinpath("index.html").read_text("utf-8")
        return HTMLResponse(html)

    ui = _ui_dir()
    if ui:
        app.mount("/assets", StaticFiles(directory=ui / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            f = (ui / path).resolve()
            if path and f.is_file() and ui.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(ui / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse("/api/docs")

    return app


def run() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Clinic Records local server")
    ap.add_argument("--home", help="data folder (default: %(default)s)", default=str(default_home()))
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None, help="override bind address")
    ap.add_argument("--parent-pid", type=int, default=None, help="exit when this process exits")
    args = ap.parse_args()

    home = Path(args.home)
    app = create_app(home)
    state: AppState = app.state.clinic
    port = args.port or state.settings.port
    host = args.host or ("0.0.0.0" if state.settings.network_access else "127.0.0.1")
    if args.parent_pid:
        threading.Thread(target=_parent_watchdog, args=(args.parent_pid,), daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)


if __name__ == "__main__":
    run()
