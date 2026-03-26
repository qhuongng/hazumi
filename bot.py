import os

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands
from dotenv import load_dotenv

from helpers.discord_commands import register_commands
from helpers.discord_events import register_events


load_dotenv()

DEFAULT_GUILD_CONFIG = {"bot_channel_id": None, "think": False, "log_ttl_days": 7}

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
scheduler = AsyncIOScheduler()

register_commands(bot, DEFAULT_GUILD_CONFIG)
register_events(bot, scheduler, DEFAULT_GUILD_CONFIG)


def run_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")
    bot.run(token)


if __name__ == "__main__":
    run_bot()
