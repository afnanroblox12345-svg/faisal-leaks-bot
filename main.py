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
# CUSTOM EMOJI CONFIGURATION
# =========================

EMOJIS = {
    "promo": "<a:giveaway:1561077598791016591>",
    "demo": "<:angry:1561078014895329331>",
    "shield": "<:z_mod_DiscordShield:1561078954519961622>",
    "gear": "<:Settings:1561077371895943319>",
    "ladder": "<:16400redswordrankicon:1561077871206989845>",
    "announcement": "<:announcement:1561079523641004162>",
    "audit": "<a:a7_book:1561077741716111362>",
    "success": "<a:MW_tick:1561077516905484448>",
    "warning": "<a:03_awarndns:1561077438816194632>",
    "error": "<a:error:1561078063968686081>",
    "user": "<:ntl_user:1561077921395904653>",
    "bullet": "<:MW_arrow_right:1561077250638610563>",
    "welcome": "<a:wel:1561077660648738876>",
    "ticket": "<:ticket:1560983848345665637>",
    "support": "<:Support:1561328482724614238>",
    "purchase": "<a:decomp:1561328437057032222>",
    "partner": "<:Partner:1561337139373932593>"
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
    "trainings": {},
    "economy": {},
    "economy": {},
    "log_channels": {},
    "economy_channels": {}
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


async def log_server_event(guild, title, description, color=discord.Color.blurple()):
    """Send a server event as an embed to its configured logging channel."""
    if guild is None:
        return
    channel_id = guild_setting("log_channels", guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    embed = discord.Embed(
        title=f"{EMOJIS['audit']} {title}",
        description=(description or "No additional details.")[:4000],
        color=color,
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"{guild.name} • Server Event Log")
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logging.exception("Failed to send server event log")


def economy_channel_allowed(ctx):
    """Restrict all economy commands to the server's configured economy channel."""
    economy_commands = {
        "economy", "balance", "daily", "work", "beg", "crime", "deposit", "withdraw",
        "pay", "leaderboard", "shop", "buy", "inventory", "sell", "bankupgrade", "rob",
        "slots", "betflip", "addmoney", "removemoney", "setmoney", "addbank", "setbank",
        "resetmoney", "reseteco"
    }
    if ctx.guild is None or ctx.command is None or ctx.command.name not in economy_commands:
        return True
    channel_id = guild_setting("economy_channels", ctx.guild.id)
    return not channel_id or ctx.channel.id == int(channel_id)


@bot.check
async def enforce_economy_channel(ctx):
    if economy_channel_allowed(ctx):
        return True
    raise commands.CheckFailure("Economy commands can only be used in the configured economy channel.")


# =========================
# TICKET SYSTEM INTERACTIVE VIEWS
# =========================

class TicketPanelActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.green, emoji="👋", custom_id="claim_ticket_btn")
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

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒", custom_id="close_ticket_btn")
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

        # Check if user already has a ticket open containing their username
        existing_channel = discord.utils.get(guild.text_channels, name=f"-{member.name.lower()}-")
        if not existing_channel:
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

        # Fetch category mapping
        cat_data = config.get("ticket_categories", {}).get(str(guild.id), {})
        cat_id = cat_data.get(category_name.lower()) if isinstance(cat_data, dict) else None
        
        category = guild.get_channel(int(cat_id)) if cat_id else None
        if not category:
            category = discord.utils.get(guild.categories, name="Support Tickets")
        if not category:
            category = await guild.create_category("Support Tickets")

        # Calculate next ticket number based on existing channels in the guild
        existing_tickets = [c for c in guild.text_channels if "-" in c.name and c.name.split("-")[0].isdigit()]
        ticket_number = len(existing_tickets) + 1

        # Format: (ticket number)-(username)-(ticket category name) -> e.g. 1-silent-support
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
        embed.set_footer(text="Faisal Mod • Ticket System")

        await channel.send(content=staff_role.mention if staff_role else "", embed=embed, view=TicketPanelActionsView())
        await interaction.response.send_message(f"{EMOJIS['success']} Your ticket has been created: {channel.mention}", ephemeral=True)
        await audit(guild, f"Ticket created ({category_name}) by {member} ({member.id}) | Channel: {channel.name}")


class TicketDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


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
        color=discord.Color.green() if promoted else discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name=f"{EMOJIS['user']} Staff Member", value=f"{member.mention}\n`{member.id}`", inline=False)
    embed.add_field(name=f"{EMOJIS['ladder']} Role", value=role.mention, inline=True)
    embed.add_field(name=f"{EMOJIS['shield']} Action By", value=moderator.mention, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{guild.name} • Faisal Mod System")

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


async def change_staff_role(ctx, member, target_role, action):
    if target_role is None:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} The specified or configured role could not be found in this server.", color=discord.Color.red()))
        return

    if member.id == ctx.author.id or member.id == ctx.guild.owner_id or target_role.is_default() or target_role.managed:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} Action unauthorized or invalid role.", color=discord.Color.orange()))
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
        await ctx.reply(embed=discord.Embed(description=f"{emoji} {member.mention} was **{result}**: {target_role.mention}", color=discord.Color.green() if result == "promoted" else discord.Color.red()))
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Missing permissions to modify roles.", color=discord.Color.red()))


# =========================
# STAFF TRAINING COMMANDS
# =========================

class TrainingControlView(discord.ui.View):
    def __init__(self, trainee_id, trainer_id):
        super().__init__(timeout=None)
        self.trainee_id = trainee_id
        self.trainer_id = trainer_id

    @discord.ui.button(label="Pass Training", style=discord.ButtonStyle.green, custom_id="pass_training_btn")
    async def pass_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.trainer_id and interaction.user.id != interaction.guild.owner_id and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(f"{EMOJIS['error']} Only the designated trainer can complete this evaluation.", ephemeral=True)
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
            description=f"{trainee_mention} has successfully passed staff training!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name=f"{EMOJIS['user']} Trainee", value=trainee_mention, inline=True)
        embed.add_field(name=f"{EMOJIS['shield']} Trainer", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Faisal Mod • Staff Training System")

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        await audit(interaction.guild, f"Staff Training Passed: {trainee_mention} | Trainer: {interaction.user}")

    @discord.ui.button(label="Fail Training", style=discord.ButtonStyle.red, custom_id="fail_training_btn")
    async def fail_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.trainer_id and interaction.user.id != interaction.guild.owner_id and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(f"{EMOJIS['error']} Only the designated trainer can complete this evaluation.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        user_id = str(self.trainee_id)

        if "trainings" not in config:
            config["trainings"] = {}
        if guild_id not in config["trainings"]:
            config["trainings"][guild_id] = {}

        config["trainings"][guild_id][user_id] = {
            "status": "FAILED",
            "trainer": str(interaction.user),
            "timestamp": discord.utils.utcnow().isoformat()
        }
        save_config()

        trainee = interaction.guild.get_member(self.trainee_id)
        trainee_mention = trainee.mention if trainee else f"<@{self.trainee_id}>"

        embed = discord.Embed(
            title=f"{EMOJIS['demo']} Training Failed",
            description=f"{trainee_mention} did not pass staff training at this time.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name=f"{EMOJIS['user']} Trainee", value=trainee_mention, inline=True)
        embed.add_field(name=f"{EMOJIS['shield']} Trainer", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Faisal Mod • Staff Training System")

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        await audit(interaction.guild, f"Staff Training Failed: {trainee_mention} | Trainer: {interaction.user}")


@bot.command(name="train")
@commands.guild_only()
async def train(ctx, trainee: discord.Member):
    """Starts an interactive training module for a staff member."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only staff supervisors can initiate training sessions.", color=discord.Color.red()))
        return

    embed = discord.Embed(
        title=f"{EMOJIS['shield']} Staff Training Session Initiated",
        description=f"Welcome {trainee.mention} to your official staff training session!",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name=f"{EMOJIS['user']} Trainee Info",
        value=f"{trainee.mention}\nID: `{trainee.id}`",
        inline=True
    )
    embed.add_field(
        name=f"{EMOJIS['shield']} Trainer",
        value=ctx.author.mention,
        inline=True
    )

    embed.add_field(
        name=f"{EMOJIS['gear']} Training Modules & Curriculum",
        value=(
            f"{EMOJIS['bullet']} **1. Moderation Quotas:** Max 3 kicks/bans per 24 hours.\n"
            f"{EMOJIS['bullet']} **2. Moderation Tools:** Use `>warn`, `>mute`, `>clear`, `>kick`, and `>ban` appropriately.\n"
            f"{EMOJIS['bullet']} **3. Ticket Management:** Assist users politely and close tickets using button controls.\n"
            f"{EMOJIS['bullet']} **4. Hierarchy & Respect:** Do not attempt commands on higher ranks."
        ),
        inline=False
    )

    embed.set_footer(text=f"{ctx.guild.name} • Trainer Controls Below", icon_url=ctx.author.display_avatar.url)

    view = TrainingControlView(trainee_id=trainee.id, trainer_id=ctx.author.id)
    await ctx.send(embed=embed, view=view)
    await audit(interaction=ctx.guild, message=f"Staff Training Started: {trainee} ({trainee.id}) by {ctx.author}")


@bot.command(name="trainings")
@commands.guild_only()
async def trainings(ctx, member: discord.Member = None):
    """Checks the training status of a staff member."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    m = member or ctx.author
    guild_id = str(ctx.guild.id)
    user_id = str(m.id)

    record = config.get("trainings", {}).get(guild_id, {}).get(user_id)

    embed = discord.Embed(
        title=f"{EMOJIS['audit']} Staff Training Record",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=m.display_avatar.url)

    if not record:
        embed.description = f"{m.mention} has no recorded training sessions yet."
    else:
        status_emoji = EMOJIS['success'] if record['status'] == "PASSED" else EMOJIS['demo']
        embed.description = f"Training status for {m.mention}:"
        embed.add_field(name=f"{status_emoji} Status", value=f"**{record['status']}**", inline=True)
        embed.add_field(name=f"{EMOJIS['shield']} Evaluated By", value=record['trainer'], inline=True)

    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await ctx.reply(embed=embed)


# =========================
# MANAGEMENT & STAFF COMMANDS
# =========================

@bot.command(name="promo")
@commands.guild_only()
async def promo(ctx, staff: discord.Member, target_role: discord.Role = None):
    """Promotes a staff member."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    if target_role is None:
        ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id))
        if not ladder:
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} No rank ladder configured. Add roles using `>ranks add @role`", color=discord.Color.orange()))
            return

        user_role_ids = [r.id for r in staff.roles]
        matched_index = -1
        
        for idx, r_id in enumerate(ladder):
            if r_id in user_role_ids:
                matched_index = idx

        next_index = matched_index + 1
        if next_index >= len(ladder):
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} {staff.mention} is already at the highest rank on the ladder!", color=discord.Color.orange()))
            return

        target_role = ctx.guild.get_role(ladder[next_index])

    await change_staff_role(ctx, staff, target_role, "promote")


@bot.command(name="demo")
@commands.guild_only()
async def demo(ctx, staff: discord.Member, target_role: discord.Role = None):
    """Demotes a staff member from their highest ladder rank."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    if target_role is None:
        ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id))
        if not ladder:
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} No rank ladder configured. Add roles using `>ranks add @role`", color=discord.Color.orange()))
            return

        user_role_ids = [r.id for r in staff.roles]
        
        matched_index = -1
        for idx, r_id in enumerate(ladder):
            if r_id in user_role_ids:
                matched_index = idx

        if matched_index == -1:
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} {staff.mention} does not have any rank from the ladder!", color=discord.Color.orange()))
            return

        target_role = ctx.guild.get_role(ladder[matched_index])

    await change_staff_role(ctx, staff, target_role, "demote")


