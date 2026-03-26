from core.memory import set_memory


async def remember(key: str, value: str, _user_id: str = "") -> str:
    normalized_key = key.strip()
    normalized_value = value.strip()
    if not normalized_key or not normalized_value:
        return "I can only remember non-empty keys and values."

    set_memory(_user_id, normalized_key, normalized_value)
    return f"Saved memory: {normalized_key} = {normalized_value}"
