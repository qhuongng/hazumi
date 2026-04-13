# default guild configuration
DEFAULT_GUILD_CONFIG = {
    "bot_channel_id": None,
    "think": False,
    "ignore_bots": True,
}

# message handling
DISCORD_COMMAND_PREFIX = "!"
DISCORD_MESSAGE_CHUNK_SIZE = 1990  # discord's limit is 2000, leave some buffer
DISCORD_MESSAGE_MAX_LENGTH = 2000

# history and context
CHANNEL_WINDOW_SIZE = 14  # number of recent messages to cache for context

NAME_PING_REACTIONS = ["🤨", "🙈", "😳", "🫣", "🫡", "👀", "🌝", "🧍‍♀️"]
