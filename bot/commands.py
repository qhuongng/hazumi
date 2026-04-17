from discord.ext import commands

from constants.config.discord import MAX_CONVO_BOMB_CHANCE
from core.memory import get_guild_config, set_guild_config


def register_commands(bot: commands.Bot, default_guild_config: dict):
    @bot.command(name="setchannel")
    @commands.guild_only()
    async def set_bot_channel_command(ctx: commands.Context, channel_input: str | None = None):
        if channel_input is None:
            await ctx.reply("pls provide a channel id, or `0` to remove the dedicated channel >:o")
            return

        if channel_input.strip() == "0":
            set_guild_config(str(ctx.guild.id), bot_channel_id=None)
            await ctx.reply("dedicated yap channel removed >:c now i'll respond only when mentioned")
            return

        if not channel_input.strip().isdigit():
            await ctx.reply("ur channel id seems wack >:D or u can pass `0` to remove the dedicated channel")
            return

        channel_id = channel_input.strip()
        target = ctx.guild.get_channel(int(channel_id))
        if target is None or not hasattr(target, "send"):
            await ctx.reply("i couldn't find that channel in this server >:o")
            return

        set_guild_config(str(ctx.guild.id), bot_channel_id=channel_id)
        await ctx.reply(f"okay, now i'll only be able to yap freely in {target.mention} (`{channel_id}`) >:D remember to @mention me elsewhere!")

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

    @bot.command(name="convobomb")
    @commands.guild_only()
    async def set_conversation_bombing(ctx: commands.Context, rate: str | None = None):
        if rate is None:
            await ctx.reply("use `!convobomb [rate]` to set a rate (e.g. `!convobomb 0.1`), or `!convobomb 0` to disable :3")
            return

        try:
            parsed = float(rate)
        except ValueError:
            await ctx.reply("rate must be a number between 0 and 0.5 (e.g. `0.1`) :<")
            return

        if parsed == 0:
            set_guild_config(str(ctx.guild.id), convo_bomb_chance=0.0)
            await ctx.reply("i'll stop conversation bombing now! :3")
            return

        if not (0 < parsed <= MAX_CONVO_BOMB_CHANCE):
            await ctx.reply(f"rate must be between 0 and {MAX_CONVO_BOMB_CHANCE} :3 u don't want me to start bombing every single message, do you? >:o")
            return

        set_guild_config(str(ctx.guild.id), convo_bomb_chance=parsed)
        await ctx.reply(f"i'll now have a {parsed*100:.4g}% chance to randomly bomb the convo >:D")

    @bot.command(name="banbomb")
    @commands.guild_only()
    async def set_bombing_banned_channel(ctx: commands.Context, channel_input: str | None = None):
        if channel_input is None:
            await ctx.reply("please provide a channel id to ban from bombing, or `0` to reset the ban list.")
            return

        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        banned_channels_str = config.get("bombing_banned_channel_ids", default_guild_config["bombing_banned_channel_ids"])
        banned_channels = set(banned_channels_str.split(",")) if banned_channels_str else set()

        if channel_input.strip() == "0":
            set_guild_config(str(ctx.guild.id), bombing_banned_channel_ids="")
            await ctx.reply("bombing ban list cleared!")
            return

        if not channel_input.strip().isdigit():
            await ctx.reply("please provide a valid channel id (numbers only), or `0` to reset the ban list.")
            return

        channel_id = channel_input.strip()
        target = ctx.guild.get_channel(int(channel_id))
        if target is None or not hasattr(target, "send"):
            await ctx.reply("i couldn't find that channel in this server. please double-check the id!")
            return

        if channel_id in banned_channels:
            await ctx.reply(f"{target.mention} is already in the bombing ban list!")
            return

        banned_channels.add(channel_id)
        set_guild_config(str(ctx.guild.id), bombing_banned_channel_ids=",".join(banned_channels))
        await ctx.reply(f"got it! i won't randomly bomb {target.mention} anymore.")

    @bot.command(name="unbanbomb")
    @commands.guild_only()
    async def remove_bombing_banned_channel(ctx: commands.Context, channel_input: str | None = None):
        if channel_input is None:
            await ctx.reply("please provide a channel id to remove from the bombing ban list.")
            return

        if not channel_input.strip().isdigit():
            await ctx.reply("please provide a valid channel id (numbers only).")
            return

        channel_id = channel_input.strip()
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        banned_channels_str = config.get("bombing_banned_channel_ids", default_guild_config["bombing_banned_channel_ids"])
        banned_channels = set(banned_channels_str.split(",")) if banned_channels_str else set()

        if channel_id not in banned_channels:
            await ctx.reply("that channel isn't in the bombing ban list!")
            return

        banned_channels.discard(channel_id)
        set_guild_config(str(ctx.guild.id), bombing_banned_channel_ids=",".join(banned_channels))
        target = ctx.guild.get_channel(int(channel_id))
        channel_mention = target.mention if target else f"`{channel_id}`"
        await ctx.reply(f"okay, i can bomb {channel_mention} again now :3")


    @bot.command(name="config")
    @commands.guild_only()
    async def guild_config_command(ctx: commands.Context):
        config = get_guild_config(str(ctx.guild.id)) or default_guild_config
        channel_id = config.get("bot_channel_id")
        channel_text = f"i **can** yap without @mentions in <#{channel_id}> (`{channel_id}`)" if channel_id else "i **cannot** yap without @mentions"
        bombing = config.get("convo_bomb_chance", default_guild_config["convo_bomb_chance"])
        bombing_text = f"i have a **{bombing*100:.4g}% chance** to randomly bomb the convo" if bombing > 0 else "i **cannot** bomb the convo"
        banned_channels_str = config.get("bombing_banned_channel_ids", default_guild_config["bombing_banned_channel_ids"])
        banned_channels = [c for c in banned_channels_str.split(",") if c] if banned_channels_str else []
        banned_mentions = [f"<#{c}>" for c in banned_channels]
        if len(banned_mentions) > 1:
            banned_text = ", ".join(banned_mentions[:-1]) + f" and {banned_mentions[-1]}"
        elif banned_mentions:
            banned_text = banned_mentions[0]

        await ctx.reply(
            f"## current config for {ctx.guild.name}\n\n"
            f"- {channel_text}{', but i **can still bomb u**' if bombing > 0 else ''}\n"
            f"- my brain is {'**on**' if config.get('think', default_guild_config['think']) else '**off**'}\n"
            f"- i'm currently {'**not ghosting**' if config.get('ignore_bots', default_guild_config['ignore_bots']) == False else '**ghosting**'} other bots\n"
            f"- {bombing_text}{', but **u banned me from bombing** in ' + banned_text if bombing > 0 and banned_channels else ''}\n\n"
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
            "## available commands\n\n"
            "### general config\n\n"
            "`!setchannel [id|0]`\nset dedicated yap channel using its id so u don't have to @mention me every time u wanna yap (`0` clears it)\n\n"
            "`!think`\ntoggle my brain on or off\n\n"
            "`!ignorebot`\ntoggle whether u want me to ghost other bots\n\n"
            "`!config`\nshow current server config\n\n"
            "### convo bombing\n\n"
            f"`!convobomb [rate]`\ntoggle whether i randomly bomb conversations. set a rate between 0 and {MAX_CONVO_BOMB_CHANCE} (e.g. `!convobomb 0.1`)\n\n"
            "`!banbomb [id|0]`\nban a channel from conversation bombing by its id (`0` clears the ban list)\n\n"
            "`!unbanbomb [id]`\nremove a channel from the bombing ban list"
        )
