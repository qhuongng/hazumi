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
                ignore_bots BOOLEAN DEFAULT TRUE
            );
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                reply_to_message_id TEXT,
                author_id TEXT NOT NULL,
                author_name TEXT NOT NULL,
                is_bot BOOLEAN NOT NULL DEFAULT FALSE,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                UNIQUE(guild_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_channel_recent
            ON conversation_history (guild_id, channel_id, created_at DESC);
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
):
    config = get_guild_config(guild_id)
    if config:
        bot_channel_id = bot_channel_id if bot_channel_id is not None else config["bot_channel_id"]
        think = think if think is not None else config["think"]
        ignore_bots = ignore_bots if ignore_bots is not None else config.get("ignore_bots", True)
        with get_conn() as conn:
            conn.execute(
                "UPDATE guild_config SET bot_channel_id = ?, think = ?, ignore_bots = ? WHERE guild_id = ?",
                (bot_channel_id, think, ignore_bots, guild_id),
            )
    else:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO guild_config (guild_id, bot_channel_id, think, ignore_bots) VALUES (?, ?, ?, ?)",
                (
                    guild_id,
                    bot_channel_id,
                    think if think is not None else False,
                    ignore_bots if ignore_bots is not None else True,
                ),
            )


def insert_discord_message(
    guild_id: str,
    channel_id: str,
    message_id: str,
    reply_to_message_id: str | None,
    author_id: str,
    author_name: str,
    is_bot: bool,
    content: str,
    created_at: str,
):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO conversation_history (
                guild_id, channel_id, message_id, reply_to_message_id,
                author_id, author_name, is_bot, content, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, message_id) DO NOTHING
            """,
            (
                guild_id,
                channel_id,
                message_id,
                reply_to_message_id,
                author_id,
                author_name,
                is_bot,
                content,
                created_at,
            ),
        )


def get_channel_recent_messages(guild_id: str, channel_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM conversation_history
            WHERE guild_id = ? AND channel_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (guild_id, channel_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def prune_conversation_history(older_than_hours: int = 48) -> dict:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            DELETE FROM conversation_history
            WHERE datetime(created_at) < datetime('now', ?)
            """,
            (f"-{older_than_hours} hours",),
        )

    return {
        "pruned": int(cursor.rowcount if cursor.rowcount is not None else 0),
        "retention_hours": older_than_hours,
    }