@bot.command(name="super")
@commands.guild_only()
async def super_cmd(ctx, member: discord.Member):
    """Assigns the supervisor role."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    role_id = guild_setting("supervisor_roles", ctx.guild.id)
    if not role_id:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} Supervisor role not set up.", color=discord.Color.orange()))
        return
    assigned_role = ctx.guild.get_role(int(role_id))
    if not assigned_role:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Configured supervisor role no longer exists.", color=discord.Color.red()))
        return
    await member.add_roles(assigned_role, reason=f"Supervisor assigned by {ctx.author}")
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Assigned supervisor role to {member.mention}.", color=discord.Color.green()))


@bot.command(name="superintro")
@commands.guild_only()
async def superintro(ctx):
    """Deletes the trigger message and introduces supervisor commands."""
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    if not user_is_supervisor(ctx):
        err_msg = await ctx.send(embed=discord.Embed(description=f"{EMOJIS['error']} Only staff supervisors can use this command.", color=discord.Color.red()))
        await err_msg.delete(delay=5)
        return

    embed = discord.Embed(
        title=f"{EMOJIS['welcome']} Welcome Staff Supervisor!",
        description=(
            f"Welcome to the **Faisal Mod Supervisor System**! {EMOJIS['shield']}\n"
            "As a Supervisor, you have permission to manage the staff hierarchy using automated rank ladder commands."
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name=f"{EMOJIS['promo']} `>promo @member [@role]`",
        value=(
            f"{EMOJIS['bullet']} Promotes a staff member.\n"
            f"{EMOJIS['bullet']} **Auto Ladder:** If no role is given, advances them to the next step up."
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['demo']} `>demo @member [@role]`",
        value=(
            f"{EMOJIS['bullet']} Demotes a staff member.\n"
            f"{EMOJIS['bullet']} **Auto Ladder:** If no role is given, strips their highest rank to drop them down."
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['gear']} `>train @member`",
        value=f"{EMOJIS['bullet']} Starts an interactive staff training session.",
        inline=False
    )

    embed.set_footer(text=f"Requested by {ctx.author.display_name} • Faisal Mod Guide", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="staffintro")
@commands.guild_only()
async def staffintro(ctx):
    """Deletes the trigger message and introduces staff moderation commands."""
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    if not user_is_staff(ctx):
        err_msg = await ctx.send(embed=discord.Embed(description=f"{EMOJIS['error']} Only staff members can use this command.", color=discord.Color.red()))
        await err_msg.delete(delay=5)
        return

    embed = discord.Embed(
        title=f"{EMOJIS['welcome']} Welcome to the Faisal Mod Staff Team!",
        description=(
            f"Hello {ctx.author.mention}! Thank you for keeping our community safe and active. {EMOJIS['shield']}\n"
            "Here is a quick introduction to your staff moderation tools and commands."
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name=f"{EMOJIS['warning']} Moderation & Safety Commands",
        value=(
            f"{EMOJIS['bullet']} `>kick @member [reason]` — Kicks a disruptive user (Max 3/24h).\n"
            f"{EMOJIS['bullet']} `>ban @member [reason]` — Permanently bans a rule-breaker (Max 3/24h).\n"
            f"{EMOJIS['bullet']} `>unban <user_id> [reason]` — Unbans a user by ID.\n"
            f"{EMOJIS['bullet']} `>mute @member [reason]` — Times out a user for 10 minutes.\n"
            f"{EMOJIS['bullet']} `>unmute @member [reason]` — Removes timeout from a member.\n"
            f"{EMOJIS['bullet']} `>warn @member [reason]` — Issues a formal warning.\n"
            f"{EMOJIS['bullet']} `>unwarn @member [index]` — Removes a warning.\n"
            f"{EMOJIS['bullet']} `>clear [amount]` — Purges chat messages."
        ),
        inline=False
    )

    embed.set_footer(text=f"Requested by {ctx.author.display_name} • Faisal Mod Guide", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="staff")
@commands.guild_only()
async def staff_cmd(ctx, member: discord.Member):
    """Assigns Staff Team and Trial Mod/Moderator roles automatically."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    staff_team_role = discord.utils.find(lambda r: "staff team" in r.name.lower(), ctx.guild.roles)
    trial_mod_role = discord.utils.find(lambda r: "trial mod" in r.name.lower() or "trial moderator" in r.name.lower(), ctx.guild.roles)

    found_roles = [r for r in [staff_team_role, trial_mod_role] if r]
    if not found_roles:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Could not find 'Staff Team' or 'Trial Mod/Moderator' roles in this server.", color=discord.Color.red()))
        return

    await member.add_roles(*found_roles, reason=f"Staff roles assigned by {ctx.author}")
    assigned_mentions = ", ".join([r.mention for r in found_roles])
    
    embed = discord.Embed(
        title=f"{EMOJIS['success']} Staff Team Roles Assigned",
        description=f"Successfully assigned {assigned_mentions} to {member.mention}.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"Action by {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=embed)
    await audit(ctx.guild, f"Staff roles ({assigned_mentions}) given to {member} ({member.id}) by {ctx.author}")


@bot.command(name="role")
@commands.guild_only()
async def role_cmd(ctx, member: discord.Member, target_role: discord.Role):
    """Toggles a role on a member, ensuring users cannot manage roles higher or equal to their own."""
    is_owner = (ctx.author.id == OWNER_ID or ctx.author.id == ctx.guild.owner_id)

    if not is_owner and not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    if target_role.position >= ctx.guild.me.top_role.position:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} I cannot manage that role because it is higher than or equal to my highest role.", color=discord.Color.red()))
        return

    if not is_owner and target_role.position >= ctx.author.top_role.position:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You cannot manage a role that is higher than or equal to your own highest role.", color=discord.Color.red()))
        return

    if target_role in member.roles:
        try:
            await member.remove_roles(target_role, reason=f"Role toggled off by {ctx.author}")
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['demo']} Removed {target_role.mention} from {member.mention}.", color=discord.Color.red()))
        except discord.Forbidden:
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Missing permissions to remove that role.", color=discord.Color.red()))
    else:
        try:
            await member.add_roles(target_role, reason=f"Role toggled on by {ctx.author}")
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['promo']} Added {target_role.mention} to {member.mention}.", color=discord.Color.green()))
        except discord.Forbidden:
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Missing permissions to assign that role.", color=discord.Color.red()))


