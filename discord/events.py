import discord
from discord.ext import commands

from core.memory import get_guild_config, init_db, set_guild_config
from core.scheduler import ensure_scheduler_started
from discord.runtime import handle_message
from helpers import discord as discord_helpers
from helpers.log import get_logger


LOGGER = get_logger(__name__)


def register_events(bot: commands.Bot, default_guild_config: dict):
    @bot.event
    async def on_ready():
        try:
            init_db()
            ensure_scheduler_started()
            print(f"{bot.user} woke up and is ready to roll! >:3")
        except Exception as exc:
            print(f"Startup error: {exc}")

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

            # check if we should ignore bot messages
            ignore_bots = bool(config.get("ignore_bots", default_guild_config.get("ignore_bots", True)))
            if message.author.bot and ignore_bots:
                return

            bot_channel = config["bot_channel_id"]
            in_dedicated_channel = bot_channel and str(message.channel.id) == bot_channel
            mentioned_bot = bot.user in message.mentions
            should_respond = in_dedicated_channel or mentioned_bot
            think_enabled = bool(config.get("think", default_guild_config.get("think", False)))

            if should_respond:
                try:
                    await handle_message(bot, message, think_enabled=think_enabled)
                except Exception as exc:
                    LOGGER.exception(f"Message handling error: {exc}")
                    await discord_helpers.safe_reply(message, "~~TRUCK-KUN~~ AN EXCEPTION HIT ME!!! HELP!!! ;;A;;", LOGGER)
        finally:
            await bot.process_commands(message)
