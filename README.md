# hazumi - Discord chatbot with local LLM integration

A Discord chatbot powered by any OpenAI API-compatible LLM backend (e.g. llama.cpp) ~~because I don't dare talk to real humans~~. The bot maintains per-channel conversation context, supports tool use, and can be configured per server. It can be triggered via `@mentions`, given a specific channel to run without mentions, or even configured to randomly bomb your conversations. >:D

## General information

The codebase is organized into four main layers:

- **`bot/`** — Discord-facing layer. Handles events (incoming messages, reactions, connect/disconnect), slash-less prefix commands, and the runtime loop that fetches channel history and dispatches messages to the engine.
- **`core/`** — Application logic. Contains the LLM engine (`engine.py`), system prompt assembly (`context.py`), per-server configuration (`memory.py`), and an APScheduler-based scheduler (`scheduler.py`) for future background jobs.
- **`tools/`** — Pluggable tool functions exposed to the LLM. Currently includes `web_search`, which queries **DuckDuckGo** and optionally scrapes page content with **trafilatura**.
- **`constants/`** — Configuration constants and prompt files. LLM endpoint, timeouts, and Discord behavior are all set here. The bot's personality is defined in `constants/prompts/SOUL.md`.

### How it works

1. A message arrives in a Discord channel (either in the bot's dedicated channel or as a `@mention`).
2. The bot unfurls the reply chain (if any) to populate its `messages` array, and fetches a sliding window of recent channel history to use as supplementary conversation context.
    - This means that, to persist a short window of memory, a user can **reply to the bot's response** instead of mentioning it again after the first round of messages.
3. The message and history are passed to the LLM engine, which calls the configured OpenAI-compatible `/v1/chat/completions` endpoint.
4. If the model invokes a tool (e.g. `web_search`), the engine executes it and feeds the result back for up to `MAX_TOOL_ROUNDS` rounds before returning a final reply.
5. The reply is chunked to stay within Discord's 2000-character message limit and sent back.

Per-server settings (dedicated channel, thinking mode, bot-ignore toggle, conversation bomb rate) are stored in a local SQLite database at `data/bot.db`.

### Bot commands

All commands use the `!` prefix.

| Command                 | Description                                                                    |
| ----------------------- | ------------------------------------------------------------------------------ |
| `!setchannel [id\|0]`   | Set (or remove) the dedicated channel where the bot responds to all messages   |
| `!think`                | Toggle the model's thinking/reasoning mode on or off                           |
| `!ignorebot`            | Toggle whether the bot ignores messages from other bots                        |
| `!convobomb [rate]`     | Set a random chance (0–1) for the bot to interject in any channel unprompted with configurable cap  |
| `!banbomb [channel_id]` | Exclude a channel from conversation bombing                                    |

## Setup & run

**Prerequisites:** Python 3.10+ and an LLM served via OpenAI-compatible API (e.g. `llama-server` or Ollama).

1. Create and activate a virtual environment:

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    # Windows: .venv\Scripts\activate
    ```

2. Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3. Copy and fill in the environment file and the bot's personality prompt:

    ```bash
    cp .env.example .env
    cp constants/prompts/SOUL.md.example constants/prompts/SOUL.md
    ```

4. Edit `.env` with your Discord bot token and any other values, then edit `constants/prompts/SOUL.md` to define the bot's personality.

5. Run the bot:

    ```bash
    python run.py
    ```

The bot will automatically initialize the SQLite database on first run and reconnect with exponential back-off if it loses connection to Discord.

## Customization

- **LLM endpoint & model** — edit `constants/config/llm.py` to point to your server and set the model name.
- **Bot personality** — edit `constants/prompts/SOUL.md`. The base instructions in `constants/prompts/BASE.md` describe tool use and general behavior. I personally have a 3-mile-long `SOUL.md` instructing the LLM to phrase its response in a less AI-sloppy fashion, but be mindful of your LLM's configured context length and that the longer a system prompt is, the longer the LLM will take to process it and generate a response.
- **Adding tools** — drop a new module in `tools/` and export the async function. The runtime auto-discovers and loads all tool functions at startup.
- **Scheduled jobs** — register APScheduler jobs in `core/scheduler.py`'s `register_scheduler_jobs` function.

## To-do

- If you dug around in the code you might have noticed that the `scheduler.py` file is dead code... I haven't found a need for a scheduler yet, but I might extend it into a proper feature once I do.
- The first iteration of this bot has a OpenClaw-inspired, three-tier memory management solution, which proved idiotic for a chaotic and multi-user environment like Discord and for small, less capable local LLMs. Maybe I can revisit it once I have an epiphany in my dreams (or take a look at 3rd party solutions lmao).
- Improve the `web_search` tool as it's pretty rudimentary right now... A search-fetch loop is definitely optimal but for a Discord chatbot that requires fast response times, it's not the most suitable approach.
- The bot occasionally suffers from context rot, which is a natural consequence of injecting a sliding window of messages for context. I might need to refine that.