@bot.command(name="steal")
@commands.guild_only()
async def steal(ctx, emoji: str, name: str = None):
    """Steals an emoji into the server."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    import re
    match = re.match(r"<(a?):([a-zA-Z0-9_]+):([0-9]+)>", emoji)
    if not match:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Invalid custom emoji.", color=discord.Color.red()))
        return
    animated, e_name, e_id = match.groups()
    url = f"https://cdn.discordapp.com/emojis/{e_id}.{'gif' if animated=='a' else 'png'}?v=1"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            image_bytes = await resp.read()
    new_emoji = await ctx.guild.create_custom_emoji(name=name or e_name, image=image_bytes)
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Stole and added {new_emoji}!", color=discord.Color.green()))


# =========================
# TICKET SETUP COMMANDS
# =========================

@bot.command(name="sendticket")
@commands.guild_only()
async def sendticket(ctx, channel: discord.TextChannel = None):
    """Deploys the persistent ticket selection dropdown panel to a channel."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only owners or supervisors can deploy the ticket panel.", color=discord.Color.red()))
        return

    target_channel = channel or ctx.channel

    embed = discord.Embed(
        title=f"{EMOJIS['ticket']} Support Ticket Center",
        description=(
            f"Welcome to the **{ctx.guild.name}** Support Center! {EMOJIS['shield']}\n\n"
            f"Please select a category from the dropdown menu below to open a private ticket with our staff team:\n\n"
            f"{EMOJIS['bullet']} {EMOJIS['support']} **Support** — General help & assistance\n"
            f"{EMOJIS['bullet']} {EMOJIS['purchase']} **Purchase** — Purchase service requests\n"
            f"{EMOJIS['bullet']} {EMOJIS['partner']} **Partnership** — Server partnership requests"
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text="Faisal Mod • Support System", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)

    await target_channel.send(embed=embed, view=TicketDropdownView())
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Successfully deployed ticket panel to {target_channel.mention}!", color=discord.Color.green()))


@bot.command(name="setstaffrole")
@commands.guild_only()
async def setstaffrole(ctx, role: discord.Role):
    """Sets the staff role that can view, claim, and get pinged in tickets."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    if "staff_roles" not in config:
        config["staff_roles"] = {}
    config["staff_roles"][str(ctx.guild.id)] = role.id
    save_config()

    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Ticket staff role set to {role.mention}.", color=discord.Color.green()))


@bot.command(name="setcategory")
@commands.guild_only()
async def setcategory(ctx, ticket_type: str, category: discord.CategoryChannel):
    """Sets the Discord category for a specific ticket type (support, purchase, partnership)."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    ticket_type = ticket_type.lower()
    if ticket_type not in ["support", "purchase", "partnership"]:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Invalid type! Choose from: `support`, `purchase`, `partnership`.\nExample: `>setcategory support #CategoryName`", color=discord.Color.red()))
        return

    guild_id = str(ctx.guild.id)
    if "ticket_categories" not in config or not isinstance(config["ticket_categories"], dict):
        config["ticket_categories"] = {}
    
    if guild_id not in config["ticket_categories"] or not isinstance(config["ticket_categories"][guild_id], dict):
        config["ticket_categories"][guild_id] = {}

    config["ticket_categories"][guild_id][ticket_type] = category.id
    save_config()

    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Category for **{ticket_type.capitalize()}** tickets set to **{category.name}**.", color=discord.Color.green()))


# =========================
# MODERATION COMMANDS
# =========================

@bot.command(name="kick")
@commands.guild_only()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    """Kicks a member (Staff capped at 3 per 24 hours with hierarchy checks)."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    if member.id == ctx.guild.owner_id or member.id == OWNER_ID:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You cannot kick the server owner or bot owner.", color=discord.Color.red()))
        return

    if member.id == ctx.author.id:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} You cannot kick yourself.", color=discord.Color.orange()))
        return

    if not user_is_owner(ctx) and member.top_role.position >= ctx.author.top_role.position:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You cannot kick {member.mention} because their highest role is higher than or equal to yours.", color=discord.Color.red()))
        return

    allowed, count = check_and_increment_action_limit(ctx, "kicks", limit=3)
    if not allowed:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} You have reached your limit of **3 kicks per 24 hours**.", color=discord.Color.orange()))
        return

    try:
        await member.kick(reason=f"{reason} (Kicked by {ctx.author})")
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Kicked {member.mention} | Reason: {reason}", color=discord.Color.orange()))
        await audit(ctx.guild, f"Member kicked: {member} ({member.id}) | Reason: {reason} | By: {ctx.author}")
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} I lack permissions to kick that member.", color=discord.Color.red()))


@bot.command(name="ban")
@commands.guild_only()
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    """Bans a member (Staff capped at 3 per 24 hours with hierarchy checks)."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    if member.id == ctx.guild.owner_id or member.id == OWNER_ID:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You cannot ban the server owner or bot owner.", color=discord.Color.red()))
        return

    if member.id == ctx.author.id:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} You cannot ban yourself.", color=discord.Color.orange()))
        return

    if not user_is_owner(ctx) and member.top_role.position >= ctx.author.top_role.position:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You cannot ban {member.mention} because their highest role is higher than or equal to yours.", color=discord.Color.red()))
        return

    allowed, count = check_and_increment_action_limit(ctx, "bans", limit=3)
    if not allowed:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} You have reached your limit of **3 bans per 24 hours**.", color=discord.Color.orange()))
        return

    try:
        await member.ban(reason=f"{reason} (Banned by {ctx.author})")
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Banned {member.mention} | Reason: {reason}", color=discord.Color.red()))
        await audit(ctx.guild, f"Member banned: {member} ({member.id}) | Reason: {reason} | By: {ctx.author}")
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} I lack permissions to ban that member.", color=discord.Color.red()))


@bot.command(name="unban")
@commands.guild_only()
async def unban(ctx, user_id: int, *, reason="No reason provided"):
    """Unbans a user by their Discord User ID."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"{reason} (Unbanned by {ctx.author})")
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Successfully unbanned {user.mention} (`{user.id}`) | Reason: {reason}", color=discord.Color.green()))
        await audit(ctx.guild, f"User unbanned: {user} ({user.id}) | Reason: {reason} | By: {ctx.author}")
    except discord.NotFound:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Could not find a banned user with ID `{user_id}`.", color=discord.Color.red()))
    except discord.HTTPException:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Failed to unban the user.", color=discord.Color.red()))


@bot.command(name="mute")
@commands.guild_only()
async def mute(ctx, member: discord.Member, *, reason="No reason provided"):
    """Timeouts a member for 10 minutes."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    from datetime import timedelta
    try:
        await member.timeout(timedelta(minutes=10), reason=f"{reason} (Muted by {ctx.author})")
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Timed out {member.mention} for 10 minutes.", color=discord.Color.orange()))
        await audit(ctx.guild, f"Member timed out: {member} ({member.id}) | Reason: {reason} | By: {ctx.author}")
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} I lack permissions to timeout that member.", color=discord.Color.red()))


@bot.command(name="unmute")
@commands.guild_only()
async def unmute(ctx, member: discord.Member, *, reason="No reason provided"):
    """Removes timeout from a member."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    try:
        await member.timeout(None, reason=f"{reason} (Unmuted by {ctx.author})")
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Removed timeout from {member.mention}.", color=discord.Color.green()))
        await audit(ctx.guild, f"Member timeout removed: {member} ({member.id}) | Reason: {reason} | By: {ctx.author}")
    except discord.Forbidden:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} I lack permissions to unmute that member.", color=discord.Color.red()))


@bot.command(name="warn")
@commands.guild_only()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    """Issues a formal warning to a member."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    if member.id == ctx.author.id or member.id == ctx.guild.owner_id:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} You cannot warn that user.", color=discord.Color.orange()))
        return

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    if "warnings" not in config:
        config["warnings"] = {}
    if guild_id not in config["warnings"]:
        config["warnings"][guild_id] = {}
    if user_id not in config["warnings"][guild_id]:
        config["warnings"][guild_id][user_id] = []

    config["warnings"][guild_id][user_id].append({
        "reason": reason,
        "moderator": str(ctx.author),
        "timestamp": discord.utils.utcnow().isoformat()
    })
    save_config()

    warn_count = len(config["warnings"][guild_id][user_id])

    embed = discord.Embed(
        title=f"{EMOJIS['warning']} Member Warned",
        description=f"{member.mention} has been warned.\n**Reason:** {reason}\n**Total Warnings:** {warn_count}",
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"Moderator: {ctx.author}")
    await ctx.reply(embed=embed)

    try:
        await member.send(embed=discord.Embed(title=f"{EMOJIS['warning']} You were warned in {ctx.guild.name}", description=f"**Reason:** {reason}", color=discord.Color.orange()))
    except discord.HTTPException:
        pass

    await audit(ctx.guild, f"Member warned: {member} ({member.id}) | Reason: {reason} | Total: {warn_count} | By: {ctx.author}")


