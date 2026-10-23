import os
import json
import logging
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands

# =========================
# CONFIGURATION
# =========================

logging.basicConfig(level=logging.INFO)

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

# =========================
# CUSTOM BLUE EMOJI MAPPING
# =========================

EMOJIS = {
    "promo": "<a:blue_star:3045>",
    "demo": "<:blue_deer:6019>",
    "shield": "<a:blue_fire:31347>",
    "gear": "<:blue_deer:6019>",
    "ladder": "<a:blue_star:3045>",
    "announcement": "<a:blue_fire:31347>",
    "audit": "<a:blue_star:3045>",
    "success": "<a:blue_star:3045>",
    "warning": "<a:blue_fire:31347>",
    "error": "<a:blue_fire:31347>",
    "user": "<:blue_deer:6019>",
    "bullet": "<a:blue_star:3045>",
    "welcome": "<a:blue_fire:31347>",
    "ticket": "<a:blue_star:3045>",
    "support": "<:blue_deer:6019>",
    "purchase": "<a:blue_star:3045>",
    "partner": "<a:blue_fire:31347>"
}

# Auto-upload URLs for your selected blue animated/aesthetic emojis
BLUE_EMOJI_SOURCES = {
    "blue_star": "https://cdn3.emoji.gg/emojis/3045-blue-star.gif",
    "blue_fire": "https://cdn3.emoji.gg/emojis/31347-bluefire.gif",
    "blue_deer": "https://cdn3.emoji.gg/emojis/6019-blue-deer.png"
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
        logging.exception("Could not load config file")


def save_config():
    temporary_file = CONFIG_FILE + ".tmp"
    try:
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)
        os.replace(temporary_file, CONFIG_FILE)
    except OSError:
        logging.exception("Could not save configuration")


def guild_setting(setting, guild_id):
    return config[setting].get(str(guild_id))


# =========================
# PERMISSION & LIMIT HELPERS
# =========================

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


# =========================
# AUDIT LOGGING
# =========================

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
        logging.exception("Failed to send audit log")


# =========================
# TICKET SYSTEM INTERACTIVE VIEWS
# =========================

class TicketPanelActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, custom_id="claim_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_staff_interaction(interaction):
            await interaction.response.send_message(f"{EMOJIS['error']} Only staff members can claim tickets.", ephemeral=True)
            return

        button.disabled = True
        button.label = f"Claimed by {interaction.user.name}"
        button.style = discord.ButtonStyle.secondary

        staff_role_id = guild_setting("staff_roles", interaction.guild.id)
        staff_role = interaction.guild.get_role(int(staff_role_id)) if staff_role_id else discord.utils.find(lambda r: "staff team" in r.name.lower(), interaction.guild.roles)
        ping_target = staff_role.mention if staff_role else ""

        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"{EMOJIS['success']} {ping_target} Ticket has been claimed by {interaction.user.mention}!")
        await audit(interaction.guild, f"Ticket claimed: {interaction.channel.name} by {interaction.user}")

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"{EMOJIS['warning']} Closing ticket in 5 seconds...", ephemeral=False)
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
    def __init__(self):
        options = [
            discord.SelectOption(label="Support", description="General help and support inquiries", emoji=discord.PartialEmoji.from_str(EMOJIS['support'])),
            discord.SelectOption(label="Purchase", description="Purchase service requests", emoji=discord.PartialEmoji.from_str(EMOJIS['purchase'])),
            discord.SelectOption(label="Partnership", description="Server partnership requests", emoji=discord.PartialEmoji.from_str(EMOJIS['partner']))
        ]
        super().__init__(placeholder="Select a ticket category...", min_values=1, max_values=1, options=options, custom_id="ticket_category_select")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        category_name = self.values[0]

        existing_channel = discord.utils.find(lambda c: f"-{member.name.lower()}-" in c.name, guild.text_channels)
        if existing_channel:
            await interaction.response.send_message(f"{EMOJIS['error']} You already have an open ticket: {existing_channel.mention}", ephemeral=True)
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
            title=f"{EMOJIS['ticket']} Support Ticket — {category_name}",
            description=f"Hello {member.mention}!\nYou selected **{category_name}**. Support staff will be with you shortly.\n\nClick **Claim Ticket** to take ownership or **Close Ticket** when finished.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="SLS Helper • Ticket System")

        await channel.send(content=staff_role.mention if staff_role else "", embed=embed, view=TicketPanelActionsView())
        await interaction.response.send_message(f"{EMOJIS['success']} Your ticket has been created: {channel.mention}", ephemeral=True)
        await audit(guild, f"Ticket created ({category_name}) by {member} ({member.id}) | Channel: {channel.name}")


class TicketDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# =========================
# AUTO EMOJI UPLOADER
# =========================

