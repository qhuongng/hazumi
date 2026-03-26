from pathlib import Path


def build_system_prompt() -> str:
    base = Path("prompts/BASE.md").read_text()
    soul = Path("prompts/SOUL.md").read_text()
    return f"""{base}

# Who you are:
{soul}
"""