@bot.command(name="unwarn")
@commands.guild_only()
async def unwarn(ctx, member: discord.Member, index: int = None):
    """Removes a warning from a member."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    if "warnings" not in config or guild_id not in config["warnings"] or user_id not in config["warnings"][guild_id] or not config["warnings"][guild_id][user_id]:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} {member.mention} has no warnings recorded.", color=discord.Color.orange()))
        return

    user_warns = config["warnings"][guild_id][user_id]

    if index is None:
        config["warnings"][guild_id][user_id] = []
        save_config()
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Cleared all warnings for {member.mention}.", color=discord.Color.green()))
        await audit(ctx.guild, f"All warnings cleared for {member} ({member.id}) by {ctx.author}")
    else:
        if 1 <= index <= len(user_warns):
            removed = user_warns.pop(index - 1)
            save_config()
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Removed warning #{index} for {member.mention} (Reason: `{removed['reason']}`).", color=discord.Color.green()))
            await audit(ctx.guild, f"Warning #{index} removed for {member} ({member.id}) by {ctx.author}")
        else:
            await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Invalid warning index number.", color=discord.Color.red()))


@bot.command(name="clear")
@commands.guild_only()
async def clear(ctx, amount: int = 5):
    """Purges messages."""
    if not user_is_staff(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return

    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(embed=discord.Embed(description=f"{EMOJIS['success']} Cleared {amount} messages.", color=discord.Color.green()))
    await msg.delete(delay=3)


# =========================
# UTILITY & INFO COMMANDS
# =========================

@bot.command(name="ping")
@commands.guild_only()
async def ping(ctx):
    """Shows bot latency."""
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Pong! Latency: `{round(bot.latency * 1000)}ms`", color=discord.Color.blue()))


@bot.command(name="serverinfo")
@commands.guild_only()
async def serverinfo(ctx):
    """Shows server info."""
    g = ctx.guild
    embed = discord.Embed(title=f"{EMOJIS['gear']} {g.name} Information", color=discord.Color.blurple())
    embed.add_field(name=f"{EMOJIS['user']} Owner", value=g.owner, inline=True)
    embed.add_field(name=f"{EMOJIS['ladder']} Members", value=g.member_count, inline=True)
    embed.add_field(name=f"{EMOJIS['success']} Created On", value=g.created_at.strftime("%Y-%m-%d"), inline=True)
    await ctx.reply(embed=embed)


@bot.command(name="userinfo")
@commands.guild_only()
async def userinfo(ctx, member: discord.Member = None):
    """Shows user info."""
    m = member or ctx.author
    embed = discord.Embed(title=f"{EMOJIS['user']} {m} Info", color=m.color)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="ID", value=m.id, inline=True)
    embed.add_field(name="Joined", value=m.joined_at.strftime("%Y-%m-%d") if m.joined_at else "N/A", inline=True)
    await ctx.reply(embed=embed)


@bot.command(name="avatar")
@commands.guild_only()
async def avatar(ctx, member: discord.Member = None):
    """Shows user avatar."""
    m = member or ctx.author
    embed = discord.Embed(title=f"{EMOJIS['user']} Avatar for {m}", color=discord.Color.blurple())
    embed.set_image(url=m.display_avatar.url)
    await ctx.reply(embed=embed)


# =========================
# FUN & MISC COMMANDS
# =========================

@bot.command(name="coinflip")
async def coinflip(ctx):
    """Flips a coin."""
    result = random.choice(["Heads", "Tails"])
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} The coin landed on: **{result}**", color=discord.Color.gold()))


@bot.command(name="roll")
async def roll(ctx):
    """Rolls a dice (1-6)."""
    result = random.randint(1, 6)
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} You rolled a **{result}**!", color=discord.Color.gold()))


# =========================
# SETUP COMMANDS (RANKS ADD / CLEAR)
# =========================

# =========================
# ECONOMY COMMANDS
# =========================

ECONOMY_EMOJI = EMOJIS["purchase"]
ECONOMY_ITEMS = {
    "laptop": {"price": 800, "description": "A shiny laptop. Sell it later if you need cash."},
    "phone": {"price": 450, "description": "A new phone for your collection."},
    "watch": {"price": 250, "description": "A stylish watch."},
    "trophy": {"price": 1200, "description": "A trophy to show off your wins."},
    "cookie": {"price": 50, "description": "A tasty cookie. Restore your luck (coming soon)."},
}


def economy_account(ctx):
    """Return a persistent account scoped to this server and member."""
    economy = config.setdefault("economy", {})
    guild_accounts = economy.setdefault(str(ctx.guild.id), {})
    account = guild_accounts.setdefault(str(ctx.author.id), {
        "wallet": 0, "bank": 0, "bank_level": 0, "inventory": [], "cooldowns": {}
    })
    account.setdefault("wallet", 0)
    account.setdefault("bank", 0)
    account.setdefault("bank_level", 0)
    account.setdefault("inventory", [])
    account.setdefault("cooldowns", {})
    return account


def economy_member_account(guild, member):
    economy = config.setdefault("economy", {})
    guild_accounts = economy.setdefault(str(guild.id), {})
    return guild_accounts.setdefault(str(member.id), {
        "wallet": 0, "bank": 0, "bank_level": 0, "inventory": [], "cooldowns": {}
    })


def economy_embed(title, description=None, color=None):
    return discord.Embed(
        title=f"{ECONOMY_EMOJI} {title}", description=description,
        color=color or discord.Color.gold()
    )


def economy_bank_limit(account):
    return 10000 + int(account.get("bank_level", 0)) * 5000


def economy_cooldown(account, action, seconds):
    import time
    now = time.time()
    expires = float(account["cooldowns"].get(action, 0)) + seconds
    if now < expires:
        return int(expires - now) + 1
    account["cooldowns"][action] = now
    return 0


@bot.command(name="balance", aliases=["bal", "wallet"])
@commands.guild_only()
async def balance(ctx, member: discord.Member = None):
    """Show your wallet and bank, or another member's balance."""
    member = member or ctx.author
    account = economy_member_account(ctx.guild, member)
    embed = economy_embed(f"{member.display_name}'s Balance", color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=f"{ECONOMY_EMOJI} Wallet", value=f"**{account['wallet']:,}** coins", inline=True)
    embed.add_field(name="🏦 Bank", value=f"**{account['bank']:,} / {economy_bank_limit(account):,}** coins", inline=True)
    embed.add_field(name="💰 Total", value=f"**{account['wallet'] + account['bank']:,}** coins", inline=False)
    save_config()
    await ctx.reply(embed=embed)


@bot.command(name="daily")
@commands.guild_only()
async def daily(ctx):
    account = economy_account(ctx)
    remaining = economy_cooldown(account, "daily", 86400)
    if remaining:
        await ctx.reply(embed=economy_embed("Daily Reward", f"{EMOJIS['warning']} Come back in **{remaining // 3600}h {(remaining % 3600) // 60}m**.", discord.Color.orange()))
        return
    amount = random.randint(250, 500)
    account["wallet"] += amount
    save_config()
    await ctx.reply(embed=economy_embed("Daily Reward Collected", f"{EMOJIS['success']} You received **{amount:,} coins**. Your wallet now has **{account['wallet']:,}** coins!", discord.Color.green()))


@bot.command(name="work", aliases=["job"])
@commands.guild_only()
async def work(ctx):
    account = economy_account(ctx)
    remaining = economy_cooldown(account, "work", 3600)
    if remaining:
        await ctx.reply(embed=economy_embed("Work", f"{EMOJIS['warning']} Your next shift starts in **{remaining // 60}m {remaining % 60}s**.", discord.Color.orange()))
        return
    jobs = ["delivered packages", "fixed a computer", "served drinks", "walked some dogs", "helped at the market"]
    amount = random.randint(80, 220)
    account["wallet"] += amount
    save_config()
    await ctx.reply(embed=economy_embed("Shift Complete", f"You {random.choice(jobs)} and earned **{amount:,} coins**! {EMOJIS['success']}", discord.Color.green()))


@bot.command(name="beg")
@commands.guild_only()
async def beg(ctx):
    account = economy_account(ctx)
    remaining = economy_cooldown(account, "beg", 300)
    if remaining:
        await ctx.reply(embed=economy_embed("Beg", f"{EMOJIS['warning']} Try again in **{remaining}s**.", discord.Color.orange()))
        return
    amount = random.randint(0, 100)
    account["wallet"] += amount
    save_config()
    if amount:
        message = f"A kind passerby gave you **{amount} coins**."
    else:
        message = "Nobody had spare change this time. Better luck next time!"
    await ctx.reply(embed=economy_embed("A Little Help", message, discord.Color.green()))


