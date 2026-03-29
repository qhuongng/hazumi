import json
import logging
import os
from typing import Any


_TRUE_VALUES = {"1", "true", "yes", "on", "y", "enabled", "enable"}
_configured = False
_last_debug: bool | None = None


def debug_enabled() -> bool:
    value = str(os.getenv("DEBUG_MODE", "0")).strip().lower()
    return value in _TRUE_VALUES


def _apply_levels(debug: bool):
    root = logging.getLogger()

    # Keep third-party internals quiet in both modes.
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # App logs are only verbose when DEBUG_MODE is enabled.
    app_level = logging.DEBUG if debug else logging.WARNING
    logging.getLogger("core").setLevel(app_level)
    logging.getLogger("helpers").setLevel(app_level)
    logging.getLogger("tools").setLevel(app_level)

    # Keep root reasonably quiet unless debugging.
    root.setLevel(logging.INFO if debug else logging.WARNING)


def _configure_once():
    global _configured, _last_debug
    if _configured:
        return

    debug = debug_enabled()
    _last_debug = debug

    root = logging.getLogger()

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)

    _apply_levels(debug)

    _configured = True


def refresh_logging_config():
    global _last_debug
    _configure_once()
    debug = debug_enabled()
    if _last_debug != debug:
        _apply_levels(debug)
        _last_debug = debug


def get_logger(name: str) -> logging.Logger:
    refresh_logging_config()
    return logging.getLogger(name)


def log_debug_json(logger: logging.Logger, event: str, payload: Any):
    if not debug_enabled():
        return

    try:
        body = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        body = f"<failed to serialize payload: {exc}>"

    logger.debug("%s %s", event, body)
