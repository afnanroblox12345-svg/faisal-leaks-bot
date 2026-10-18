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
    "decomp": "<a:decomp:1561328437057032222>",
    "report": "<:report:1561328585954951269>"
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
            discord.SelectOption(label="Report", description="Report a user or issue", emoji=discord.PartialEmoji.from_str(EMOJIS['report'])),
            discord.SelectOption(label="Giveaway Claim", description="Claim your giveaway prize", emoji=discord.PartialEmoji.from_str(EMOJIS['promo'])),
            discord.SelectOption(label="Decomp Use", description="Decomp service requests", emoji=discord.PartialEmoji.from_str(EMOJIS['decomp']))
        ]
        super().__init__(placeholder="Select a ticket category...", min_values=1, max_values=1, options=options, custom_id="ticket_category_select")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        category_name = self.values[0]

        existing_channel = discord.utils.get(guild.text_channels, name=f"ticket-{member.name.lower()}")
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

        cat_id = guild_setting("ticket_categories", guild.id)
        category = guild.get_channel(int(cat_id)) if cat_id else discord.utils.get(guild.categories, name="Support Tickets")
        if not category:
            category = await guild.create_category("Support Tickets")

        channel = await guild.create_text_channel(
            name=f"ticket-{member.name}",
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
    await audit(ctx.guild, f"Staff Training Started: {trainee} ({trainee.id}) by {ctx.author}")


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
            f"{EMOJIS['bullet']} {EMOJIS['support']} **Support** — General questions & assistance\n"
            f"{EMOJIS['bullet']} {EMOJIS['report']} **Report** — Report users or rule breakers\n"
            f"{EMOJIS['bullet']} {EMOJIS['promo']} **Giveaway Claim** — Claim won prizes\n"
            f"{EMOJIS['bullet']} {EMOJIS['decomp']} **Decomp Use** — Decomp service requests"
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
async def setcategory(ctx, category: discord.CategoryChannel):
    """Sets the category where new tickets are created."""
    if not user_is_owner(ctx):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Only the bot owner or server owner can use this command.", color=discord.Color.red()))
        return

    if "ticket_categories" not in config:
        config["ticket_categories"] = {}
    config["ticket_categories"][str(ctx.guild.id)] = category.id
    save_config()

    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['success']} Ticket creation category set to **{category.name}**.", color=discord.Color.green()))


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
    embed.add_field(name=f"{EMOJIS['ticket']} Support & Tickets", value="`>sendticket [#channel]`, `>setstaffrole @role`, `>setcategory #category`", inline=False)
    embed.add_field(name=f"{EMOJIS['user']} Utility & Info", value="`>ping`, `>serverinfo`, `>userinfo`, `>avatar`", inline=False)
    embed.add_field(name=f"{EMOJIS['success']} Fun & Games", value="`>coinflip`, `>roll`", inline=False)
    embed.add_field(name=f"{EMOJIS['gear']} Setup", value="`>ranks add @role`, `>ranks clear`, `>setstaffsupervisor`, `>setpromodemo`, `>setaudit`, `>staffsettings`", inline=False)
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
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} You don't have permission to use this command.", color=discord.Color.red()))
        return
    
    logging.exception("Command error:", exc_info=error)
    await ctx.reply(embed=discord.Embed(description=f"{EMOJIS['error']} Error: `{str(error)}`", color=discord.Color.red()))


load_config()
bot.run(TOKEN)
