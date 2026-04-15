import asyncio
import os
import sys
import aiohttp
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from bot.commands import register_commands
from bot.events import register_events
from constants.config.discord import DEFAULT_GUILD_CONFIG, DISCORD_COMMAND_PREFIX, RETRY_DELAY, MAX_RETRY_DELAY
from core.memory import init_db
from helpers.log import get_logger

LOGGER = get_logger(__name__)

intents = discord.Intents.all()
intents.message_content = True


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
    delay = RETRY_DELAY

    while True:
        init_db()  # re-initialize on every reconnect attempt
        bot = make_bot()
        start_time = asyncio.get_event_loop().time()

        try:
            LOGGER.info("Starting bot...")
            await bot.start(token, reconnect=False)
        except discord.LoginFailure:
            # bad token — no point retrying
            LOGGER.critical("Invalid Discord token. Shutting down.")
            break
        except (discord.ConnectionClosed, discord.GatewayNotFound) as e:
            LOGGER.warning(f"Gateway error: {e}. Retrying in {delay}s...")
        except (OSError, aiohttp.ClientConnectorError) as e:
            # Covers socket.gaierror, DNS failures, and aiohttp connector errors
            LOGGER.warning(f"Network/DNS error: {e}. Retrying in {delay}s...")
        except Exception as e:
            LOGGER.error(f"Unexpected error: {e}. Retrying in {delay}s...", exc_info=True)
        finally:
            if not bot.is_closed():
                await bot.close()

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > 60:
            delay = RETRY_DELAY
        
        LOGGER.info(f"Retrying in {delay}s...")
        await asyncio.sleep(delay)
        delay = min(delay * 2, MAX_RETRY_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        LOGGER.info("Received exit signal (Ctrl+C), shutting down gracefully.")
        try:
            sys.exit(0)
        except SystemExit:
            pass