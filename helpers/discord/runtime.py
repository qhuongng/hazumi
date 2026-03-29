import asyncio
import re

import discord

from core.memory import (
    add_log,
    get_discord_message_scope,
    get_scope_logs,
    get_uncompacted_scope_batch,
    get_uncompacted_scope_count,
    insert_discord_message,
    mark_scope_messages_compacted,
)
from core.engine import process_message_with_history, summarize_transcript
from helpers.log import get_logger
from helpers.text import split_message_chunks
from tools import load_tool_functions


CHANNEL_WINDOW_SIZE = 10
SCOPE_COMPACTION_BATCH_SIZE = 20
SCOPE_LOG_LIMIT = 3
_active_scope_compactions: set[str] = set()
_active_tools = load_tool_functions()
LOGGER = get_logger(__name__)
LOGGER.info("[tooling] loaded tools count=%s names=%s", len(_active_tools), [fn.__name__ for fn in _active_tools])


def is_prefix_command_content(content: str) -> bool:
    return content.lstrip().startswith("!")


async def should_skip_history_message(bot: discord.Client, message: discord.Message) -> bool:
    """Skip command messages and direct bot replies to command messages."""

    # explicit !command messages
    if is_prefix_command_content(message.content or ""):
        return True

    # other messages from the user
    if message.author.id != bot.user.id:
        return False

    # messages that don't reply to anything
    if not message.reference or not message.reference.message_id:
        return False

    # find the message that the bot is replying to and check if it's a command message
    parent_message = message.reference.resolved
    if parent_message is None:
        try:
            parent_message = await message.channel.fetch_message(message.reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            parent_message = None

    if isinstance(parent_message, discord.Message):
        return is_prefix_command_content(parent_message.content or "")

    return False


async def safe_reply(message: discord.Message, content: str):
    try:
        await message.reply(content)
    except Exception as exc:
        LOGGER.exception("Reply send error: %s", exc)


def channel_scope_key(guild_id: str, channel_id: str) -> str:
    """Scope key for messages in a channel that are not direct replies to the bot."""

    return f"channel:{guild_id}:{channel_id}"


def reply_scope_key(guild_id: str, root_message_id: str) -> str:
    """Scope key for bot-rooted reply threads."""

    return f"reply:{guild_id}:{root_message_id}"


def scope_log_user_id(guild_id: str, scope_key: str) -> str:
    """Synthetic logs key used to store compacted summaries for a scope."""

    return f"discord_scope:{guild_id}:{scope_key}"


def to_history_role(is_bot: bool) -> str:
    return "assistant" if is_bot else "user"


def _format_chat_line(author_name: str, content: str) -> str:
    return f"{author_name}: {content}"


def _format_context_row(row: dict) -> str:
    msg_id = str(row.get("message_id") or "")
    author_name = str(row.get("author_name") or "unknown")
    content = str(row.get("content") or "")
    reply_to = str(row.get("reply_to_message_id") or "").strip()
    if reply_to:
        return f"msg_id {msg_id} (reply to {reply_to}) - {author_name}: {content}"
    return f"msg_id {msg_id} - {author_name}: {content}"


def _format_summary_row(row: dict) -> str:
    """Format transcript lines for the summarizer model."""

    msg_id = str(row.get("message_id") or "")
    reply_to = str(row.get("reply_to_message_id") or "").strip()
    author_name = str(row.get("author_name") or "unknown")
    content = str(row.get("content") or "")

    if reply_to:
        return f"msg_id <{msg_id}> (reply to <{reply_to}>) - {author_name}: {content}"
    return f"msg_id <{msg_id}> - {author_name}: {content}"


def _highlight_usernames_in_text(text: str, usernames: set[str]) -> str:
    valid_names = [name.strip() for name in usernames if str(name or "").strip()]
    if not valid_names:
        return text

    # Prefer longest matches first so multi-word names are not partially replaced.
    pattern = "|".join(re.escape(name) for name in sorted(valid_names, key=len, reverse=True))
    return re.sub(pattern, lambda m: f"**{m.group(0)}**", text, flags=re.IGNORECASE)


async def _build_reply_thread_history(bot: discord.Client, message: discord.Message) -> list[dict]:
    """Collect parent-chain messages for the current Discord reply thread."""

    chain: list[discord.Message] = []
    seen_ids: set[int] = set()
    current = message

    while current.reference and current.reference.message_id:
        parent_id = int(current.reference.message_id)
        if parent_id in seen_ids:
            break
        seen_ids.add(parent_id)

        parent = current.reference.resolved
        if parent is None:
            try:
                parent = await current.channel.fetch_message(parent_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                parent = None

        if not isinstance(parent, discord.Message):
            break

        if not await should_skip_history_message(bot, parent):
            chain.append(parent)
        current = parent

    chain.reverse()

    history: list[dict] = []
    for item in chain:
        role = to_history_role(item.author.bot)
        if role == "assistant":
            content = str(item.content)
        else:
            content = _format_chat_line(item.author.display_name, item.content)
        history.append({
            "role": role,
            "content": content,
        })
    return history


def message_reply_to_id(message: discord.Message) -> str | None:
    if not message.reference or not message.reference.message_id:
        return None
    return str(message.reference.message_id)


def store_discord_message(message: discord.Message, scope_key: str):
    """Persist one discord message row under the resolved conversation scope."""

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
    """Resolve which conversation scope this message belongs to."""

    guild_id = str(message.guild.id)
    c_scope = channel_scope_key(guild_id, str(message.channel.id))
    reply_to_id = message_reply_to_id(message)
    
    if not reply_to_id:
        return c_scope

    # if the parent message is already known, inherit that scope directly.
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
        # direct replies to bot messages get their own reply-thread scope.
        return reply_scope_key(guild_id, str(parent_message.id))

    return c_scope


async def cache_recent_channel_window(bot: discord.Client, message: discord.Message, scope_key: str):
    """Cache a small recent window so prompt history has nearby channel context."""

    recent = [m async for m in message.channel.history(limit=CHANNEL_WINDOW_SIZE, oldest_first=False)]
    recent.reverse()
    
    for item in recent:
        if await should_skip_history_message(bot, item):
            continue
        store_discord_message(item, scope_key)

    if not await should_skip_history_message(bot, message):
        store_discord_message(message, scope_key)


async def _get_recent_channel_rows_before_message(
    bot: discord.Client,
    message: discord.Message,
    limit: int,
) -> list[dict]:
    """Fetch up to `limit` message rows strictly before `message` from channel history."""

    rows: list[dict] = []
    try:
        recent = [m async for m in message.channel.history(limit=limit, before=message, oldest_first=False)]
    except (discord.Forbidden, discord.HTTPException):
        return rows

    recent.reverse()

    for item in recent:
        if await should_skip_history_message(bot, item):
            continue
        rows.append(
            {
                "message_id": str(item.id),
                "reply_to_message_id": message_reply_to_id(item),
                "author_name": item.author.display_name,
                "content": item.content,
            }
        )

    return rows


async def build_custom_history(
    bot: discord.Client,
    message: discord.Message,
    guild_id: str,
    scope_key: str,
) -> tuple[list[dict], str]:
    """Build Discord context note from latest pre-message channel rows and scope summaries."""

    scope_rows = await _get_recent_channel_rows_before_message(bot, message, CHANNEL_WINDOW_SIZE)
    scope_summaries = get_scope_logs(guild_id, scope_key, limit=SCOPE_LOG_LIMIT)
    known_usernames = {str(row.get("author_name") or "") for row in scope_rows}

    history: list[dict] = []
    context_note = (
        "You are in a Discord guild text conversation with multiple participants. "
        "Expect casual, messy language and occasional out-of-order references. "
        "In message content, patterns like <@1234567890> are Discord user mentions."
    )

    if scope_rows:
        context_rows = "\n".join(_format_context_row(row) for row in scope_rows)
        context_note = (
            f"{context_note}\n\n"
            "## Latest Discord messages\n\n"
            "These are the most recent messages in the conversation. You should use them to have a rough idea of the context, but don't reply to them directly.\n\n"
            "Format: msg_id id (reply to id) - username: message\n\n",
            "CRITICAL: Do not let 'username: ' leak into your response, it's only part of the context formatting.\n\n",
            f"{context_rows}"
        )

    if scope_summaries:
        highlighted_summaries = [
            _highlight_usernames_in_text(summary, known_usernames)
            for summary in scope_summaries
        ]
        summary_block = "\n".join(highlighted_summaries)
        context_note = f"{context_note}\n\n## Recent summaries\n\nThese are recent summaries of the conversation. Also serves as a quick reference for important points. Don't reference them directly in your response.\n\n{summary_block if summary_block else '(no summaries yet)'}\n\nRememeber, you should primarily rely on the latest messages for immediate context, and use the summaries as a secondary reference for important details that may have been mentioned earlier."

    return history, context_note


def make_scope_compaction_key(guild_id: str, scope_key: str) -> str:
    """Create a unique in-process key for compaction locking per scope."""

    return f"{guild_id}:{scope_key}"


def maybe_start_scope_compaction(guild_id: str, scope_key: str):
    """Start background compaction when enough uncompacted messages have accumulated."""

    compaction_key = make_scope_compaction_key(guild_id, scope_key)

    if compaction_key in _active_scope_compactions:
        return
    
    uncompacted_count = get_uncompacted_scope_count(guild_id, scope_key)
    LOGGER.debug(
        "[compaction] check guild_id=%s scope=%s uncompacted=%s threshold=%s",
        guild_id,
        scope_key,
        uncompacted_count,
        SCOPE_COMPACTION_BATCH_SIZE,
    )
    if uncompacted_count < SCOPE_COMPACTION_BATCH_SIZE:
        return

    _active_scope_compactions.add(compaction_key)
    asyncio.create_task(run_scope_compaction(guild_id, scope_key, compaction_key))


async def run_scope_compaction(guild_id: str, scope_key: str, compaction_key: str):
    """Summarize one scope batch and mark those rows as compacted."""

    try:
        rows = get_uncompacted_scope_batch(guild_id, scope_key, batch_size=SCOPE_COMPACTION_BATCH_SIZE)
        if len(rows) < SCOPE_COMPACTION_BATCH_SIZE:
            return

        LOGGER.info("[compaction] started guild_id=%s scope=%s rows=%s", guild_id, scope_key, len(rows))

        transcript = "\n".join(_format_summary_row(row) for row in rows)
        summary = await summarize_transcript(transcript, batch_size=SCOPE_COMPACTION_BATCH_SIZE)

        if not summary:
            return

        add_log(scope_log_user_id(guild_id, scope_key), summary)
        mark_scope_messages_compacted([row["id"] for row in rows])
        LOGGER.info("[compaction] completed guild_id=%s scope=%s compacted=%s", guild_id, scope_key, len(rows))
    except Exception as exc:
        LOGGER.exception("Scope compaction error (%s): %s", scope_key, exc)
    finally:
        _active_scope_compactions.discard(compaction_key)


async def handle_message(bot: discord.Client, message: discord.Message, think_enabled: bool = False):
    """Main discord message pipeline: scope, history, model call, reply, then compaction check."""

    user_id = str(message.author.id)
    user_name = message.author.display_name
    guild_id = str(message.guild.id)
    scope_key = await resolve_scope_key(bot, message)

    await cache_recent_channel_window(bot, message, scope_key)
    # Run compaction check right after ingesting new message rows so model/reply failures
    # do not block background summarization from ever starting.
    maybe_start_scope_compaction(guild_id, scope_key)

    text = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if not text:
        text = message.content.strip() or "(no text)"
    text = _format_chat_line(user_name, text)

    should_mention_author = False

    if message.reference and message.reference.message_id:
        # only mention author automatically in bot-thread reply flows.
        parent_message = message.reference.resolved
        
        if parent_message is None:
            try:
                parent_message = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                parent_message = None

        if isinstance(parent_message, discord.Message) and parent_message.author.id == bot.user.id:
            should_mention_author = bot.user in message.mentions

    async with message.channel.typing():
        thread_history = await _build_reply_thread_history(bot, message)
        _, context_note = await build_custom_history(bot, message, guild_id, scope_key)
        response = await process_message_with_history(
            user_id=user_id,
            user_name=user_name,
            text=text,
            history=thread_history,
            context_note=context_note,
            tools=_active_tools,
            thinking_enabled=think_enabled,
        )

    if len(response) <= 2000:
        sent = await message.reply(response, mention_author=should_mention_author)
        store_discord_message(sent, scope_key)
    else:
        # discord has a hard message limit, so split long outputs safely.
        chunks = split_message_chunks(response, max_len=1990)
        for chunk in chunks:
            sent = await message.reply(chunk, mention_author=should_mention_author)
            store_discord_message(sent, scope_key)

    maybe_start_scope_compaction(guild_id, scope_key)
