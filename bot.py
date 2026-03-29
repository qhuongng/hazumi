import os
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from constants.discord import DEFAULT_GUILD_CONFIG, DISCORD_COMMAND_PREFIX
from discord.commands import register_commands
from discord.events import register_events

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix=DISCORD_COMMAND_PREFIX, intents=intents, help_command=None)

register_commands(bot, DEFAULT_GUILD_CONFIG)
register_events(bot, DEFAULT_GUILD_CONFIG)


def run_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")
    # use project logging config only; disable discord.py's default handler wiring
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    run_bot()