@bot.command(name="setupemojis")
@commands.guild_only()
async def setupemojis(ctx):
    """Automatically downloads and uploads your custom blue emojis to the server."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only server owners can run setup commands.", color=discord.Color.blue()))
        return

    status_msg = await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['bullet']} Uploading your selected blue emojis...", color=discord.Color.blue()))
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
                logging.error(f"Failed to upload {emoji_name}: {e}")

    embed = discord.Embed(
        title=f"{EMOJIS['success']} Blue Emojis Auto-Uploaded",
        description=f"Successfully added **{uploaded_count}** custom emojis to **{ctx.guild.name}**!",
        color=discord.Color.blue()
    )
    embed.set_footer(text="SLS Helper • Theme Loaded")
    await status_msg.edit(embed=embed)


# =========================
# EMBED HELPERS
# =========================

async def send_promodemo_embed(guild, member, role, action, moderator):
    channel_id = guild_setting("promodemo_channels", guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return

    promoted = action == "promoted"
    embed = discord.Embed(
        title=f"{EMOJIS['promo']} Staff Promotion" if promoted else f"{EMOJIS['demo']} Staff Demotion",
        description=f"{member.mention} has been **promoted**!" if promoted else f"{member.mention} has been **demoted**.",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name=f"{EMOJIS['user']} Staff Member", value=f"{member.mention}\n`{member.id}`", inline=False)
    embed.add_field(name=f"{EMOJIS['ladder']} Role", value=role.mention, inline=True)
    embed.add_field(name=f"{EMOJIS['shield']} Action By", value=moderator.mention, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{guild.name} • SLS Helper")

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


async def change_staff_role(ctx, member, target_role, action):
    if target_role is None:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Role not found.", color=discord.Color.blue()))
        return

    try:
        if action == "promote":
            await member.add_roles(target_role, reason=f"Staff promotion by {ctx.author}")
            result = "promoted"
        else:
            await member.remove_roles(target_role, reason=f"Staff demotion by {ctx.author}")
            result = "demoted"

        await send_promodemo_embed(ctx.guild, member, target_role, result, ctx.author)
        await audit(ctx.guild, f"Staff {result}: {member} | Role: {target_role.name} | By: {ctx.author}")
        emoji = EMOJIS['promo'] if result == "promoted" else EMOJIS['demo']
        await ctx.reply(embed=discord.Embed(description=f"{emoji} {member.mention} was **{result}**: {target_role.mention}", color=discord.Color.blue()))
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Missing permissions.", color=discord.Color.blue()))


# =========================
# STAFF TRAINING COMMANDS
# =========================

class TrainingControlView(discord.ui.View):
    def __init__(self, trainee_id, trainer_id):
        super().__init__(timeout=None)
        self.trainee_id = trainee_id
        self.trainer_id = trainer_id

    @discord.ui.button(label="Pass Training", style=discord.ButtonStyle.primary, custom_id="pass_training_btn")
    async def pass_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.trainer_id and not user_is_owner(interaction):
            await interaction.response.send_message(f"{EMOJIS['error']} Permission denied.", ephemeral=True)
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
            title=f"{EMOJIS['success']} Training Passed!",
            description=f"{trainee_mention} has passed staff training!",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


@bot.command(name="train")
@commands.guild_only()
async def train(ctx, trainee: discord.Member):
    """Starts staff training."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Permission denied.", color=discord.Color.blue()))
        return

    embed = discord.Embed(
        title=f"{EMOJIS['shield']} Staff Training Session",
        description=f"Welcome {trainee.mention} to your training session!",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name=f"{EMOJIS['user']} Trainee", value=trainee.mention, inline=True)
    embed.add_field(name=f"{EMOJIS['shield']} Trainer", value=ctx.author.mention, inline=True)
    embed.set_footer(text="SLS Helper Training")

    view = TrainingControlView(trainee_id=trainee.id, trainer_id=ctx.author.id)
    await ctx.send(embed=embed, view=view)


@bot.command(name="sendticket")
@commands.guild_only()
async def sendticket(ctx, channel: discord.TextChannel = None):
    """Deploys ticket panel."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Permission denied.", color=discord.Color.blue()))
        return

    target_channel = channel or ctx.channel
    embed = discord.Embed(
        title=f"{EMOJIS['ticket']} SLS Helper • Support Center",
        description=(
            f"Welcome to **{ctx.guild.name}**! {EMOJIS['shield']}\n\n"
            f"Select a category below:\n\n"
            f"{EMOJIS['bullet']} {EMOJIS['support']} **Support** — General help\n"
            f"{EMOJIS['bullet']} {EMOJIS['purchase']} **Purchase** — Purchases\n"
            f"{EMOJIS['bullet']} {EMOJIS['partner']} **Partnership** — Partnerships"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="SLS Helper Ticket System")
    await target_channel.send(embed=embed, view=TicketDropdownView())
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Panel deployed!", color=discord.Color.blue()))


@bot.command(name="setstaffrole")
@commands.guild_only()
async def setstaffrole(ctx, role: discord.Role):
    if not user_is_owner(ctx):
        return
    if "staff_roles" not in config:
        config["staff_roles"] = {}
    config["staff_roles"][str(ctx.guild.id)] = role.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Staff role set to {role.mention}.", color=discord.Color.blue()))


@bot.command(name="setcategory")
@commands.guild_only()
async def setcategory(ctx, ticket_type: str, category: discord.CategoryChannel):
    if not user_is_owner(ctx):
        return
    ticket_type = ticket_type.lower()
    if ticket_type not in ["support", "purchase", "partnership"]:
        return
    guild_id = str(ctx.guild.id)
    if "ticket_categories" not in config:
        config["ticket_categories"] = {}
    if guild_id not in config["ticket_categories"]:
        config["ticket_categories"][guild_id] = {}
    config["ticket_categories"][guild_id][ticket_type] = category.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Category for **{ticket_type}** set to **{category.name}**.", color=discord.Color.blue()))


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(title=f"{EMOJIS['gear']} SLS Helper • Command Center", description="Blue themed utility & moderation commands:", color=discord.Color.blue())
    embed.add_field(name=f"{EMOJIS['shield']} Commands", value="`>sendticket`, `>setupemojis`, `>train`, `>promo`, `>demo`, `>kick`, `>ban`, `>ping`", inline=False)
    embed.set_footer(text="SLS Helper")
    await ctx.reply(embed=embed, mention_author=False)


@bot.event
async def on_ready():
    bot.add_view(TicketDropdownView())
    bot.add_view(TicketPanelActionsView())
    logging.info("SLS Helper logged in as %s", bot.user)


load_config()
bot.run(TOKEN)