@bot.command(name="crime")
@commands.guild_only()
async def crime(ctx):
    account = economy_account(ctx)
    remaining = economy_cooldown(account, "crime", 1800)
    if remaining:
        await ctx.reply(embed=economy_embed("Crime", f"{EMOJIS['warning']} Lay low for **{remaining // 60}m {remaining % 60}s**.", discord.Color.orange()))
        return
    if random.random() < 0.55:
        amount = random.randint(100, 350)
        account["wallet"] += amount
        result = f"You got away with **{amount:,} coins**! {EMOJIS['success']}"
        color = discord.Color.green()
    else:
        amount = min(account["wallet"], random.randint(50, 200))
        account["wallet"] -= amount
        result = f"You got caught and paid a **{amount:,}-coin fine**. {EMOJIS['warning']}"
        color = discord.Color.red()
    save_config()
    await ctx.reply(embed=economy_embed("Risky Business", result, color))


@bot.command(name="deposit", aliases=["dep"])
@commands.guild_only()
async def deposit(ctx, amount: str):
    account = economy_account(ctx)
    amount = account["wallet"] if amount.lower() == "all" else int(amount)
    if amount <= 0 or amount > account["wallet"]:
        await ctx.reply(embed=economy_embed("Deposit", f"{EMOJIS['error']} Enter an amount up to your wallet balance (**{account['wallet']:,}**).", discord.Color.red()))
        return
    available = economy_bank_limit(account) - account["bank"]
    if amount > available:
        await ctx.reply(embed=economy_embed("Bank Full", f"Your bank has room for **{available:,}** more coins. Upgrade it with `>bankupgrade`.", discord.Color.orange()))
        return
    account["wallet"] -= amount
    account["bank"] += amount
    save_config()
    await ctx.reply(embed=economy_embed("Deposit Complete", f"{EMOJIS['success']} Deposited **{amount:,} coins** into your bank."))


@bot.command(name="withdraw", aliases=["with"])
@commands.guild_only()
async def withdraw(ctx, amount: str):
    account = economy_account(ctx)
    amount = account["bank"] if amount.lower() == "all" else int(amount)
    if amount <= 0 or amount > account["bank"]:
        await ctx.reply(embed=economy_embed("Withdraw", f"{EMOJIS['error']} Enter an amount up to your bank balance (**{account['bank']:,}**).", discord.Color.red()))
        return
    account["bank"] -= amount
    account["wallet"] += amount
    save_config()
    await ctx.reply(embed=economy_embed("Withdrawal Complete", f"{EMOJIS['success']} Withdrew **{amount:,} coins** to your wallet."))


@bot.command(name="pay", aliases=["give", "transfer"])
@commands.guild_only()
async def pay(ctx, member: discord.Member, amount: int):
    account = economy_account(ctx)
    if member.bot or member == ctx.author or amount <= 0 or account["wallet"] < amount:
        await ctx.reply(embed=economy_embed("Transfer", f"{EMOJIS['error']} Choose another member and a positive amount you can afford.", discord.Color.red()))
        return
    recipient = economy_member_account(ctx.guild, member)
    account["wallet"] -= amount
    recipient["wallet"] += amount
    save_config()
    await ctx.reply(embed=economy_embed("Transfer Complete", f"{EMOJIS['success']} Sent **{amount:,} coins** to {member.mention}."))


@bot.command(name="leaderboard", aliases=["lb", "rich"])
@commands.guild_only()
async def leaderboard(ctx):
    accounts = config.setdefault("economy", {}).get(str(ctx.guild.id), {})
    ranked = sorted(accounts.items(), key=lambda pair: int(pair[1].get("wallet", 0)) + int(pair[1].get("bank", 0)), reverse=True)[:10]
    if not ranked:
        await ctx.reply(embed=economy_embed("Richest Members", "No economy accounts yet. Try `>daily` to get started."))
        return
    rows = []
    for rank, (user_id, account) in enumerate(ranked, 1):
        total = int(account.get("wallet", 0)) + int(account.get("bank", 0))
        rows.append(f"**{rank}.** <@{user_id}> — **{total:,}** coins")
    await ctx.reply(embed=economy_embed("Server Rich List", "\n".join(rows)))


@bot.command(name="shop", aliases=["store"])
@commands.guild_only()
async def shop(ctx):
    embed = economy_embed("Shop", "Buy items with `>buy <item>`. Sell items with `>sell <item>`.\n")
    for item, details in ECONOMY_ITEMS.items():
        embed.add_field(name=f"{item.title()} — {details['price']:,} coins", value=details["description"], inline=False)
    await ctx.reply(embed=embed)


@bot.command(name="buy")
@commands.guild_only()
async def buy(ctx, item: str):
    item = item.lower()
    if item not in ECONOMY_ITEMS:
        await ctx.reply(embed=economy_embed("Shop", f"{EMOJIS['error']} That item is unavailable. Use `>shop` to see the catalog.", discord.Color.red()))
        return
    account = economy_account(ctx)
    price = ECONOMY_ITEMS[item]["price"]
    if account["wallet"] < price:
        await ctx.reply(embed=economy_embed("Not Enough Coins", f"You need **{price:,} coins**; your wallet has **{account['wallet']:,}**.", discord.Color.red()))
        return
    account["wallet"] -= price
    account["inventory"].append(item)
    save_config()
    await ctx.reply(embed=economy_embed("Purchase Complete", f"{EMOJIS['success']} You bought a **{item}** for **{price:,} coins**."))


@bot.command(name="inventory", aliases=["inv", "bag"])
@commands.guild_only()
async def inventory(ctx, member: discord.Member = None):
    member = member or ctx.author
    account = economy_member_account(ctx.guild, member)
    items = account.get("inventory", [])
    counts = {item: items.count(item) for item in set(items)}
    description = "\n".join(f"{ECONOMY_EMOJI} **{item.title()}** × {count}" for item, count in sorted(counts.items())) or "Your inventory is empty. Visit `>shop`!"
    await ctx.reply(embed=economy_embed(f"{member.display_name}'s Inventory", description))


@bot.command(name="sell")
@commands.guild_only()
async def sell(ctx, item: str):
    item = item.lower()
    account = economy_account(ctx)
    if item not in ECONOMY_ITEMS or item not in account["inventory"]:
        await ctx.reply(embed=economy_embed("Sell Item", f"{EMOJIS['error']} You don't own that item. Check `>inventory`.", discord.Color.red()))
        return
    account["inventory"].remove(item)
    amount = ECONOMY_ITEMS[item]["price"] // 2
    account["wallet"] += amount
    save_config()
    await ctx.reply(embed=economy_embed("Item Sold", f"{EMOJIS['success']} Sold **{item}** for **{amount:,} coins**."))


@bot.command(name="bankupgrade", aliases=["upgradebank"])
@commands.guild_only()
async def bankupgrade(ctx):
    account = economy_account(ctx)
    cost = 2000 + int(account["bank_level"]) * 2000
    if account["wallet"] < cost:
        await ctx.reply(embed=economy_embed("Bank Upgrade", f"Upgrade costs **{cost:,} coins**. Your wallet has **{account['wallet']:,}**.", discord.Color.red()))
        return
    account["wallet"] -= cost
    account["bank_level"] += 1
    save_config()
    await ctx.reply(embed=economy_embed("Bank Upgraded", f"{EMOJIS['success']} Capacity increased to **{economy_bank_limit(account):,} coins**!"))


@bot.command(name="rob")
@commands.guild_only()
async def rob(ctx, member: discord.Member):
    account = economy_account(ctx)
    if OWNER_ID and member.id == OWNER_ID:
        await ctx.reply(embed=economy_embed("Rob", f"{EMOJIS['shield']} The bot owner is protected from robbery.", discord.Color.orange()))
        return
    if member.bot or member == ctx.author:
        await ctx.reply(embed=economy_embed("Rob", f"{EMOJIS['error']} Pick another server member.", discord.Color.red()))
        return
    remaining = economy_cooldown(account, "rob", 3600)
    if remaining:
        await ctx.reply(embed=economy_embed("Rob", f"{EMOJIS['warning']} Wait **{remaining // 60}m {remaining % 60}s** before trying again.", discord.Color.orange()))
        return
    victim = economy_member_account(ctx.guild, member)
    if victim["wallet"] < 100:
        await ctx.reply(embed=economy_embed("Rob", "That member doesn't have enough in their wallet."))
        return
    if random.random() < 0.45:
        amount = min(victim["wallet"], random.randint(50, 250))
        victim["wallet"] -= amount
        account["wallet"] += amount
        message, color = f"You stole **{amount:,} coins** from {member.mention}!", discord.Color.green()
    else:
        fine = min(account["wallet"], random.randint(50, 200))
        account["wallet"] -= fine
        victim["wallet"] += fine
        message, color = f"You were caught! You paid {member.mention} a **{fine:,}-coin fine**.", discord.Color.red()
    save_config()
    await ctx.reply(embed=economy_embed("Robbery Result", message, color))


