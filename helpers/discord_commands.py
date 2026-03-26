from discord.ext import commands

from core.memory import get_guild_config, set_guild_config


def parse_bool_flag(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "yes", "y", "1", "enable", "enabled"}:
        return True
    if normalized in {"off", "false", "no", "n", "0", "disable", "disabled"}:
        return False
    return None


def register_commands(bot: commands.Bot, default_guild_config: dict):
    @bot.command(name="setchannel")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def set_bot_channel_command(ctx: commands.Context, channel_input: str | None = None):
        if channel_input and channel_input.strip().lower() in {"0", "none", "off", "disable", "disabled", "null"}:
            set_guild_config(str(ctx.guild.id), bot_channel_id=None)
            await ctx.reply("dedicated bot channel cleared. i'll respond only when mentioned.")
            return

        if channel_input:
            converter = commands.TextChannelConverter()
            try:
                target = await converter.convert(ctx, channel_input)
            except commands.BadArgument:
                await ctx.reply("i couldn't find that channel. use a mention, channel id, name, or `0` to clear.")
                return
        else:
            target = ctx.channel

        if target.guild.id != ctx.guild.id:
            await ctx.reply("channels in this server only! i cannot teleport!")
            return

        set_guild_config(str(ctx.guild.id), bot_channel_id=str(target.id))
        await ctx.reply(f"okay, now i'll only be able to run my mouth in {target.mention} (`{target.id}`). remember to @mention me elsewhere!")

    @bot.command(name="ttl")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def set_log_ttl_command(ctx: commands.Context, days: int):
        if days < 1 or days > 365:
            await ctx.reply("`days` must be between 1 and 365.")
            return

        set_guild_config(str(ctx.guild.id), log_ttl_days=days)
        day_text = "1 day" if days == 1 else f"{days} days"
        await ctx.reply(f"okay, i'll only clean the logs every {day_text} :3")

    @bot.command(name="think")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def set_think_command(ctx: commands.Context, enabled: str):
        parsed = parse_bool_flag(enabled)
        if parsed is None:
            await ctx.reply("use `on|off` (or `true|false`, `yes|no`, `1|0`)")
            return

        set_guild_config(str(ctx.guild.id), think=parsed)
        await ctx.reply("you turned on my brain! :3" if parsed else "you turned off my brain! :3")

    @bot.command(name="config")
    @commands.guild_only()
    async def guild_config_command(ctx: commands.Context):
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        channel_id = config.get("bot_channel_id")
        channel_text = f"<#{channel_id}> (`{channel_id}`)" if channel_id else "Not set"

        await ctx.reply(
            "Guild config:\n"
            f"- bot_channel_id: {channel_text}\n"
            f"- log_ttl_days: {config.get('log_ttl_days', default_guild_config['log_ttl_days'])}\n"
            f"- think: {config.get('think', default_guild_config['think'])}"
        )

    @set_bot_channel_command.error
    @set_log_ttl_command.error
    @set_think_command.error
    async def guild_admin_command_error(ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("pls spam ur admin to turn on `Manage Server` permission first ehe")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.reply("this is not the square hole meme so check ur aguments again pls :3")
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply("gotta plug sth in for commands to work so use `!config` to view current values :3")
            return
        raise error

    @bot.command(name="help")
    @commands.guild_only()
    async def help_command(ctx: commands.Context):
        await ctx.reply(
            "available commands:\n"
            "- `!setchannel [#channel|id|name|0]` set dedicated bot channel (`0` clears it).\n"
            "- `!ttl <days>` set retention window for logs/history (1-365).\n"
            "- `!think <on|off>` toggle think mode in guild config.\n"
            "- `!config` show current guild config.\n"
            "notes: config-changing commands require `Manage Server`."
        )
