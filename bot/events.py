import re

import discord
from discord.ext import commands

from bot.runtime import handle_message
from constants.config.llm import FALLBACK_REPLY
from core.memory import get_guild_config, set_guild_config
from core.scheduler import ensure_scheduler_started
from helpers import discord as discord_helpers
from helpers.log import get_logger


LOGGER = get_logger(__name__)


def register_events(bot: commands.Bot, default_guild_config: dict):
    @bot.event
    async def on_ready():
        try:
            ensure_scheduler_started()
            print(f"{bot.user} woke up and is ready to roll! >:3")
        except Exception as exc:
            print(f"Startup error: {exc}")
            
    @bot.event
    async def on_disconnect():
        LOGGER.warning("Disconnected from Discord. Closing for outer loop retry...")
        await bot.close()

    @bot.event
    async def on_message(message: discord.Message):
        if not message.guild:
            return

        ctx = await bot.get_context(message)
        try:
            # valid commands should be handled only by command handlers
            if ctx.valid:
                return

            guild_id = str(message.guild.id)
            config = get_guild_config(guild_id)
            if not config:
                set_guild_config(guild_id)
                config = get_guild_config(guild_id)
            config = config or default_guild_config

            # check if we should ignore bot messages, however the bot must always ignore its own messages to prevent loops
            ignore_bots = bool(config.get("ignore_bots", default_guild_config.get("ignore_bots", True)))
            if (message.author.bot and ignore_bots) or message.author == bot.user:
                return

            bot_channel = config["bot_channel_id"]
            in_dedicated_channel = bot_channel and str(message.channel.id) == bot_channel
            mentioned_bot = bot.user in message.mentions
            should_respond = in_dedicated_channel or mentioned_bot
            think_enabled = bool(config.get("think", default_guild_config.get("think", False)))

            # just a fun bit where the bot reacts if it's mentioned by name but not pinged
            bot_name = (bot.user.display_name or bot.user.name or "").strip()
            content = message.content or ""
            name_pattern = rf"(?<!\w){re.escape(bot_name)}(?!\w)" if bot_name else None
            contains_bot_name = bool(name_pattern and re.search(name_pattern, content, flags=re.IGNORECASE))

            if contains_bot_name and not should_respond:
                try:
                    await message.add_reaction(discord_helpers.get_random_reaction())
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.debug("Unable to add name ping reaction for message_id=%s", message.id)

            if should_respond:
                try:
                    await handle_message(bot, message, think_enabled=think_enabled)
                except Exception as exc:
                    LOGGER.exception(f"Message handling error: {exc}")
                    await discord_helpers.safe_reply(message, FALLBACK_REPLY, LOGGER)
        finally:
            await bot.process_commands(message)