@bot.command(name="slots")
@commands.guild_only()
async def slots(ctx, bet: int):
    account = economy_account(ctx)
    if bet <= 0 or bet > 5000 or bet > account["wallet"]:
        await ctx.reply(embed=economy_embed("Slots", f"{EMOJIS['error']} Bet between 1 and 5,000 coins, up to your wallet balance.", discord.Color.red()))
        return
    symbols = ["🍒", "🍋", "🔔", "💎", "⭐"]
    result = [random.choice(symbols) for _ in range(3)]
    account["wallet"] -= bet
    if result[0] == result[1] == result[2]:
        winnings = bet * 5
        account["wallet"] += winnings
        message = f"{' | '.join(result)}\nJackpot! You won **{winnings:,} coins**."
        color = discord.Color.green()
    elif len(set(result)) == 2:
        winnings = bet * 2
        account["wallet"] += winnings
        message = f"{' | '.join(result)}\nTwo match! You won **{winnings:,} coins**."
        color = discord.Color.green()
    else:
        message = f"{' | '.join(result)}\nNo match this time. You lost **{bet:,} coins**."
        color = discord.Color.red()
    save_config()
    await ctx.reply(embed=economy_embed("Slot Machine", message, color))


@bot.command(name="betflip")
@commands.guild_only()
async def betflip(ctx, choice: str, bet: int):
    account = economy_account(ctx)
    choice = choice.lower()
    if choice not in ("heads", "tails") or bet <= 0 or bet > account["wallet"]:
        await ctx.reply(embed=economy_embed("Coinflip Bet", f"{EMOJIS['error']} Use `>betflip <heads/tails> <amount>` with a valid wallet bet.", discord.Color.red()))
        return
    result = random.choice(["heads", "tails"])
    if choice == result:
        account["wallet"] += bet
        message, color = f"It was **{result}**! You won **{bet:,} coins**.", discord.Color.green()
    else:
        account["wallet"] -= bet
        message, color = f"It was **{result}**. You lost **{bet:,} coins**.", discord.Color.red()
    save_config()
    await ctx.reply(embed=economy_embed("Coinflip Bet", message, color))


@bot.command(name="economy")
@commands.guild_only()
async def economy_help(ctx):
    embed = economy_embed("Economy Commands", "`>balance [@member]` · `>daily` · `>work` · `>beg` · `>crime`\n`>deposit <amount/all>` · `>withdraw <amount/all>` · `>pay @member <amount>`\n`>leaderboard` · `>shop` · `>buy <item>` · `>sell <item>` · `>inventory [@member]`\n`>bankupgrade` · `>rob @member` · `>slots <bet>` · `>betflip <heads/tails> <bet>\n\n" + f"All balances are saved per server. Currency: {ECONOMY_EMOJI}")
    description = (
        "`>balance [@member]` · `>daily` · `>work` · `>beg` · `>crime`\n"
        "`>deposit <amount/all>` · `>withdraw <amount/all>` · `>pay @member <amount>`\n"
        "`>leaderboard` · `>shop` · `>buy <item>` · `>sell <item>` · `>inventory [@member]`\n"
        "`>bankupgrade` · `>rob @member` · `>slots <bet>` · `>betflip <heads/tails> <bet>`\n\n"
        f"All balances are saved per server. Currency: {ECONOMY_EMOJI}"
    )
    if OWNER_ID and ctx.author.id == OWNER_ID:
        description += (
            "\n\n**Bot owner (per-server):** `>addmoney @member <amount> [wallet/bank]` · "
            "`>removemoney @member <amount> [wallet/bank]` · `>setmoney @member <amount> [wallet/bank]` · "
            "`>resetmoney @member` · `>addbank @member <amount>` · `>setbank @member <amount>` · `>reseteco @member`"
        )
    embed = economy_embed("Economy Commands", description)
    await ctx.reply(embed=embed)


def is_bot_owner(ctx):
    return bool(OWNER_ID) and ctx.author.id == OWNER_ID


async def owner_economy_reply(ctx, title, description, color=discord.Color.green()):
    await ctx.reply(embed=economy_embed(title, description, color))


@bot.command(name="addmoney", aliases=["addcash"])
@commands.guild_only()
async def addmoney(ctx, member: discord.Member, amount: int, pocket: str = "wallet"):
    """Bot owner: add coins to a member's wallet or bank in this server."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    pocket = pocket.lower()
    account = economy_member_account(ctx.guild, member)
    if amount <= 0 or pocket not in ("wallet", "bank"):
        await owner_economy_reply(ctx, "Usage", "Use `>addmoney @member <positive amount> [wallet/bank]`.", discord.Color.orange())
        return
    if pocket == "bank" and account["bank"] + amount > economy_bank_limit(account):
        await owner_economy_reply(ctx, "Bank Capacity", f"That exceeds the member's bank limit of **{economy_bank_limit(account):,}**.", discord.Color.orange())
        return
    account[pocket] += amount
    save_config()
    await owner_economy_reply(ctx, "Money Added", f"{EMOJIS['success']} Added **{amount:,} coins** to {member.mention}'s {pocket}.")


@bot.command(name="removemoney", aliases=["takemoney", "removecash"])
@commands.guild_only()
async def removemoney(ctx, member: discord.Member, amount: int, pocket: str = "wallet"):
    """Bot owner: remove coins from a member's wallet or bank in this server."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    pocket = pocket.lower()
    account = economy_member_account(ctx.guild, member)
    if amount <= 0 or pocket not in ("wallet", "bank"):
        await owner_economy_reply(ctx, "Usage", "Use `>removemoney @member <positive amount> [wallet/bank]`.", discord.Color.orange())
        return
    removed = min(amount, account[pocket])
    account[pocket] -= removed
    save_config()
    await owner_economy_reply(ctx, "Money Removed", f"Removed **{removed:,} coins** from {member.mention}'s {pocket}.")


@bot.command(name="setmoney", aliases=["setcash"])
@commands.guild_only()
async def setmoney(ctx, member: discord.Member, amount: int, pocket: str = "wallet"):
    """Bot owner: set a member's wallet or bank balance in this server."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    pocket = pocket.lower()
    account = economy_member_account(ctx.guild, member)
    if amount < 0 or pocket not in ("wallet", "bank"):
        await owner_economy_reply(ctx, "Usage", "Use `>setmoney @member <amount of 0 or more> [wallet/bank]`.", discord.Color.orange())
        return
    if pocket == "bank" and amount > economy_bank_limit(account):
        await owner_economy_reply(ctx, "Bank Capacity", f"The bank limit is **{economy_bank_limit(account):,}**. Upgrade the account or set its wallet instead.", discord.Color.orange())
        return
    account[pocket] = amount
    save_config()
    await owner_economy_reply(ctx, "Balance Set", f"Set {member.mention}'s {pocket} to **{amount:,} coins**.")


@bot.command(name="addbank")
@commands.guild_only()
async def addbank(ctx, member: discord.Member, amount: int):
    """Bot owner: add coins directly to a member's bank, respecting its capacity."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    account = economy_member_account(ctx.guild, member)
    if amount <= 0 or account["bank"] + amount > economy_bank_limit(account):
        await owner_economy_reply(ctx, "Bank Capacity", f"Enter a positive amount that fits the remaining **{economy_bank_limit(account) - account['bank']:,}** bank capacity.", discord.Color.orange())
        return
    account["bank"] += amount
    save_config()
    await owner_economy_reply(ctx, "Bank Funds Added", f"Added **{amount:,} coins** to {member.mention}'s bank.")


@bot.command(name="setbank")
@commands.guild_only()
async def setbank(ctx, member: discord.Member, amount: int):
    """Bot owner: set a member's bank balance without exceeding its capacity."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    account = economy_member_account(ctx.guild, member)
    if amount < 0 or amount > economy_bank_limit(account):
        await owner_economy_reply(ctx, "Bank Capacity", f"Choose an amount from 0 to **{economy_bank_limit(account):,}**.", discord.Color.orange())
        return
    account["bank"] = amount
    save_config()
    await owner_economy_reply(ctx, "Bank Set", f"Set {member.mention}'s bank to **{amount:,} coins**.")


@bot.command(name="resetmoney", aliases=["clearmoney"])
@commands.guild_only()
async def resetmoney(ctx, member: discord.Member):
    """Bot owner: clear a member's wallet and bank balances in this server."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    account = economy_member_account(ctx.guild, member)
    account["wallet"] = 0
    account["bank"] = 0
    save_config()
    await owner_economy_reply(ctx, "Balances Cleared", f"Cleared {member.mention}'s wallet and bank. Inventory and cooldowns were kept.", discord.Color.orange())


@bot.command(name="reseteco", aliases=["resetaccount"])
@commands.guild_only()
async def reseteco(ctx, member: discord.Member):
    """Bot owner: reset a member's entire economy account in this server."""
    if not is_bot_owner(ctx):
        await owner_economy_reply(ctx, "Owner Only", f"{EMOJIS['error']} This command is only for the configured bot owner.", discord.Color.red())
        return
    config.setdefault("economy", {}).setdefault(str(ctx.guild.id), {})[str(member.id)] = {
        "wallet": 0, "bank": 0, "bank_level": 0, "inventory": [], "cooldowns": {}
    }
    save_config()
    await owner_economy_reply(ctx, "Account Reset", f"Reset {member.mention}'s complete economy account in this server.", discord.Color.orange())

