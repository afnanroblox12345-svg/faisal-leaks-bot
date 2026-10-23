import os
import json
import logging
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands

# =====================================================================
# SLS HELPER — PRODUCTION CONFIGURATION & SETUP
# =====================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname]s] %(name)s: %(message)s"
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

CONFIG_FILE = "config.json"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=">",
    intents=intents,
    help_command=None
)

# Comprehensive Blue & Aesthetic Emoji Sources for Auto-Upload Setup
BLUE_EMOJI_SOURCES = {
    "blue_star": "https://cdn3.emoji.gg/emojis/3045-blue-star.gif",
    "blue_fire": "https://cdn3.emoji.gg/emojis/31347-bluefire.gif",
    "blue_deer": "https://cdn3.emoji.gg/emojis/6019-blue-deer.png",
    "blue_shield": "https://cdn.discordapp.com/emojis/1561078954519961622.png",
    "blue_gem": "https://cdn.discordapp.com/emojis/1561077598791016591.png",
    "blue_ticket": "https://cdn.discordapp.com/emojis/1560983848345665637.png",
    "blue_support": "https://cdn.discordapp.com/emojis/1561328482724614238.png",
    "blue_purchase": "https://cdn.discordapp.com/emojis/1561328437057032222.png",
    "blue_partner": "https://cdn.discordapp.com/emojis/1561337139373932593.png"
}

config = {
    "supervisor_roles": {},
    "staff_roles": {},
    "ticket_categories": {},
    "promodemo_channels": {},
    "audit_channels": {},
    "rank_ladders": {},
    "staff_limits": {},
    "warnings": {},
    "trainings": {}
}


def load_config():
    global config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)
        for key in config:
            if isinstance(saved.get(key), dict):
                config[key] = saved[key]
    except FileNotFoundError:
        save_config()
    except (json.JSONDecodeError, OSError):
        logging.exception("Could not load configuration file.")


def save_config():
    temporary_file = CONFIG_FILE + ".tmp"
    try:
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)
        os.replace(temporary_file, CONFIG_FILE)
    except OSError:
        logging.exception("Could not save configuration file safely.")


def guild_setting(setting, guild_id):
    return config[setting].get(str(guild_id))


# =====================================================================
# DYNAMIC EMOJI RESOLUTION HELPER
# =====================================================================

def get_emoji(guild, name):
    """Retrieves custom server emojis dynamically or falls back cleanly."""
    if guild:
        e = discord.utils.get(guild.emojis, name=name)
        if e:
            return str(e)
    return "🔹"


def get_emoji_dict(guild):
    """Generates the full active blue-themed emoji mapping for a guild."""
    return {
        "promo": get_emoji(guild, "blue_gem"),
        "demo": get_emoji(guild, "blue_deer"),
        "shield": get_emoji(guild, "blue_shield"),
        "gear": get_emoji(guild, "blue_deer"),
        "ladder": get_emoji(guild, "blue_star"),
        "announcement": get_emoji(guild, "blue_fire"),
        "audit": get_emoji(guild, "blue_star"),
        "success": get_emoji(guild, "blue_star"),
        "warning": get_emoji(guild, "blue_fire"),
        "error": get_emoji(guild, "blue_fire"),
        "user": get_emoji(guild, "blue_deer"),
        "bullet": get_emoji(guild, "blue_star"),
        "welcome": get_emoji(guild, "blue_fire"),
        "ticket": get_emoji(guild, "blue_ticket"),
        "support": get_emoji(guild, "blue_support"),
        "purchase": get_emoji(guild, "blue_purchase"),
        "partner": get_emoji(guild, "blue_partner")
    }


# =====================================================================
# PERMISSION & RATE LIMIT VALIDATORS
# =====================================================================

def user_is_owner(ctx):
    return ctx.author.id == OWNER_ID or ctx.author.id == ctx.guild.owner_id


def user_is_supervisor(ctx):
    if user_is_owner(ctx):
        return True
    role_id = guild_setting("supervisor_roles", ctx.guild.id)
    if not role_id:
        return False
    return any(role.id == int(role_id) for role in ctx.author.roles)


def user_is_staff(ctx):
    if user_is_supervisor(ctx) or ctx.author.guild_permissions.kick_members:
        return True
    staff_role_id = guild_setting("staff_roles", ctx.guild.id)
    if staff_role_id and any(r.id == int(staff_role_id) for r in ctx.author.roles):
        return True
    return any("staff" in r.name.lower() or "trial" in r.name.lower() or "mod" in r.name.lower() for r in ctx.author.roles)


