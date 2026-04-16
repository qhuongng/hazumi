from discord.ext import commands

from core.memory import get_guild_config, set_guild_config


def register_commands(bot: commands.Bot, default_guild_config: dict):
    @bot.command(name="setchannel")
    @commands.guild_only()
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
    async def set_think_command(ctx: commands.Context):
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        new_value = not config.get("think", default_guild_config["think"])
        set_guild_config(str(ctx.guild.id), think=new_value)
        await ctx.reply("you turned on my brain! :3" if new_value else "you turned off my brain! >:o")

    @bot.command(name="ignorebot")
    @commands.guild_only()
    async def set_ignore_bots_command(ctx: commands.Context):
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        new_value = not config.get("ignore_bots", default_guild_config["ignore_bots"])
        set_guild_config(str(ctx.guild.id), ignore_bots=new_value)
        if new_value:
            await ctx.reply("i'll ignore other bots now :3")
        else:
            await ctx.reply("i'll interact with other bots now! :3")

    @bot.command(name="config")
    @commands.guild_only()
    async def guild_config_command(ctx: commands.Context):
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        channel_id = config.get("bot_channel_id")
        channel_text = f"i **can** yap without @mentions in <#{channel_id}> (`{channel_id}`)" if channel_id else "i **cannot** yap without @mentions"

        await ctx.reply(
            "current config for this server:\n\n"
            f"- {channel_text}\n"
            f"- my brain is {'**on**' if config.get('think', default_guild_config['think']) else '**off**'}\n"
            f"- i'm currently {'**not ghosting**' if config.get('ignore_bots', default_guild_config['ignore_bots']) == False else '**ghosting**'} other bots\n\n"
            f"pls use `!help` to see how to change these settings :3"
        )

    @set_bot_channel_command.error
    @set_think_command.error
    @set_ignore_bots_command.error
    async def guild_admin_command_error(ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.BadArgument):
            await ctx.reply("this is not the square hole meme so check ur aguments again pls :3")
            return
        raise error

    @bot.command(name="help")
    @commands.guild_only()
    async def help_command(ctx: commands.Context):
        await ctx.reply(
            "available commands:\n\n"
            "`!setchannel [#channel|id|name|0]`\nset dedicated yap channel for me so u don't have to @mention me every time u wanna yap (`0` clears it)\n\n"
            "`!think`\ntoggle my brain on or off\n\n"
            "`!ignorebot`\ntoggle whether u want me to ghost other bots\n\n"
            "`!config`\nshow current guild config"
        )
