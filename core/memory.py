import sqlite3

from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "data" / "bot.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                bot_channel_id TEXT,
                think BOOLEAN DEFAULT FALSE,
                ignore_bots BOOLEAN DEFAULT TRUE,
                convo_bomb_chance REAL DEFAULT 0.0,
                bombing_banned_channel_ids TEXT DEFAULT ''
            );
        """)


def get_guild_config(guild_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
    return dict(row) if row else None


def set_guild_config(
    guild_id: str,
    bot_channel_id: str | None = None,
    think: bool | None = None,
    ignore_bots: bool | None = None,
    convo_bomb_chance: float | None = None,
    bombing_banned_channel_ids: str | None = None,
):
    config = get_guild_config(guild_id)
    if config:
        bot_channel_id = bot_channel_id if bot_channel_id is not None else config["bot_channel_id"]
        think = think if think is not None else config["think"]
        ignore_bots = ignore_bots if ignore_bots is not None else config.get("ignore_bots", True)
        convo_bomb_chance = convo_bomb_chance if convo_bomb_chance is not None else config.get("convo_bomb_chance", 0.0)
        bombing_banned_channel_ids = bombing_banned_channel_ids if bombing_banned_channel_ids is not None else config.get("bombing_banned_channel_ids", "")
        with get_conn() as conn:
            conn.execute(
                "UPDATE guild_config SET bot_channel_id = ?, think = ?, ignore_bots = ?, convo_bomb_chance = ?, bombing_banned_channel_ids = ? WHERE guild_id = ?",
                (bot_channel_id, think, ignore_bots, convo_bomb_chance, bombing_banned_channel_ids, guild_id),
            )
    else:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO guild_config (guild_id, bot_channel_id, think, ignore_bots, convo_bomb_chance, bombing_banned_channel_ids) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    bot_channel_id,
                    think if think is not None else False,
                    ignore_bots if ignore_bots is not None else True,
                    convo_bomb_chance if convo_bomb_chance is not None else 0.0,
                    bombing_banned_channel_ids if bombing_banned_channel_ids is not None else "",
                ),
            )




