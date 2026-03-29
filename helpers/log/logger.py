import json
import logging
import os
from pathlib import Path
from typing import Any


_TRUE_VALUES = {"1", "true", "yes", "on", "y", "enabled", "enable"}
_configured = False
_last_debug: bool | None = None
_log_config: dict | None = None


def debug_enabled() -> bool:
    """Check if DEBUG_MODE is enabled via environment variable."""
    value = str(os.getenv("DEBUG_MODE", "0")).strip().lower()
    return value in _TRUE_VALUES


def _load_log_config() -> dict:
    """Load logging configuration from config.json."""
    global _log_config
    if _log_config is not None:
        return _log_config

    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        _log_config = {"logging": {}}
        return _log_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            _log_config = config
            return _log_config
    except Exception:
        _log_config = {"logging": {}}
        return _log_config


def should_log(category: str) -> bool:
    """
    Check if logging is enabled for a specific category.
    Categories are defined in config.json under "logging".
    Returns False if DEBUG_MODE is off, otherwise checks config.json.
    """
    if not debug_enabled():
        return False

    config = _load_log_config()
    return config.get("logging", {}).get(category, False)


def _apply_levels(debug: bool):
    root = logging.getLogger()

    # keep third-party internals quiet in both modes
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # app logs are only verbose when DEBUG_MODE is enabled
    app_level = logging.DEBUG if debug else logging.WARNING
    logging.getLogger("core").setLevel(app_level)
    logging.getLogger("helpers").setLevel(app_level)
    logging.getLogger("tools").setLevel(app_level)

    # keep root reasonably quiet unless debugging
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


def log_tool_use(logger: logging.Logger, event: str, data: Any):
    """Log tool invocation and results if tool_use logging is enabled."""
    if not should_log("tool_use"):
        return

    try:
        body = json.dumps(data, ensure_ascii=False, default=str, indent=2)
    except Exception as exc:
        body = f"<failed to serialize: {exc}>"

    logger.debug("[TOOL] %s\n%s", event, body)


def log_messages(logger: logging.Logger, messages: list[dict]):
    """Log the entire messages array before sending to LLM if messages logging is enabled."""
    if not should_log("messages"):
        return

    try:
        body = json.dumps(messages, ensure_ascii=False, default=str, indent=2)
    except Exception as exc:
        body = f"<failed to serialize: {exc}>"

    logger.debug("[MESSAGES]\n%s", body)


def log_prompt(logger: logging.Logger, system_prompt: str, context_note: str = ""):
    """Log the system prompt and Discord context if prompt logging is enabled."""
    if not should_log("prompt"):
        return

    separator = "\n" + "=" * 80 + "\n"
    output = f"[SYSTEM PROMPT]{separator}{system_prompt}"

    if context_note:
        output += f"\n\n[DISCORD CONTEXT]{separator}{context_note}"

    logger.debug(output)


def log_debug_json(logger: logging.Logger, event: str, payload: Any):
    """Legacy debug JSON logger - logs if DEBUG_MODE is enabled."""
    if not debug_enabled():
        return

    try:
        body = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        body = f"<failed to serialize payload: {exc}>"

    logger.debug("%s %s", event, body)
