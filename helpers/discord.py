import discord
import random

from constants.config.discord import NAME_PING_REACTIONS


def is_prefix_command(content: str, prefix: str = "!") -> bool:
    """Check if a message content starts with a command prefix."""
    return content.lstrip().startswith(prefix)


def message_reply_to_id(message: discord.Message) -> str | None:
    """Extract the reply-to message ID from a Discord message."""
    if not message.reference or not message.reference.message_id:
        return None
    return str(message.reference.message_id)


async def fetch_parent_message(message: discord.Message) -> discord.Message | None:
    """
    Fetch the parent message that this message is replying to.
    Returns None if there is no parent or if fetching fails.
    """
    if not message.reference or not message.reference.message_id:
        return None

    parent = message.reference.resolved
    if parent is None:
        try:
            parent = await message.channel.fetch_message(message.reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    return parent if isinstance(parent, discord.Message) else None


def to_llm_role(is_bot: bool) -> str:
    """Convert Discord bot flag to LLM role."""
    return "assistant" if is_bot else "user"


def format_chat_line(author_name: str, content: str) -> str:
    """Format a chat message with author prefix."""
    return f"{author_name}: {content}"


def format_context_row(row: dict) -> str:
    """Format a message row for Discord context display."""
    msg_id = str(row.get("message_id") or "")
    author_name = str(row.get("author_name") or "unknown")
    content = str(row.get("content") or "")
    reply_to = str(row.get("reply_to_message_id") or "").strip()

    if reply_to:
        return f"msg_id {msg_id} (reply to {reply_to}) - {author_name}: {content}"
    return f"msg_id {msg_id} - {author_name}: {content}"


async def safe_reply(message: discord.Message, content: str, logger=None):
    """Safely reply to a message, logging errors if they occur."""
    try:
        await message.reply(content)
    except Exception as exc:
        if logger:
            logger.exception("Reply send error: %s", exc)
        else:
            print(f"Reply send error: {exc}")

def get_random_reaction() -> str:
    """Get a random reaction emoji from the predefined list."""
    return random.choice(NAME_PING_REACTIONS)
