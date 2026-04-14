import os

from datetime import datetime
from pathlib import Path

_BASE_PROMPT = Path("constants/prompts/BASE.md").read_text()
_SOUL_PROMPT = Path("constants/prompts/SOUL.md").read_text()


def build_system_prompt(user_id: str, user_name: str = "") -> str:
    base = _BASE_PROMPT
    soul = _SOUL_PROMPT

    return f"""Today is {datetime.now().strftime('%Y-%m-%d')}.

{base}

# Who you are

{soul}
"""