@bot.group(invoke_without_command=True)
@commands.guild_only()
async def ranks(ctx):
    """Shows current rank ladder configuration."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id), [])
    ladder_str = " -> ".join([f"<@&{r_id}>" for r_id in ladder]) if ladder else "Not configured. Use `>ranks add @role`"
    
    embed = discord.Embed(
        title=f"{EMOJIS['ladder']} Staff Rank Ladder",
        description=f"**Current Order (Lowest to Highest):**\n{ladder_str}",
        color=discord.Color.blurple()
    )
    await ctx.reply(embed=embed)


@ranks.command(name="add")
@commands.guild_only()
async def ranks_add(ctx, role: discord.Role):
    """Adds a role to the rank ladder sequence (lowest to highest)."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    if role.is_default() or role.managed:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} You cannot add that role to the ladder.", color=discord.Color.orange()))
        return

    guild_id = str(ctx.guild.id)
    if "rank_ladders" not in config:
        config["rank_ladders"] = {}
    if guild_id not in config["rank_ladders"]:
        config["rank_ladders"][guild_id] = []

    if role.id in config["rank_ladders"][guild_id]:
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['warning']} That role is already in the rank ladder.", color=discord.Color.orange()))
        return

    config["rank_ladders"][guild_id].append(role.id)
    save_config()

    ladder = config["rank_ladders"][guild_id]
    ladder_str = " -> ".join([f"<@&{r_id}>" for r_id in ladder])

    embed = discord.Embed(
        title=f"{EMOJIS['success']} Rank Added to Ladder",
        description=f"Added {role.mention} successfully!\n\n**Current Ladder:**\n{ladder_str}",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)


