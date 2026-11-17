"""Logging to <home>/logs/clinic.log (rotating) and stderr."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    # Avoid stacking handlers when the app is created several times (tests).
    for h in list(root.handlers):
        if getattr(h, "_clinic", False):
            root.removeHandler(h)
            h.close()
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(_FMT))
    fh._clinic = True  # type: ignore[attr-defined]
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(_FMT))
    sh._clinic = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    root.addHandler(sh)
    root.setLevel(level)
