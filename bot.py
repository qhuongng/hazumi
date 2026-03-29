import os
import discord

from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

from helpers.discord.commands import register_commands
from helpers.discord.events import register_events

DEFAULT_GUILD_CONFIG = {"bot_channel_id": None, "think": False, "log_ttl_days": 7}

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

register_commands(bot, DEFAULT_GUILD_CONFIG)
register_events(bot, DEFAULT_GUILD_CONFIG)


def run_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")
    # Use project logging config only; disable discord.py's default handler wiring.
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    run_bot()
