def parse_bool_flag(value: str) -> bool | None:
    """
    Parse a string value into a boolean flag.

    Returns:
        True for: "on", "true", "yes", "y", "1", "enable", "enabled"
        False for: "off", "false", "no", "n", "0", "disable", "disabled"
        None for: any other value
    """
    normalized = value.strip().lower()
    if normalized in {"on", "true", "yes", "y", "1", "enable", "enabled"}:
        return True
    if normalized in {"off", "false", "no", "n", "0", "disable", "disabled"}:
        return False
    return None


def is_compute_error(response_text: str) -> bool:
    text = str(response_text or "").lower()
    return "compute error" in text or "insufficient memory" in text


def is_unsupported_parameter_error(response_text: str, parameter_name: str) -> bool:
    text = str(response_text or "").lower()
    param = str(parameter_name or "").strip().lower()
    if not param or param not in text:
        return False
    return any(
        token in text
        for token in (
            "unsupported",
            "unknown",
            "unrecognized",
            "not permitted",
            "extra inputs",
            "invalid",
        )
    )


def extract_response_message(data: dict) -> dict:
    choices = data.get("choices") or []
    if not choices:
        return {}
    first = choices[0] or {}
    return first.get("message") or {}
