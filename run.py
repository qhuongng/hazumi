import asyncio
import os
import sys
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from constants.config.discord import DEFAULT_GUILD_CONFIG, DISCORD_COMMAND_PREFIX
from bot.commands import register_commands
from bot.events import register_events
from helpers.log import get_logger
from core.memory import init_db

LOGGER = get_logger(__name__)

intents = discord.Intents.all()
intents.message_content = True

RETRY_DELAY = 30
MAX_RETRY_DELAY = 300


def make_bot() -> commands.Bot:
    bot = commands.Bot(
        command_prefix=DISCORD_COMMAND_PREFIX,
        intents=intents,
        help_command=None,
    )
    register_commands(bot, DEFAULT_GUILD_CONFIG)
    register_events(bot, DEFAULT_GUILD_CONFIG)
    return bot


async def run_bot():
    token = os.getenv("DISCORD_TOKEN")
    init_db()

    delay = RETRY_DELAY

    while True:
        bot = make_bot()
        try:
            LOGGER.info("Starting bot...")
            await bot.start(token)
            # bot.start() only returns cleanly on a graceful logout,
            # so reset the delay on a clean exit
            delay = RETRY_DELAY
        except discord.LoginFailure:
            # bad token — no point retrying
            LOGGER.critical("Invalid Discord token. Shutting down.")
            break
        except (discord.ConnectionClosed, discord.GatewayNotFound) as e:
            LOGGER.warning(f"Gateway error: {e}. Retrying in {delay}s...")
        except OSError as e:
            # Covers socket.gaierror / DNS failures
            LOGGER.warning(f"Network/DNS error: {e}. Retrying in {delay}s...")
        except Exception as e:
            LOGGER.error(f"Unexpected error: {e}. Retrying in {delay}s...")
        finally:
            if not bot.is_closed():
                await bot.close()

        await asyncio.sleep(delay)
        delay = min(delay * 2, MAX_RETRY_DELAY)  # exponential backoff, capped


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        LOGGER.info("Received exit signal (Ctrl+C), shutting down gracefully.")
        try:
            sys.exit(0)
        except SystemExit:
            pass