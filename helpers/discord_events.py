import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from core.memory import add_log, get_all_guild_configs, get_conn, get_guild_config, init_db, set_guild_config
from helpers.discord_runtime import cleanup_discord_messages_for_guild, handle_message, safe_reply


def register_events(bot: commands.Bot, scheduler: AsyncIOScheduler, default_guild_config: dict):
    @scheduler.scheduled_job("cron", hour=3)
    async def cleanup_logs():
        configs = get_all_guild_configs()
        for config in configs:
            ttl_window = f"-{config['log_ttl_days']} days"
            try:
                with get_conn() as conn:
                    conn.execute(
                        """
                        DELETE FROM logs
                        WHERE logged_at < datetime('now', ?)
                        """,
                        (ttl_window,),
                    )
                cleanup_discord_messages_for_guild(str(config["guild_id"]), int(config["log_ttl_days"]))
            except Exception as exc:
                print(f"Cleanup error for guild {config.get('guild_id', 'unknown')}: {exc}")

    @bot.event
    async def on_ready():
        try:
            init_db()
            scheduler.start()
            print(f"{bot.user} woke up and is ready to roll! >:3")
        except Exception as exc:
            print(f"Startup error: {exc}")

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        config = get_guild_config(guild_id)
        if not config:
            set_guild_config(guild_id)
            config = get_guild_config(guild_id)
        config = config or default_guild_config

        bot_channel = config["bot_channel_id"]
        in_dedicated_channel = bot_channel and str(message.channel.id) == bot_channel
        mentioned_bot = bot.user in message.mentions
        should_respond = in_dedicated_channel or mentioned_bot

        try:
            if should_respond:
                try:
                    await handle_message(bot, message)
                except Exception as exc:
                    print(f"Message handling error: {exc}")
                    await safe_reply(message, "~~TRUCK-KUN~~ AN EXCEPTION HIT ME!!! HELP!!! ;;A;;")

                try:
                    add_log(user_id, f"{message.author.name}: {message.content}")
                except Exception as exc:
                    print(f"Log write error: {exc}")
        finally:
            await bot.process_commands(message)
