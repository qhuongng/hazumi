import os

from datetime import datetime
from pathlib import Path

from core.memory import get_memories


MEMORIES_IN_PROMPT_LIMIT = int(os.getenv("MEMORIES_IN_PROMPT_LIMIT", "20"))

_BASE_PROMPT = Path("constants/prompts/BASE.md").read_text()
_SOUL_PROMPT = Path("constants/prompts/SOUL.md").read_text()


def build_system_prompt(user_id: str, user_name: str = "") -> str:
    base = _BASE_PROMPT
    soul = _SOUL_PROMPT
    memory_limit = MEMORIES_IN_PROMPT_LIMIT if MEMORIES_IN_PROMPT_LIMIT > 0 else None
    memory_rows = get_memories(user_id, limit=memory_limit)
    display_name = user_name.strip() or "unknown"

    if memory_rows:
        memories = "\n".join(
            f"- {m['value']} (discord_user_id={user_id}, discord_name={display_name})"
            for m in memory_rows
        )
    else:
        memories = "- (no memories)"

    return f"""Today is {datetime.now().strftime('%Y-%m-%d')}.

{base}

# Who you are

{soul}

# What you know about the user

{memories}
"""
