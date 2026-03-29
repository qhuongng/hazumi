import discord

from constants.discord import CHANNEL_WINDOW_SIZE, DISCORD_MESSAGE_CHUNK_SIZE, DISCORD_MESSAGE_MAX_LENGTH
from core.memory import insert_discord_message
from core.engine import process_message_with_history
from helpers import discord as discord_helpers
from helpers import text as text_helpers
from helpers.log import get_logger
from tools import load_tool_functions


_active_tools = load_tool_functions()
LOGGER = get_logger(__name__)
LOGGER.info("[tooling] loaded tools count=%s names=%s", len(_active_tools), [fn.__name__ for fn in _active_tools])


async def should_skip_history_message(bot: discord.Client, message: discord.Message) -> bool:
    """Skip command messages and direct bot replies to command messages."""

    # explicit !command messages
    if discord_helpers.is_prefix_command(message.content or ""):
        return True

    # other messages from the user
    if message.author.id != bot.user.id:
        return False

    # messages that don't reply to anything
    if not message.reference or not message.reference.message_id:
        return False

    # find the message that the bot is replying to and check if it's a command message
    parent_message = await discord_helpers.fetch_parent_message(message)
    if isinstance(parent_message, discord.Message):
        return discord_helpers.is_prefix_command(parent_message.content or "")

    return False


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
        role = discord_helpers.to_llm_role(item.author.bot)
        if role == "assistant":
            content = str(item.content)
        else:
            content = discord_helpers.format_chat_line(item.author.display_name, item.content)
        history.append({
            "role": role,
            "content": content,
        })
    return history


def store_discord_message(message: discord.Message):
    """Persist one discord message row."""

    insert_discord_message(
        guild_id=str(message.guild.id),
        channel_id=str(message.channel.id),
        message_id=str(message.id),
        reply_to_message_id=discord_helpers.message_reply_to_id(message),
        author_id=str(message.author.id),
        author_name=message.author.display_name,
        is_bot=message.author.bot,
        content=message.content,
        created_at=message.created_at.isoformat(),
    )


async def cache_recent_channel_window(bot: discord.Client, message: discord.Message):
    """Cache a small recent window so prompt history has nearby channel context."""

    recent = [m async for m in message.channel.history(limit=CHANNEL_WINDOW_SIZE, oldest_first=False)]
    recent.reverse()

    for item in recent:
        if await should_skip_history_message(bot, item):
            continue
        store_discord_message(item)

    if not await should_skip_history_message(bot, message):
        store_discord_message(message)


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
                "reply_to_message_id": discord_helpers.message_reply_to_id(item),
                "author_name": item.author.display_name,
                "content": item.content,
            }
        )

    return rows


async def build_custom_history(
    bot: discord.Client,
    message: discord.Message,
) -> tuple[list[dict], str]:
    """Build Discord context note from latest pre-message channel rows."""

    scope_rows = await _get_recent_channel_rows_before_message(bot, message, CHANNEL_WINDOW_SIZE)

    history: list[dict] = []
    context_note = (
        "You are in a Discord guild text conversation with multiple participants. "
        "Expect casual, messy language and occasional out-of-order references. "
        "In message content, patterns like <@1234567890> are Discord user mentions."
    )

    if scope_rows:
        context_rows = "\n".join(discord_helpers.format_context_row(row) for row in scope_rows)
        context_note = (
            f"{context_note}\n\n"
            "## Latest Discord messages\n\n"
            "These are the most recent messages in the conversation. You should use them to have a rough idea of the context, but don't reply to them directly.\n\n"
            "Format: msg_id id (reply to id) - username: message\n\n",
            "CRITICAL: Do not let 'username: ' leak into your response, it's only part of the context formatting.\n\n",
            f"{context_rows}"
        )

    return history, context_note


async def handle_message(bot: discord.Client, message: discord.Message, think_enabled: bool = False):
    """Main discord message pipeline: scope, history, model call, reply, then compaction check."""

    user_id = str(message.author.id)
    user_name = message.author.display_name
    guild_id = str(message.guild.id)
    scope_key = await resolve_scope_key(bot, message)

    await cache_recent_channel_window(bot, message, scope_key)

    text = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if not text:
        text = message.content.strip() or "(no text)"
    text = discord_helpers.format_chat_line(user_name, text)

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
        _, context_note = await build_custom_history(bot, message)
        response = await process_message_with_history(
            user_id=user_id,
            user_name=user_name,
            text=text,
            history=thread_history,
            context_note=context_note,
            tools=_active_tools,
            thinking_enabled=think_enabled,
        )

    if len(response) <= DISCORD_MESSAGE_MAX_LENGTH:
        sent = await message.reply(response, mention_author=should_mention_author)
        store_discord_message(sent)
    else:
        # discord has a hard message limit, so split long outputs safely.
        chunks = text_helpers.split_message_chunks(response, max_len=DISCORD_MESSAGE_CHUNK_SIZE)
        for chunk in chunks:
            sent = await message.reply(chunk, mention_author=should_mention_author)
            store_discord_message(sent)
