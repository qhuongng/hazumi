from core.memory import add_memory


async def remember(
    content: str = "",
    _user_id: str = "",
    _user_name: str = "",
) -> str:
    """
    Remember a piece of information for the user.
    The content should be a concise fact or detail that can be recalled later.
    """
    normalized_content = content.strip()
    if not normalized_content:
        return "I can only remember non-empty content."

    owner = _user_name.strip() or _user_id

    add_memory(_user_id, normalized_content)
    return f"Saved memory for {owner}: {normalized_content}"
