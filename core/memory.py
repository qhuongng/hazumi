import sqlite3
from pathlib import Path


DB_PATH = Path("data/bot.db")
DB_PATH.parent.mkdir(exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key)
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                bot_channel_id TEXT,
                think BOOLEAN DEFAULT FALSE,
                log_ttl_days INTEGER DEFAULT 7
            );
            CREATE TABLE IF NOT EXISTS discord_conversation_messages (
                id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                message_id TEXT NOT NULL,
                reply_to_message_id TEXT,
                author_id TEXT NOT NULL,
                author_name TEXT NOT NULL,
                is_bot BOOLEAN NOT NULL DEFAULT FALSE,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                compacted BOOLEAN DEFAULT FALSE,
                UNIQUE(guild_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_discord_scope_recent
            ON discord_conversation_messages (guild_id, scope_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_discord_scope_compacted
            ON discord_conversation_messages (guild_id, scope_key, compacted, created_at ASC);
        """)


def set_memory(user_id: str, key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO memories (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, value),
        )


def get_memories(user_id: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT key, value
            FROM memories
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def add_log(user_id: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (user_id, content) VALUES (?, ?)",
            (user_id, content),
        )


def get_all_guild_configs() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM guild_config").fetchall()]


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
    log_ttl_days: int | None = None,
):
    config = get_guild_config(guild_id)
    if config:
        bot_channel_id = bot_channel_id if bot_channel_id is not None else config["bot_channel_id"]
        think = think if think is not None else config["think"]
        log_ttl_days = log_ttl_days if log_ttl_days is not None else config["log_ttl_days"]
        with get_conn() as conn:
            conn.execute(
                "UPDATE guild_config SET bot_channel_id = ?, think = ?, log_ttl_days = ? WHERE guild_id = ?",
                (bot_channel_id, think, log_ttl_days, guild_id),
            )
    else:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO guild_config (guild_id, bot_channel_id, think, log_ttl_days) VALUES (?, ?, ?, ?)",
                (
                    guild_id,
                    bot_channel_id,
                    think if think is not None else False,
                    log_ttl_days if log_ttl_days is not None else 7,
                ),
            )


def insert_discord_message(
    guild_id: str,
    channel_id: str,
    scope_key: str,
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
            INSERT INTO discord_conversation_messages (
                guild_id, channel_id, scope_key, message_id, reply_to_message_id,
                author_id, author_name, is_bot, content, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, message_id) DO NOTHING
            """,
            (
                guild_id,
                channel_id,
                scope_key,
                message_id,
                reply_to_message_id,
                author_id,
                author_name,
                is_bot,
                content,
                created_at,
            ),
        )


def get_discord_message_scope(guild_id: str, message_id: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT scope_key
            FROM discord_conversation_messages
            WHERE guild_id = ? AND message_id = ?
            """,
            (guild_id, message_id),
        ).fetchone()
    return row["scope_key"] if row else None


def get_scope_recent_messages(guild_id: str, scope_key: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM discord_conversation_messages
            WHERE guild_id = ? AND scope_key = ? AND compacted = FALSE
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (guild_id, scope_key, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_uncompacted_scope_count(guild_id: str, scope_key: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM discord_conversation_messages
            WHERE guild_id = ? AND scope_key = ? AND compacted = FALSE
            """,
            (guild_id, scope_key),
        ).fetchone()
    return int(row["count"]) if row else 0


def get_uncompacted_scope_batch(guild_id: str, scope_key: str, batch_size: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM discord_conversation_messages
            WHERE guild_id = ? AND scope_key = ? AND compacted = FALSE
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (guild_id, scope_key, batch_size),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_scope_messages_compacted(ids: list[int]):
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE discord_conversation_messages SET compacted = TRUE WHERE id IN ({placeholders})",
            ids,
        )


def get_scope_logs(guild_id: str, scope_key: str, limit: int = 3) -> list[str]:
    scope_user_id = f"discord_scope:{guild_id}:{scope_key}"
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT content
            FROM logs
            WHERE user_id = ?
            ORDER BY logged_at DESC, id DESC
            LIMIT ?
            """,
            (scope_user_id, limit),
        ).fetchall()
    return [r["content"] for r in reversed(rows)]


def delete_old_discord_messages(guild_id: str, ttl_days: int):
    with get_conn() as conn:
        conn.execute(
            """
            DELETE FROM discord_conversation_messages
            WHERE guild_id = ?
            AND created_at < datetime('now', ?)
            """,
            (guild_id, f"-{ttl_days} days"),
        )
