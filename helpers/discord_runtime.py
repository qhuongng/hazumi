import asyncio

import discord

from core.memory import (
    add_log,
    delete_old_discord_messages,
    get_discord_message_scope,
    get_memories,
    get_scope_logs,
    get_scope_recent_messages,
    get_uncompacted_scope_batch,
    get_uncompacted_scope_count,
    insert_discord_message,
    mark_scope_messages_compacted,
)
from helpers.ai_runtime import process_message_with_history, summarize_transcript
from helpers.text import split_message_chunks
from tools.remember import remember


CHANNEL_WINDOW_SIZE = 10
SCOPE_COMPACTION_BATCH_SIZE = 20
_active_scope_compactions: set[str] = set()


async def safe_reply(message: discord.Message, content: str):
    try:
        await message.reply(content)
    except Exception as exc:
        print(f"Reply send error: {exc}")


def channel_scope_key(guild_id: str, channel_id: str) -> str:
    return f"channel:{guild_id}:{channel_id}"


def reply_scope_key(guild_id: str, root_message_id: str) -> str:
    return f"reply:{guild_id}:{root_message_id}"


def scope_log_user_id(guild_id: str, scope_key: str) -> str:
    return f"discord_scope:{guild_id}:{scope_key}"


def to_history_role(is_bot: bool) -> str:
    return "assistant" if is_bot else "user"


def message_reply_to_id(message: discord.Message) -> str | None:
    if not message.reference or not message.reference.message_id:
        return None
    return str(message.reference.message_id)


def store_discord_message(message: discord.Message, scope_key: str):
    insert_discord_message(
        guild_id=str(message.guild.id),
        channel_id=str(message.channel.id),
        scope_key=scope_key,
        message_id=str(message.id),
        reply_to_message_id=message_reply_to_id(message),
        author_id=str(message.author.id),
        author_name=message.author.display_name,
        is_bot=message.author.bot,
        content=message.content,
        created_at=message.created_at.isoformat(),
    )


async def resolve_scope_key(bot: discord.Client, message: discord.Message) -> str:
    guild_id = str(message.guild.id)
    c_scope = channel_scope_key(guild_id, str(message.channel.id))
    reply_to_id = message_reply_to_id(message)
    if not reply_to_id:
        return c_scope

    existing_scope = get_discord_message_scope(guild_id, reply_to_id)
    if existing_scope:
        return existing_scope

    parent_message = message.reference.resolved
    if parent_message is None:
        try:
            parent_message = await message.channel.fetch_message(int(reply_to_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            parent_message = None

    if isinstance(parent_message, discord.Message) and parent_message.author.id == bot.user.id:
        return reply_scope_key(guild_id, str(parent_message.id))

    return c_scope


async def cache_recent_channel_window(message: discord.Message, scope_key: str):
    recent = [m async for m in message.channel.history(limit=CHANNEL_WINDOW_SIZE, oldest_first=True)]
    for item in recent:
        store_discord_message(item, scope_key)
    store_discord_message(message, scope_key)


def build_custom_history(user_id: str, guild_id: str, scope_key: str) -> tuple[list[dict], str]:
    scope_rows = get_scope_recent_messages(guild_id, scope_key, limit=CHANNEL_WINDOW_SIZE)
    scope_summaries = get_scope_logs(guild_id, scope_key, limit=3)
    memories = get_memories(user_id, limit=10)

    history = [{"role": to_history_role(row["is_bot"]), "content": row["content"]} for row in scope_rows]
    context_note = "You are in a Discord guild channel with multiple participants."
    if scope_summaries:
        summary_block = "\n".join(f"- {s}" for s in scope_summaries)
        context_note = f"{context_note}\nRecent compacted summaries:\n{summary_block}"
    if memories:
        memory_block = "\n".join(f"- {m['key']}: {m['value']}" for m in memories)
        context_note = f"{context_note}\nKnown user memories:\n{memory_block}"

    return history, context_note


def make_scope_compaction_key(guild_id: str, scope_key: str) -> str:
    return f"{guild_id}:{scope_key}"


def maybe_start_scope_compaction(guild_id: str, scope_key: str):
    compaction_key = make_scope_compaction_key(guild_id, scope_key)
    if compaction_key in _active_scope_compactions:
        return
    if get_uncompacted_scope_count(guild_id, scope_key) < SCOPE_COMPACTION_BATCH_SIZE:
        return

    _active_scope_compactions.add(compaction_key)
    asyncio.create_task(run_scope_compaction(guild_id, scope_key, compaction_key))


async def run_scope_compaction(guild_id: str, scope_key: str, compaction_key: str):
    try:
        rows = get_uncompacted_scope_batch(guild_id, scope_key, batch_size=SCOPE_COMPACTION_BATCH_SIZE)
        if len(rows) < SCOPE_COMPACTION_BATCH_SIZE:
            return

        transcript = "\n".join(f"{row['author_name']}: {row['content']}" for row in rows)
        summary = await summarize_transcript(transcript, batch_size=SCOPE_COMPACTION_BATCH_SIZE)
        if not summary:
            return

        add_log(scope_log_user_id(guild_id, scope_key), f"[SUMMARY x{SCOPE_COMPACTION_BATCH_SIZE}] {summary}")
        mark_scope_messages_compacted([row["id"] for row in rows])
    except Exception as exc:
        print(f"Scope compaction error ({scope_key}): {exc}")
    finally:
        _active_scope_compactions.discard(compaction_key)


async def handle_message(bot: discord.Client, message: discord.Message):
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    scope_key = await resolve_scope_key(bot, message)

    await cache_recent_channel_window(message, scope_key)

    text = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if not text:
        text = message.content.strip() or "(no text)"

    should_mention_author = False
    if message.reference and message.reference.message_id:
        parent_message = message.reference.resolved
        if parent_message is None:
            try:
                parent_message = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                parent_message = None

        if isinstance(parent_message, discord.Message) and parent_message.author.id == bot.user.id:
            should_mention_author = bot.user in message.mentions

    async with message.channel.typing():
        custom_history, context_note = build_custom_history(user_id, guild_id, scope_key)
        response = await process_message_with_history(
            user_id=user_id,
            text=text,
            history=custom_history,
            context_note=context_note,
            tools=[remember],
        )

    if len(response) <= 2000:
        sent = await message.reply(response, mention_author=should_mention_author)
        store_discord_message(sent, scope_key)
    else:
        chunks = split_message_chunks(response, max_len=1990)
        for chunk in chunks:
            sent = await message.reply(chunk, mention_author=should_mention_author)
            store_discord_message(sent, scope_key)

    maybe_start_scope_compaction(guild_id, scope_key)


def cleanup_discord_messages_for_guild(guild_id: str, ttl_days: int):
    delete_old_discord_messages(guild_id, ttl_days)
