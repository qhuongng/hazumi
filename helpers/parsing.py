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