@ranks.command(name="clear")
@commands.guild_only()
async def ranks_clear(ctx):
    """Clears the entire rank ladder configuration."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    guild_id = str(ctx.guild.id)
    if "rank_ladders" in config and guild_id in config["rank_ladders"]:
        config["rank_ladders"][guild_id] = []
        save_config()

    embed = discord.Embed(
        title=f"{EMOJIS['success']} Rank Ladder Cleared",
        description="The rank ladder sequence has been reset.",
        color=discord.Color.red()
    )
    await ctx.reply(embed=embed)


@bot.command(name="setstaffsupervisor")
@commands.guild_only()
async def setstaffsupervisor(ctx, assigned_role: discord.Role):
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    config["supervisor_roles"][str(ctx.guild.id)] = assigned_role.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Supervisor role set to {assigned_role.mention}.", color=discord.Color.green()))


@bot.command(name="setpromodemo")
@commands.guild_only()
async def setpromodemo(ctx, channel: discord.TextChannel):
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    config["promodemo_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Promo channel set to {channel.mention}.", color=discord.Color.green()))


@bot.command(name="setaudit")
@commands.guild_only()
async def setaudit(ctx, channel: discord.TextChannel):
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    config["audit_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Audit channel set to {channel.mention}.", color=discord.Color.green()))


@bot.command(name="setlogchan")
@commands.guild_only()
async def setlogchan(ctx, channel: discord.TextChannel):
    """Sets the channel for server event embed logs."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return
    config.setdefault("log_channels", {})[str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Server event logs will be sent to {channel.mention}.", color=discord.Color.green()))


@bot.command(name="setecochan")
@commands.guild_only()
async def setecochan(ctx, channel: discord.TextChannel):
    """Restricts economy commands to the selected channel."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return
    config.setdefault("economy_channels", {})[str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Economy commands can now only be used in {channel.mention}.", color=discord.Color.green()))


@bot.command(name="staffsettings")
@commands.guild_only()
async def staffsettings(ctx):
    """Displays current server staff configurations and rank ladder."""
    if not user_is_supervisor(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to view staff settings.", color=discord.Color.red()))
        return

    supervisor_id = guild_setting("supervisor_roles", ctx.guild.id)
    staff_role_id = guild_setting("staff_roles", ctx.guild.id)
    promo_id = guild_setting("promodemo_channels", ctx.guild.id)
    audit_id = guild_setting("audit_channels", ctx.guild.id)
    ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id), [])

    supervisor = ctx.guild.get_role(int(supervisor_id)) if supervisor_id else None
    staff_role = ctx.guild.get_role(int(staff_role_id)) if staff_role_id else None
    promo_channel = ctx.guild.get_channel(int(promo_id)) if promo_id else None
    audit_channel = ctx.guild.get_channel(int(audit_id)) if audit_id else None
    
    ladder_str = " -> ".join([f"<@&{r_id}>" for r_id in ladder]) if ladder else "Not configured (`>ranks add @role`)"

    embed = discord.Embed(
        title=f"{EMOJIS['gear']} Faisal Mod • Server Settings",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name=f"{EMOJIS['shield']} Supervisor Role",
        value=supervisor.mention if supervisor else "Not configured (`>setstaffsupervisor @role`)",
        inline=False
    )
    embed.add_field(
        name=f"{EMOJIS['shield']} Ticket Staff Role",
        value=staff_role.mention if staff_role else "Not configured (`>setstaffrole @role`)",
        inline=False
    )
    embed.add_field(
        name=f"{EMOJIS['announcement']} Announcement Channel",
        value=promo_channel.mention if promo_channel else "Not configured (`>setpromodemo #channel`)",
        inline=False
    )
    embed.add_field(
        name=f"{EMOJIS['audit']} Audit Log Channel",
        value=audit_channel.mention if audit_channel else "Not configured (`>setaudit #channel`)",
        inline=False
    )
    embed.add_field(
        name=f"{EMOJIS['ladder']} Rank Ladder Sequence",
        value=ladder_str,
        inline=False
    )
    embed.add_field(
        name=f"{EMOJIS['warning']} Staff Daily Quota",
        value="Max **3 Kicks / 3 Bans per 24 hours** for Staff Members",
        inline=False
    )

    embed.set_footer(text=f"{ctx.guild.name} • Configuration Dashboard", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    await ctx.reply(embed=embed)


# =========================
# HELP COMMAND
# =========================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(title=f"{EMOJIS['gear']} Faisal Mod • Command Center", description="Here are all available command modules:", color=discord.Color.blurple())
    embed.add_field(name=f"{EMOJIS['shield']} Staff & Management", value="`>promo`, `>demo`, `>super`, `>superintro`, `>staffintro`, `>staff`, `>role`, `>train`, `>trainings`, `>steal`", inline=False)
    embed.add_field(name=f"{EMOJIS['warning']} Moderation", value="`>kick`, `>ban`, `>unban`, `>mute`, `>unmute`, `>warn`, `>unwarn`, `>clear`", inline=False)
    embed.add_field(name=f"{EMOJIS['ticket']} Support & Tickets", value="`>sendticket [#channel]`, `>setstaffrole @role`, `>setcategory <support/purchase/partnership> #category`", inline=False)
    embed.add_field(name=f"{EMOJIS['user']} Utility & Info", value="`>ping`, `>serverinfo`, `>userinfo`, `>avatar`", inline=False)
    embed.add_field(name=f"{EMOJIS['success']} Fun & Games", value="`>coinflip`, `>roll`, `>slots <bet>`, `>betflip <heads/tails> <bet>`", inline=False)
    embed.add_field(name=f"{EMOJIS['purchase']} Economy", value="`>economy` for the full list: balance, daily, work, beg, crime, deposit, withdraw, pay, leaderboard, shop, buy, sell, inventory, bankupgrade, rob, slots, betflip", inline=False)
    embed.add_field(name=f"{EMOJIS['gear']} Setup", value="`>ranks add @role`, `>ranks clear`, `>setstaffsupervisor`, `>setpromodemo`, `>setaudit`, `>staffsettings`", inline=False)
    embed.add_field(name=f"{EMOJIS['gear']} Setup", value="`>ranks add @role`, `>ranks clear`, `>setstaffsupervisor`, `>setpromodemo`, `>setaudit`, `>setlogchan #channel`, `>setecochan #channel`, `>staffsettings`", inline=False)
    await ctx.reply(embed=embed, mention_author=False)


# =========================
# EVENTS & STARTUP
# =========================

@bot.event
async def on_ready():
    bot.add_view(TicketDropdownView())
    bot.add_view(TicketPanelActionsView())
    logging.info("Faisal Mod logged in as %s", bot.user)


@bot.event
async def on_message(message):
    if message.guild and message.author.id != (bot.user.id if bot.user else None):
        text_content = message.content or "[No text content]"
        await log_server_event(
            message.guild,
            "Message Sent",
            f"**Author:** {message.author.mention} (`{message.author.id}`)\n"
            f"**Channel:** {message.channel.mention}\n**Content:**\n{text_content[:3000]}",
            discord.Color.blurple()
        )
    await bot.process_commands(message)


@bot.event
async def on_message_edit(before, after):
    if after.guild and after.author.id != (bot.user.id if bot.user else None) and before.content != after.content:
        await log_server_event(
            after.guild,
            "Message Edited",
            f"**Author:** {after.author.mention} (`{after.author.id}`)\n"
            f"**Channel:** {after.channel.mention}\n**Before:**\n{(before.content or '[No text content]')[:1300]}\n"
            f"**After:**\n{(after.content or '[No text content]')[:1300]}\n[Jump to message]({after.jump_url})",
            discord.Color.orange()
        )


@bot.event
async def on_message_delete(message):
    if message.guild and message.author.id != (bot.user.id if bot.user else None):
        await log_server_event(
            message.guild,
            "Message Deleted",
            f"**Author:** {message.author.mention} (`{message.author.id}`)\n"
            f"**Channel:** {message.channel.mention}\n**Content:**\n{(message.content or '[No text content]')[:3000]}",
            discord.Color.red()
        )


@bot.event
async def on_raw_message_delete(payload):
    if payload.cached_message is None and payload.guild_id:
        guild = bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id) if guild else None
        await log_server_event(
            guild,
            "Message Deleted (Not Cached)",
            f"A message was deleted in {channel.mention if channel else f'<#{payload.channel_id}>'}.\n"
            f"**Message ID:** `{payload.message_id}`\nMessage content was unavailable because it was not cached.",
            discord.Color.red()
        )


@bot.event
async def on_member_join(member):
    await log_server_event(member.guild, "Member Joined", f"{member.mention} (`{member.id}`) joined the server.", discord.Color.green())


@bot.event
async def on_member_remove(member):
    await log_server_event(member.guild, "Member Left", f"**Member:** {member} (`{member.id}`)", discord.Color.orange())


@bot.event
async def on_member_update(before, after):
    changes = []
    if before.nick != after.nick:
        changes.append(f"**Nickname:** `{before.nick or before.name}` → `{after.nick or after.name}`")
    old_roles = {role.id: role for role in before.roles}
    new_roles = {role.id: role for role in after.roles}
    added = [role.mention for role_id, role in new_roles.items() if role_id not in old_roles]
    removed = [role.mention for role_id, role in old_roles.items() if role_id not in new_roles]
    if added:
        changes.append("**Roles added:** " + ", ".join(added))
    if removed:
        changes.append("**Roles removed:** " + ", ".join(removed))
    if changes:
        await log_server_event(after.guild, "Member Updated", f"**Member:** {after.mention} (`{after.id}`)\n" + "\n".join(changes), discord.Color.orange())


@bot.event
async def on_member_ban(guild, user):
    await log_server_event(guild, "Member Banned", f"**User:** {user} (`{user.id}`)", discord.Color.red())


@bot.event
async def on_member_unban(guild, user):
    await log_server_event(guild, "Member Unbanned", f"**User:** {user} (`{user.id}`)", discord.Color.green())


@bot.event
async def on_guild_channel_create(channel):
    mention = channel.mention if hasattr(channel, "mention") else channel.name
    await log_server_event(channel.guild, "Channel Created", f"**Channel:** {mention}\n**Type:** {type(channel).__name__}", discord.Color.green())


@bot.event
async def on_guild_channel_delete(channel):
    await log_server_event(channel.guild, "Channel Deleted", f"**Channel:** #{channel.name} (`{channel.id}`)\n**Type:** {type(channel).__name__}", discord.Color.red())


@bot.event
async def on_guild_channel_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if hasattr(before, "topic") and before.topic != after.topic:
        changes.append(f"**Topic:** `{before.topic or 'None'}` → `{after.topic or 'None'}`")
    if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
        changes.append(f"**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
    if before.category_id != after.category_id:
        changes.append(f"**Category:** `{before.category}` → `{after.category}`")
    if changes:
        mention = after.mention if hasattr(after, "mention") else after.name
        await log_server_event(after.guild, "Channel Updated", f"**Channel:** {mention}\n" + "\n".join(changes), discord.Color.orange())


@bot.event
async def on_guild_role_create(role):
    await log_server_event(role.guild, "Role Created", f"**Role:** {role.mention} (`{role.id}`)", discord.Color.green())


@bot.event
async def on_guild_role_delete(role):
    await log_server_event(role.guild, "Role Deleted", f"**Role:** {role.name} (`{role.id}`)", discord.Color.red())


@bot.event
async def on_guild_role_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if before.permissions != after.permissions:
        changes.append("**Permissions:** changed")
    if before.color != after.color:
        changes.append(f"**Color:** `{before.color}` → `{after.color}`")
    if before.hoist != after.hoist or before.mentionable != after.mentionable:
        changes.append(f"**Display settings:** hoist `{before.hoist}` → `{after.hoist}`, mentionable `{before.mentionable}` → `{after.mentionable}`")
    if changes:
        await log_server_event(after.guild, "Role Updated", f"**Role:** {after.mention} (`{after.id}`)\n" + "\n".join(changes), discord.Color.orange())


@bot.event
async def on_voice_state_update(member, before, after):
    old_channel = before.channel.name if before.channel else "Not in voice"
    new_channel = after.channel.name if after.channel else "Not in voice"
    if before.channel == after.channel and before.self_mute == after.self_mute and before.mute == after.mute and before.self_deaf == after.self_deaf and before.deaf == after.deaf and before.self_stream == after.self_stream and before.self_video == after.self_video:
        return
    await log_server_event(member.guild, "Voice State Updated", f"**Member:** {member.mention}\n**Voice channel:** `{old_channel}` → `{new_channel}`\nMute, deaf, stream, or camera state changed.", discord.Color.blurple())


@bot.event
async def on_guild_emojis_update(guild, before, after):
    old_emojis = {emoji.id: emoji for emoji in before}
    new_emojis = {emoji.id: emoji for emoji in after}
    added = [str(emoji) for emoji_id, emoji in new_emojis.items() if emoji_id not in old_emojis]
    removed = [emoji.name for emoji_id, emoji in old_emojis.items() if emoji_id not in new_emojis]
    changes = []
    if added:
        changes.append("**Added:** " + " ".join(added))
    if removed:
        changes.append("**Removed:** " + ", ".join(removed))
    if changes:
        await log_server_event(guild, "Custom Emojis Updated", "\n".join(changes), discord.Color.orange())


@bot.event
async def on_invite_create(invite):
    channel = invite.channel.mention if invite.channel else "Unknown"
    await log_server_event(invite.guild, "Invite Created", f"**Code:** `{invite.code}`\n**Channel:** {channel}\n**Created by:** {invite.inviter or 'Unknown'}", discord.Color.green())


@bot.event
async def on_invite_delete(invite):
    channel = invite.channel.mention if invite.channel else "Unknown"
    await log_server_event(invite.guild, "Invite Deleted", f"**Code:** `{invite.code}`\n**Channel:** {channel}", discord.Color.orange())


@bot.event
async def on_webhooks_update(channel):
    await log_server_event(channel.guild, "Webhooks Updated", f"Webhook configuration changed in {channel.mention}.", discord.Color.orange())


@bot.event
async def on_raw_reaction_add(payload):
    if payload.guild_id and payload.user_id != (bot.user.id if bot.user else None):
        guild = bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id) if guild else None
        await log_server_event(
            guild,
            "Reaction Added",
            f"**User:** <@{payload.user_id}>\n**Channel:** {channel.mention if channel else f'<#{payload.channel_id}>'}\n"
            f"**Emoji:** {payload.emoji}\n**Message ID:** `{payload.message_id}`",
            discord.Color.green()
        )


@bot.event
async def on_raw_reaction_remove(payload):
    if payload.guild_id and payload.user_id != (bot.user.id if bot.user else None):
        guild = bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id) if guild else None
        await log_server_event(
            guild,
            "Reaction Removed",
            f"**User:** <@{payload.user_id}>\n**Channel:** {channel.mention if channel else f'<#{payload.channel_id}>'}\n"
            f"**Emoji:** {payload.emoji}\n**Message ID:** `{payload.message_id}`",
            discord.Color.orange()
        )


@bot.event
async def on_guild_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"**Server name:** `{before.name}` → `{after.name}`")
    if before.icon != after.icon:
        changes.append("**Server icon:** changed")
    if before.verification_level != after.verification_level:
        changes.append(f"**Verification level:** `{before.verification_level}` → `{after.verification_level}`")
    if before.description != after.description:
        changes.append("**Server description:** changed")
    if changes:
        await log_server_event(after, "Server Settings Updated", "\n".join(changes), discord.Color.orange())


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        if not economy_channel_allowed(ctx):
            channel_id = guild_setting("economy_channels", ctx.guild.id)
            await ctx.reply(embed=economy_embed("Wrong Channel", f"{EMOJIS['warning']} Economy commands are only available in <#{channel_id}>.", discord.Color.orange()))
            return
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return
    
    logging.exception("Command error:", exc_info=error)
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Error: `{str(error)}`", color=discord.Color.red()))


load_config()
bot.run(TOKEN)
