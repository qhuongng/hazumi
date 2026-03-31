from discord.ext import commands

from core.memory import get_guild_config, set_guild_config
from helpers import parsing as parsing_helpers


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

    @bot.command(name="think")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def set_think_command(ctx: commands.Context, enabled: str):
        parsed = parsing_helpers.parse_bool_flag(enabled)
        if parsed is None:
            await ctx.reply("use `on|off` (or `true|false`, `yes|no`, `1|0`)")
            return

        set_guild_config(str(ctx.guild.id), think=parsed)
        await ctx.reply("you turned on my brain! :3" if parsed else "you turned off my brain! :3")

    @bot.command(name="ignorebot")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def set_ignore_bots_command(ctx: commands.Context, enabled: str):
        parsed = parsing_helpers.parse_bool_flag(enabled)
        if parsed is None:
            await ctx.reply("use `on|off` (or `true|false`, `yes|no`, `1|0`)")
            return

        set_guild_config(str(ctx.guild.id), ignore_bots=parsed)
        if parsed:
            await ctx.reply("i'll ignore other bots now :3")
        else:
            await ctx.reply("i'll interact with other bots now! :3")

    @bot.command(name="config")
    @commands.guild_only()
    async def guild_config_command(ctx: commands.Context):
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        channel_id = config.get("bot_channel_id")
        channel_text = f"<#{channel_id}> (`{channel_id}`)" if channel_id else "Not set"

        await ctx.reply(
            "current config for this server:\n"
            f"- bot_channel_id: {channel_text} (!setchannel [#channel|id|name|0] to change)\n"
            f"- think: {config.get('think', default_guild_config['think'])} (!think <on|off> to change)\n"
            f"- ignore_bots: {config.get('ignore_bots', default_guild_config['ignore_bots'])} (!ignorebot <on|off> to change)"
        )

    @set_bot_channel_command.error
    @set_think_command.error
    @set_ignore_bots_command.error
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
            "- `!setchannel [#channel|id|name|0]` set dedicated channel for me so u don't have to @mention me every time u wanna yap (`0` clears it)\n"
            "- `!think <on|off>` turn my brain on or off\n"
            "- `!ignorebot <on|off>` toggle whether u want me to ghost other bots\n"
            "- `!config` show current guild config\n"
            "notes: config-changing commands require `Manage Server` permission"
        )