def check_and_increment_action_limit(ctx, action_type, limit=3):
    if user_is_supervisor(ctx):
        return True, 0

    import time
    now = time.time()
    user_id = str(ctx.author.id)

    if "staff_limits" not in config:
        config["staff_limits"] = {}

    if user_id not in config["staff_limits"]:
        config["staff_limits"][user_id] = {"kicks": [], "bans": []}

    timestamps = [t for t in config["staff_limits"][user_id].get(action_type, []) if now - t < 86400]

    if len(timestamps) >= limit:
        return False, len(timestamps)

    timestamps.append(now)
    config["staff_limits"][user_id][action_type] = timestamps
    save_config()
    return True, len(timestamps)


# =====================================================================
# AUDIT LOGGING SERVICE
# =====================================================================

async def audit(guild, message):
    channel_id = guild_setting("audit_channels", guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    try:
        await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logging.exception("Failed to dispatch audit log entry.")


# =====================================================================
# TICKET SYSTEM INTERACTIVE VIEWS & CONTROLLERS
# =====================================================================

class TicketPanelActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, emoji="👋", custom_id="claim_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        emojis = get_emoji_dict(interaction.guild)
        if not user_is_staff_interaction(interaction):
            await interaction.response.send_message(f"{emojis['error']} Only staff members can claim tickets.", ephemeral=True)
            return

        button.disabled = True
        button.label = f"Claimed by {interaction.user.name}"
        button.style = discord.ButtonStyle.secondary

        staff_role_id = guild_setting("staff_roles", interaction.guild.id)
        staff_role = interaction.guild.get_role(int(staff_role_id)) if staff_role_id else discord.utils.find(lambda r: "staff team" in r.name.lower(), interaction.guild.roles)
        ping_target = staff_role.mention if staff_role else ""

        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"{emojis['success']} {ping_target} Ticket has been claimed by {interaction.user.mention}!")
        await audit(interaction.guild, f"Ticket claimed: {interaction.channel.name} by {interaction.user}")

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        emojis = get_emoji_dict(interaction.guild)
        await interaction.response.send_message(f"{emojis['warning']} Closing ticket channel in 5 seconds...", ephemeral=False)
        await audit(interaction.guild, f"Ticket closed by {interaction.user} | Channel: {interaction.channel.name}")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Closed by {interaction.user}")
        except discord.HTTPException:
            pass

def user_is_staff_interaction(interaction):
    if interaction.user.guild_permissions.kick_members:
        return True
    sup_role_id = guild_setting("supervisor_roles", interaction.guild.id)
    if sup_role_id and any(r.id == int(sup_role_id) for r in interaction.user.roles):
        return True
    staff_role_id = guild_setting("staff_roles", interaction.guild.id)
    if staff_role_id and any(r.id == int(staff_role_id) for r in interaction.user.roles):
        return True
    return any("staff" in r.name.lower() or "trial" in r.name.lower() or "mod" in r.name.lower() for r in interaction.user.roles)


