import os
import re

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from core.memory import get_memories


MEMORIES_IN_PROMPT_LIMIT = int(os.getenv("MEMORIES_IN_PROMPT_LIMIT", "20"))


@lru_cache(maxsize=1)
def get_assistant_identity() -> str:
    soul = Path("constants/prompts/SOUL.md").read_text()
    match = re.search(r"\bYou are\s+([^\n.!?]+)", soul, flags=re.IGNORECASE)
    if match:
        identity = match.group(1).strip()
        if identity:
            return identity
    return "the assistant"


def build_system_prompt(user_id: str, user_name: str = "") -> str:
    base = Path("constants/prompts/BASE.md").read_text()
    soul = Path("constants/prompts/SOUL.md").read_text()
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

    return f"""Today is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.

{base}

# Who you are

{soul}

# What you know about the user

{memories}
"""
