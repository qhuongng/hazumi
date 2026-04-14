import sqlite3
import re

from datetime import datetime, timedelta
from pathlib import Path

from constants.memory import DURABLE_MEMORY_MARKERS


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
                value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
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


def add_memory(user_id: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO memories (user_id, value) VALUES (?, ?)",
            (user_id, value),
        )


def get_memories(user_id: str, limit: int | None = 20) -> list[dict]:
    with get_conn() as conn:
        if limit is None:
            rows = conn.execute(
                """
                SELECT id, value, created_at
                FROM memories
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, value, created_at
                FROM memories
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_memory_rows(user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, value, created_at
            FROM memories
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_memory_user_ids() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT user_id
            FROM memories
            ORDER BY user_id ASC
            """
        ).fetchall()
    return [str(r["user_id"]) for r in rows]


def _parse_memory_timestamp(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


def _is_durable_memory(content: str) -> bool:
    lowered = content.lower()
    return any(marker in lowered for marker in DURABLE_MEMORY_MARKERS)


def _memory_topic_signature(content: str) -> str:
    stopwords = {
        "the", "a", "an", "is", "am", "are", "was", "were", "to", "of", "and",
        "in", "on", "for", "with", "that", "this", "it", "i", "my", "me", "we",
        "our", "you", "your", "they", "them", "he", "she", "at", "as", "be",
    }
    tokens = [t for t in re.findall(r"[a-z0-9']+", content.lower()) if t not in stopwords]
    return " ".join(tokens[:5])


def prune_memories_for_user(user_id: str, older_than_days: int = 14) -> dict:
    rows = get_memory_rows(user_id)
    if not rows:
        return {"user_id": user_id, "pruned": 0, "kept": 0}

    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    seen_signatures: set[str] = set()
    prune_ids: list[int] = []

    for row in rows:
        content = str(row["value"])
        created_at = _parse_memory_timestamp(str(row["created_at"]))
        durable = _is_durable_memory(content)
        signature = _memory_topic_signature(content)

        # newer memory wins for the same topic unless the older one is durable.
        if signature and signature in seen_signatures and not durable:
            prune_ids.append(int(row["id"]))
            continue

        # non-durable memories older than retention window are pruned.
        if created_at < cutoff and not durable:
            prune_ids.append(int(row["id"]))
            continue

        if signature:
            seen_signatures.add(signature)

    if prune_ids:
        placeholders = ",".join("?" for _ in prune_ids)
        with get_conn() as conn:
            conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", prune_ids)

    return {"user_id": user_id, "pruned": len(prune_ids), "kept": len(rows) - len(prune_ids)}


def prune_memories(older_than_days: int = 14) -> dict:
    user_ids = list_memory_user_ids()
    total_pruned = 0
    total_kept = 0

    for user_id in user_ids:
        result = prune_memories_for_user(user_id, older_than_days=older_than_days)
        total_pruned += int(result["pruned"])
        total_kept += int(result["kept"])

    return {"users": len(user_ids), "pruned": total_pruned, "kept": total_kept}


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