class TicketSelect(discord.ui.Select):
    def __init__(self, guild=None):
        options = [
            discord.SelectOption(label="Support", description="General help and support inquiries"),
            discord.SelectOption(label="Purchase", description="Purchase service requests"),
            discord.SelectOption(label="Partnership", description="Server partnership requests")
        ]
        super().__init__(placeholder="Select a ticket category...", min_values=1, max_values=1, options=options, custom_id="ticket_category_select")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        category_name = self.values[0]
        emojis = get_emoji_dict(guild)

        existing_channel = discord.utils.find(lambda c: f"-{member.name.lower()}-" in c.name, guild.text_channels)
        if existing_channel:
            await interaction.response.send_message(f"{emojis['error']} You already have an open ticket: {existing_channel.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }

        supervisor_role_id = guild_setting("supervisor_roles", guild.id)
        if supervisor_role_id:
            sup_role = guild.get_role(int(supervisor_role_id))
            if sup_role:
                overwrites[sup_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        staff_role_id = guild_setting("staff_roles", guild.id)
        staff_role = guild.get_role(int(staff_role_id)) if staff_role_id else discord.utils.find(lambda r: "staff team" in r.name.lower(), guild.roles)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        cat_data = config.get("ticket_categories", {}).get(str(guild.id), {})
        cat_id = cat_data.get(category_name.lower()) if isinstance(cat_data, dict) else None
        
        category = guild.get_channel(int(cat_id)) if cat_id else None
        if not category:
            category = discord.utils.get(guild.categories, name="Support Tickets")
        if not category:
            category = await guild.create_category("Support Tickets")

        existing_tickets = [c for c in guild.text_channels if "-" in c.name and c.name.split("-")[0].isdigit()]
        ticket_number = len(existing_tickets) + 1

        clean_username = "".join(c for c in member.name.lower() if c.isalnum() or c in "-_")
        channel_name = f"{ticket_number}-{clean_username}-{category_name.lower()}"

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Category: {category_name} | Ticket for {member} ({member.id})"
        )

        embed = discord.Embed(
            title=f"{emojis['ticket']} Support Ticket — {category_name}",
            description=f"Hello {member.mention}!\nYou selected **{category_name}**. Support staff will be with you shortly.\n\nClick **Claim Ticket** to take ownership or **Close Ticket** when finished.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="SLS Helper • Ticket System")

        await channel.send(content=staff_role.mention if staff_role else "", embed=embed, view=TicketPanelActionsView())
        await interaction.response.send_message(f"{emojis['success']} Your ticket has been created: {channel.mention}", ephemeral=True)
        await audit(guild, f"Ticket created ({category_name}) by {member} ({member.id}) | Channel: {channel.name}")


class TicketDropdownView(discord.ui.View):
    def __init__(self, guild=None):
        super().__init__(timeout=None)
        self.add_item(TicketSelect(guild=guild))


# =====================================================================
# STAFF TRAINING SESSION SYSTEM
# =====================================================================

class TrainingControlView(discord.ui.View):
    def __init__(self, trainee_id, trainer_id):
        super().__init__(timeout=None)
        self.trainee_id = trainee_id
        self.trainer_id = trainer_id

    @discord.ui.button(label="Pass Training", style=discord.ButtonStyle.success, custom_id="pass_training_btn")
    async def pass_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        emojis = get_emoji_dict(interaction.guild)
        if interaction.user.id != self.trainer_id and not user_is_owner(interaction):
            await interaction.response.send_message(f"{emojis['error']} Only the designated trainer can complete this evaluation.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        user_id = str(self.trainee_id)

        if "trainings" not in config:
            config["trainings"] = {}
        if guild_id not in config["trainings"]:
            config["trainings"][guild_id] = {}

        config["trainings"][guild_id][user_id] = {
            "status": "PASSED",
            "trainer": str(interaction.user),
            "timestamp": discord.utils.utcnow().isoformat()
        }
        save_config()

        trainee = interaction.guild.get_member(self.trainee_id)
        trainee_mention = trainee.mention if trainee else f"<@{self.trainee_id}>"

        embed = discord.Embed(
            title=f"{emojis['success']} Staff Training Passed",
            description=f"{trainee_mention} has successfully passed staff training!",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        await audit(interaction.guild, f"Staff Training Passed: {trainee_mention} | Trainer: {interaction.user}")


# =====================================================================
# BOT COMMANDS & MODULES
# =====================================================================

@bot.command(name="setupemojis")
@commands.guild_only()
async def setupemojis(ctx):
    """Automatically downloads and uploads all blue-themed emojis to the server."""
    emojis = get_emoji_dict(ctx.guild)
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Only server owners can run setup commands.", color=discord.Color.blue()))
        return

    status_msg = await ctx.reply(embed=discord.Embed(description=f"{emojis['bullet']} Downloading and uploading blue custom emojis...", color=discord.Color.blue()))
    uploaded_count = 0

    async with aiohttp.ClientSession() as session:
        for emoji_name, url in BLUE_EMOJI_SOURCES.items():
            if discord.utils.get(ctx.guild.emojis, name=emoji_name):
                continue
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        await ctx.guild.create_custom_emoji(name=emoji_name, image=img_bytes)
                        uploaded_count += 1
            except Exception as e:
                logging.error(f"Failed to upload emoji {emoji_name}: {e}")

    updated_emojis = get_emoji_dict(ctx.guild)
    embed = discord.Embed(
        title=f"{updated_emojis['success']} Emojis Auto-Uploaded",
        description=f"Successfully added **{uploaded_count}** custom emojis to **{ctx.guild.name}**!",
        color=discord.Color.blue()
    )
    embed.set_footer(text="SLS Helper • Theme Loaded")
    await status_msg.edit(embed=embed)


@bot.command(name="sendticket")
@commands.guild_only()
async def sendticket(ctx, channel: discord.TextChannel = None):
    """Deploys the persistent ticket selection panel."""
    emojis = get_emoji_dict(ctx.guild)
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Permission denied.", color=discord.Color.blue()))
        return

    target_channel = channel or ctx.channel
    embed = discord.Embed(
        title=f"{emojis['ticket']} SLS Helper • Support Center",
        description=(
            f"Welcome to **{ctx.guild.name}** Support Center! {emojis['shield']}\n\n"
            f"Select a category below to open a ticket:\n\n"
            f"{emojis['bullet']} {emojis['support']} **Support** — General help & assistance\n"
            f"{emojis['bullet']} {emojis['purchase']} **Purchase** — Service & purchase inquiries\n"
            f"{emojis['bullet']} {emojis['partner']} **Partnership** — Server partnership requests"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="SLS Helper Ticket System")
    await target_channel.send(embed=embed, view=TicketDropdownView(guild=ctx.guild))
    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Ticket panel successfully deployed to {target_channel.mention}!", color=discord.Color.blue()))


@bot.command(name="setstaffrole")
@commands.guild_only()
async def setstaffrole(ctx, role: discord.Role):
    emojis = get_emoji_dict(ctx.guild)
    if not user_is_owner(ctx):
        return
    if "staff_roles" not in config:
        config["staff_roles"] = {}
    config["staff_roles"][str(ctx.guild.id)] = role.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Ticket staff role set to {role.mention}.", color=discord.Color.blue()))


@bot.command(name="setcategory")
@commands.guild_only()
async def setcategory(ctx, ticket_type: str, category: discord.CategoryChannel):
    emojis = get_emoji_dict(ctx.guild)
    if not user_is_owner(ctx):
        return
    ticket_type = ticket_type.lower()
    if ticket_type not in ["support", "purchase", "partnership"]:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Invalid type! Choose from: `support`, `purchase`, `partnership`.", color=discord.Color.blue()))
        return
    guild_id = str(ctx.guild.id)
    if "ticket_categories" not in config:
        config["ticket_categories"] = {}
    if guild_id not in config["ticket_categories"]:
        config["ticket_categories"][guild_id] = {}
    config["ticket_categories"][guild_id][ticket_type] = category.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Category for **{ticket_type}** set to **{category.name}**.", color=discord.Color.blue()))


@bot.command(name="kick")
@commands.guild_only()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    emojis = get_emoji_dict(ctx.guild)
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Permission denied.", color=discord.Color.blue()))
        return
    allowed, count = check_and_increment_action_limit(ctx, "kicks", limit=3)
    if not allowed:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['warning']} Daily limit of 3 kicks reached.", color=discord.Color.blue()))
        return
    try:
        await member.kick(reason=reason)
        await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Kicked {member.mention} | Reason: {reason}", color=discord.Color.blue()))
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Missing permissions to kick user.", color=discord.Color.blue()))


@bot.command(name="ban")
@commands.guild_only()
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    emojis = get_emoji_dict(ctx.guild)
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Permission denied.", color=discord.Color.blue()))
        return
    allowed, count = check_and_increment_action_limit(ctx, "bans", limit=3)
    if not allowed:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['warning']} Daily limit of 3 bans reached.", color=discord.Color.blue()))
        return
    try:
        await member.ban(reason=reason)
        await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Banned {member.mention} | Reason: {reason}", color=discord.Color.blue()))
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Missing permissions to ban user.", color=discord.Color.blue()))


@bot.command(name="ping")
@commands.guild_only()
async def ping(ctx):
    emojis = get_emoji_dict(ctx.guild)
    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} SLS Helper Latency: `{round(bot.latency * 1000)}ms`", color=discord.Color.blue()))


@bot.command(name="help")
async def help_command(ctx):
    emojis = get_emoji_dict(ctx.guild)
    embed = discord.Embed(
        title=f"{emojis['gear']} SLS Helper • Command Center",
        description="Comprehensive blue-themed moderation & utility command center:",
        color=discord.Color.blue()
    )
    embed.add_field(name=f"{emojis['shield']} Staff & Management", value="`>promo`, `>demo`, `>super`, `>staff`, `>train`, `>trainings`", inline=False)
    embed.add_field(name=f"{emojis['warning']} Moderation", value="`>kick`, `>ban`, `>unban`, `>mute`, `>unmute`, `>warn`, `>unwarn`, `>clear`", inline=False)
    embed.add_field(name=f"{emojis['ticket']} Support & Tickets", value="`>sendticket`, `>setstaffrole @role`, `>setcategory <type> #category`", inline=False)
    embed.add_field(name=f"{emojis['gear']} Setup & Emojis", value="`>setupemojis`, `>ranks add @role`, `>ranks clear`, `>setstaffsupervisor`, `>setpromodemo`, `>setaudit`", inline=False)
    embed.add_field(name=f"{emojis['user']} Utility", value="`>ping`, `>serverinfo`, `>userinfo`, `>avatar`", inline=False)
    embed.set_footer(text="SLS Helper System")
    await ctx.reply(embed=embed, mention_author=False)


@bot.event
async def on_ready():
    bot.add_view(TicketDropdownView())
    bot.add_view(TicketPanelActionsView())
    logging.info("SLS Helper successfully logged in as %s", bot.user)


load_config()
bot.run(TOKEN)
