# Discord bot with Ollama SDK

WIP. This README will be updated with more details later.

## How to run

Prerequisites: Python (3.10+) and Ollama installed.

Create a virtual Python environment:

```bash
python -m venv .venv
# or
python3 -m venv .venv
```

Activate the virtual environment:

```bash
.venv/Scripts/activate
# or
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Remove `.example` from `.env.example` and `constants/prompts/SOUL.md.example` and customize the values and content to your liking. 

Run the bot:

```bash
python bot.py
# or
python3 bot.py
```