import os
import sys
import json
import logging
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands

# =====================================================================
# SLS HELPER — PRODUCTION CONFIGURATION
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

# =====================================================================
# EXTENSIVE BLUE & ANIMATED EMOJI COLLECTION (EMOJI.GG SOURCES)
# =====================================================================

BLUE_EMOJI_SOURCES = {
    # Core Branding
    "blue_star": "https://cdn3.emoji.gg/emojis/3045-blue-star.gif",
    "blue_fire": "https://cdn3.emoji.gg/emojis/31347-bluefire.gif",
    "blue_deer": "https://cdn3.emoji.gg/emojis/6019-blue-deer.png",
    "blue_shield": "https://cdn.discordapp.com/emojis/1561078954519961622.png",
    "blue_gem": "https://cdn.discordapp.com/emojis/1561077598791016591.png",
    # Ticket Categories
    "blue_ticket": "https://cdn.discordapp.com/emojis/1560983848345665637.png",
    "blue_support": "https://cdn.discordapp.com/emojis/1561328482724614238.png",
    "blue_purchase": "https://cdn.discordapp.com/emojis/1561328437057032222.png",
    "blue_partner": "https://cdn.discordapp.com/emojis/1561337139373932593.png",
    # Aesthetic & UI
    "blue_heart": "https://cdn3.emoji.gg/emojis/3820-blue-heart.gif",
    "blue_sparkle": "https://cdn3.emoji.gg/emojis/7452-blue-sparkle.gif",
    "blue_flame": "https://cdn3.emoji.gg/emojis/4946-twitch-logo-animated-blue.gif",
    "blue_sword": "https://cdn.discordapp.com/emojis/1561077871206989845.png",
    "blue_gear": "https://cdn.discordapp.com/emojis/1561077371895943319.png",
    "blue_book": "https://cdn.discordapp.com/emojis/1561077741716111362.png",
    "blue_tick": "https://cdn.discordapp.com/emojis/1561077516905484448.png",
    "blue_warning": "https://cdn.discordapp.com/emojis/1561077438816194632.png",
    "blue_error": "https://cdn.discordapp.com/emojis/1561078063968686081.png",
    "blue_user": "https://cdn.discordapp.com/emojis/1561077921395904653.png",
    "blue_arrow": "https://cdn.discordapp.com/emojis/1561077250638610563.png",
    "blue_welcome": "https://cdn.discordapp.com/emojis/1561077660648738876.png",
    # Economy & Games
    "blue_coin": "https://cdn3.emoji.gg/emojis/3045-blue-star.gif",
    "blue_bank": "https://cdn.discordapp.com/emojis/1561077741716111362.png",
    "blue_dice": "https://cdn3.emoji.gg/emojis/7452-blue-sparkle.gif",
    "blue_trophy": "https://cdn3.emoji.gg/emojis/31347-bluefire.gif"
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
    "inventories": {},
    "daily_cooldowns": {},
    "work_cooldowns": {},
    "beg_cooldowns": {}
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
    if guild:
        e = discord.utils.get(guild.emojis, name=name)
        if e:
            return str(e)
    return "🔹"


def get_emoji_dict(guild):
    return {
        "promo": get_emoji(guild, "blue_gem"),
        "demo": get_emoji(guild, "blue_deer"),
        "shield": get_emoji(guild, "blue_shield"),
        "gear": get_emoji(guild, "blue_gear"),
        "ladder": get_emoji(guild, "blue_star"),
        "announcement": get_emoji(guild, "blue_fire"),
        "audit": get_emoji(guild, "blue_book"),
        "success": get_emoji(guild, "blue_tick"),
        "warning": get_emoji(guild, "blue_warning"),
        "error": get_emoji(guild, "blue_error"),
        "user": get_emoji(guild, "blue_user"),
        "bullet": get_emoji(guild, "blue_arrow"),
        "welcome": get_emoji(guild, "blue_welcome"),
        "ticket": get_emoji(guild, "blue_ticket"),
        "support": get_emoji(guild, "blue_support"),
        "purchase": get_emoji(guild, "blue_purchase"),
        "partner": get_emoji(guild, "blue_partner"),
        "coin": get_emoji(guild, "blue_coin"),
        "bank": get_emoji(guild, "blue_bank"),
        "dice": get_emoji(guild, "blue_dice"),
        "trophy": get_emoji(guild, "blue_trophy")
    }


# =====================================================================
# PERMISSION & HELPER CHECKS
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


def get_user_econ(user_id):
    uid = str(user_id)
    if "economy" not in config:
        config["economy"] = {}
    if uid not in config["economy"]:
        config["economy"][uid] = {"wallet": 100, "bank": 0}
    return config["economy"][uid]


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
# TICKET SYSTEM INTERACTIVE VIEWS
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
# BOT OWNER ADMIN COMMANDS
# =====================================================================

@bot.command(name="eval")
async def eval_cmd(ctx, *, code: str):
    """Executes arbitrary python code (Bot Owner Only)."""
    if ctx.author.id != OWNER_ID:
        return
    try:
        result = eval(code)
        if asyncio.iscoroutine(result):
            result = await result
        await ctx.reply(f"```python\n{result}\n```")
    except Exception as e:
        await ctx.reply(f"```python\nError: {e}\n```")


@bot.command(name="shutdown")
async def shutdown(ctx):
    """Shuts down the bot process safely (Bot Owner Only)."""
    if ctx.author.id != OWNER_ID:
        return
    await ctx.reply("🟦 Shutting down SLS Helper...")
    await bot.close()


@bot.command(name="restart")
async def restart(ctx):
    """Restarts the bot process (Bot Owner Only)."""
    if ctx.author.id != OWNER_ID:
        return
    await ctx.reply("🟦 Restarting SLS Helper process...")
    os.execv(sys.executable, ['python'] + sys.argv)


@bot.command(name="botservers")
async def botservers(ctx):
    """Lists all servers the bot is currently in (Bot Owner Only)."""
    if ctx.author.id != OWNER_ID:
        return
    guilds_str = "\n".join([f"🔹 **{g.name}** (`{g.id}`) — {g.member_count} members" for g in bot.guilds])
    embed = discord.Embed(title="SLS Helper • Guild List", description=guilds_str, color=discord.Color.blue())
    await ctx.reply(embed=embed)


@bot.command(name="addcoins")
async def addcoins(ctx, member: discord.Member, amount: int):
    """Gives economy coins to a member (Bot Owner Only)."""
    if ctx.author.id != OWNER_ID:
        return
    econ = get_user_econ(member.id)
    econ["wallet"] += amount
    save_config()
    await ctx.reply(f"🟦 Added **{amount}** coins to {member.mention}'s wallet!")


@bot.command(name="removecoins")
async def removecoins(ctx, member: discord.Member, amount: int):
    """Removes economy coins from a member (Bot Owner Only)."""
    if ctx.author.id != OWNER_ID:
        return
    econ = get_user_econ(member.id)
    econ["wallet"] = max(0, econ["wallet"] - amount)
    save_config()
    await ctx.reply(f"🟦 Removed **{amount}** coins from {member.mention}'s wallet!")


# =====================================================================
# ECONOMY COMMANDS
# =====================================================================

@bot.command(name="balance", aliases=["bal"])
async def balance(ctx, member: discord.Member = None):
    """Checks user coin balance."""
    m = member or ctx.author
    econ = get_user_econ(m.id)
    emojis = get_emoji_dict(ctx.guild)
    
    embed = discord.Embed(title=f"{emojis['coin']} Balance — {m.display_name}", color=discord.Color.blue())
    embed.add_field(name="Wallet", value=f"**{econ['wallet']}** coins", inline=True)
    embed.add_field(name="Bank", value=f"**{econ['bank']}** coins", inline=True)
    embed.add_field(name="Net Worth", value=f"**{econ['wallet'] + econ['bank']}** coins", inline=True)
    embed.set_thumbnail(url=m.display_avatar.url)
    await ctx.reply(embed=embed)


@bot.command(name="daily")
async def daily(ctx):
    """Claims daily coins."""
    import time
    user_id = str(ctx.author.id)
    now = time.time()
    last_claim = config.get("daily_cooldowns", {}).get(user_id, 0)
    emojis = get_emoji_dict(ctx.guild)

    if now - last_claim < 86400:
        remaining = int(86400 - (now - last_claim)) // 3600
        await ctx.reply(embed=discord.Embed(description=f"{emojis['warning']} You already claimed your daily reward! Come back in **{remaining} hours**.", color=discord.Color.blue()))
        return

    if "daily_cooldowns" not in config:
        config["daily_cooldowns"] = {}
    config["daily_cooldowns"][user_id] = now
    
    econ = get_user_econ(ctx.author.id)
    reward = 250
    econ["wallet"] += reward
    save_config()

    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Claimed your daily reward of **{reward}** coins!", color=discord.Color.blue()))


@bot.command(name="work")
async def work(ctx):
    """Works to earn coins."""
    import time
    user_id = str(ctx.author.id)
    now = time.time()
    last_work = config.get("work_cooldowns", {}).get(user_id, 0)
    emojis = get_emoji_dict(ctx.guild)

    if now - last_work < 3600:
        remaining = int(3600 - (now - last_work)) // 60
        await ctx.reply(embed=discord.Embed(description=f"{emojis['warning']} You are exhausted! Work again in **{remaining} minutes**.", color=discord.Color.blue()))
        return

    if "work_cooldowns" not in config:
        config["work_cooldowns"] = {}
    config["work_cooldowns"][user_id] = now

    earned = random.randint(50, 200)
    jobs = ["Discord Mod", "Developer", "Graphic Designer", "Support Representative"]
    job = random.choice(jobs)

    econ = get_user_econ(ctx.author.id)
    econ["wallet"] += earned
    save_config()

    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Worked as a **{job}** and earned **{earned}** coins!", color=discord.Color.blue()))


@bot.command(name="beg")
async def beg(ctx):
    """Begs for coins."""
    import time
    user_id = str(ctx.author.id)
    now = time.time()
    last_beg = config.get("beg_cooldowns", {}).get(user_id, 0)
    emojis = get_emoji_dict(ctx.guild)

    if now - last_beg < 300:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['warning']} Please wait 5 minutes between begging attempts.", color=discord.Color.blue()))
        return

    if "beg_cooldowns" not in config:
        config["beg_cooldowns"] = {}
    config["beg_cooldowns"][user_id] = now

    if random.choice([True, False]):
        earned = random.randint(10, 50)
        econ = get_user_econ(ctx.author.id)
        econ["wallet"] += earned
        save_config()
        await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} A kind stranger gave you **{earned}** coins!", color=discord.Color.blue()))
    else:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Nobody gave you any coins this time.", color=discord.Color.blue()))


@bot.command(name="deposit", aliases=["dep"])
async def deposit(ctx, amount: str):
    """Deposits coins into bank."""
    econ = get_user_econ(ctx.author.id)
    emojis = get_emoji_dict(ctx.guild)

    if amount.lower() == "all":
        amt = econ["wallet"]
    else:
        try:
            amt = int(amount)
        except ValueError:
            await ctx.reply("Invalid amount.")
            return

    if amt <= 0 or amt > econ["wallet"]:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Invalid deposit amount.", color=discord.Color.blue()))
        return

    econ["wallet"] -= amt
    econ["bank"] += amt
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Deposited **{amt}** coins into your bank!", color=discord.Color.blue()))


@bot.command(name="withdraw", aliases=["with"])
async def withdraw(ctx, amount: str):
    """Withdraws coins from bank."""
    econ = get_user_econ(ctx.author.id)
    emojis = get_emoji_dict(ctx.guild)

    if amount.lower() == "all":
        amt = econ["bank"]
    else:
        try:
            amt = int(amount)
        except ValueError:
            await ctx.reply("Invalid amount.")
            return

    if amt <= 0 or amt > econ["bank"]:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Invalid withdrawal amount.", color=discord.Color.blue()))
        return

    econ["bank"] -= amt
    econ["wallet"] += amt
    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Withdrew **{amt}** coins from your bank!", color=discord.Color.blue()))


@bot.command(name="pay")
async def pay(ctx, member: discord.Member, amount: int):
    """Transfers wallet coins to another member."""
    emojis = get_emoji_dict(ctx.guild)
    if amount <= 0:
        return
    sender = get_user_econ(ctx.author.id)
    if sender["wallet"] < amount:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Insufficient funds in wallet.", color=discord.Color.blue()))
        return

    receiver = get_user_econ(member.id)
    sender["wallet"] -= amount
    receiver["wallet"] += amount
    save_config()

    await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Sent **{amount}** coins to {member.mention}!", color=discord.Color.blue()))


@bot.command(name="leaderboard", aliases=["lb"])
async def leaderboard(ctx):
    """Displays top server economy balances."""
    emojis = get_emoji_dict(ctx.guild)
    sorted_econ = sorted(config.get("economy", {}).items(), key=lambda x: x[1].get("wallet", 0) + x[1].get("bank", 0), reverse=True)[:10]

    lb_str = ""
    for idx, (uid, data) in enumerate(sorted_econ, 1):
        m = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f"User {uid}"
        total = data.get("wallet", 0) + data.get("bank", 0)
        lb_str += f"**#{idx} {name}** — {total} coins\n"

    embed = discord.Embed(title=f"{emojis['trophy']} SLS Helper • Economy Leaderboard", description=lb_str or "No records.", color=discord.Color.blue())
    await ctx.reply(embed=embed)


# =====================================================================
# MINI-GAMES MODULE
# =====================================================================

@bot.command(name="slots")
async def slots(ctx, bet: int):
    """Gambles coins on a slot machine."""
    emojis = get_emoji_dict(ctx.guild)
    econ = get_user_econ(ctx.author.id)

    if bet <= 0 or econ["wallet"] < bet:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Invalid bet amount or insufficient funds.", color=discord.Color.blue()))
        return

    symbols = ["🟦", "💎", "⭐", "🔔", "7️⃣"]
    s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)

    if s1 == s2 == s3:
        payout = bet * 5
        econ["wallet"] += payout
        res = f"🎉 **JACKPOT!** You won **{payout}** coins!"
    elif s1 == s2 or s2 == s3 or s1 == s3:
        payout = bet * 2
        econ["wallet"] += payout - bet
        res = f"✨ **MATCH!** You won **{payout}** coins!"
    else:
        econ["wallet"] -= bet
        res = f"❌ You lost **{bet}** coins!"

    save_config()
    embed = discord.Embed(title=f"{emojis['dice']} Slot Machine", description=f"[ {s1} | {s2} | {s3} ]\n\n{res}", color=discord.Color.blue())
    await ctx.reply(embed=embed)


@bot.command(name="dice")
async def dice_game(ctx, bet: int, guess: int):
    """Bets coins on a dice roll (1-6)."""
    emojis = get_emoji_dict(ctx.guild)
    econ = get_user_econ(ctx.author.id)

    if bet <= 0 or econ["wallet"] < bet or guess < 1 or guess > 6:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Invalid bet or guess (choose 1-6).", color=discord.Color.blue()))
        return

    roll = random.randint(1, 6)
    if roll == guess:
        win = bet * 4
        econ["wallet"] += win
        res = f"🎉 **CORRECT!** Rolled a **{roll}**. Won **{win}** coins!"
    else:
        econ["wallet"] -= bet
        res = f"❌ Rolled a **{roll}**. Lost **{bet}** coins."

    save_config()
    await ctx.reply(embed=discord.Embed(description=f"{emojis['dice']} {res}", color=discord.Color.blue()))


@bot.command(name="coinflip", aliases=["cf"])
async def coinflip_game(ctx, bet: int = 0, choice: str = "heads"):
    """Flips a coin or bets on outcome."""
    emojis = get_emoji_dict(ctx.guild)
    result = random.choice(["heads", "tails"])

    if bet <= 0:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['success']} Coin landed on **{result.capitalize()}**!", color=discord.Color.blue()))
        return

    econ = get_user_econ(ctx.author.id)
    if econ["wallet"] < bet:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Insufficient funds.", color=discord.Color.blue()))
        return

    if choice.lower() == result:
        econ["wallet"] += bet
        res = f"🎉 Landed on **{result.capitalize()}**! Won **{bet}** coins!"
    else:
        econ["wallet"] -= bet
        res = f"❌ Landed on **{result.capitalize()}**! Lost **{bet}** coins."

    save_config()
    await ctx.reply(embed=discord.Embed(description=res, color=discord.Color.blue()))


@bot.command(name="rps")
async def rps(ctx, choice: str, bet: int = 0):
    """Plays Rock Paper Scissors."""
    emojis = get_emoji_dict(ctx.guild)
    user_choice = choice.lower()
    if user_choice not in ["rock", "paper", "scissors"]:
        await ctx.reply("Choose `rock`, `paper`, or `scissors`.")
        return

    bot_choice = random.choice(["rock", "paper", "scissors"])
    econ = get_user_econ(ctx.author.id)

    if bet > 0 and econ["wallet"] < bet:
        await ctx.reply(embed=discord.Embed(description=f"{emojis['error']} Insufficient funds.", color=discord.Color.blue()))
        return

    if user_choice == bot_choice:
        res = f"👔 **Tie!** Bot also chose **{bot_choice}**."
    elif (user_choice == "rock" and bot_choice == "scissors") or (user_choice == "paper" and bot_choice == "rock") or (user_choice == "scissors" and bot_choice == "paper"):
        if bet > 0:
            econ["wallet"] += bet
            save_config()
        res = f"🎉 **You Win!** Bot chose **{bot_choice}**. Won **{bet}** coins!"
    else:
        if bet > 0:
            econ["wallet"] -= bet
            save_config()
        res = f"❌ **You Lose!** Bot chose **{bot_choice}**. Lost **{bet}** coins."

    await ctx.reply(embed=discord.Embed(description=res, color=discord.Color.blue()))


# =====================================================================
# MAIN HELP COMMAND
# =====================================================================

@bot.command(name="help")
async def help_command(ctx):
    emojis = get_emoji_dict(ctx.guild)
    embed = discord.Embed(
        title=f"{emojis['gear']} SLS Helper • Command Center",
        description="Complete command suite for SLS Helper:",
        color=discord.Color.blue()
    )
    embed.add_field(name=f"{emojis['shield']} Staff & Management", value="`>promo`, `>demo`, `>super`, `>staff`, `>train`, `>trainings`", inline=False)
    embed.add_field(name=f"{emojis['warning']} Moderation", value="`>kick`, `>ban`, `>unban`, `>mute`, `>unmute`, `>warn`, `>unwarn`, `>clear`", inline=False)
    embed.add_field(name=f"{emojis['ticket']} Support & Tickets", value="`>sendticket`, `>setstaffrole @role`, `>setcategory <type> #category`", inline=False)
    embed.add_field(name=f"{emojis['coin']} Economy", value="`>balance`, `>daily`, `>work`, `>beg`, `>deposit`, `>withdraw`, `>pay`, `>leaderboard`", inline=False)
    embed.add_field(name=f"{emojis['dice']} Mini-Games", value="`>slots <bet>`, `>dice <bet> <guess>`, `>coinflip [bet] [choice]`, `>rps <choice> [bet]`", inline=False)
    embed.add_field(name=f"{emojis['gear']} Setup & Emojis", value="`>setupemojis`, `>ranks add @role`, `>ranks clear`, `>setstaffsupervisor`, `>setpromodemo`, `>setaudit`", inline=False)
    
    if ctx.author.id == OWNER_ID:
        embed.add_field(name="👑 Owner Commands", value="`>eval`, `>restart`, `>shutdown`, `>botservers`, `>addcoins`, `>removecoins`", inline=False)

    embed.set_footer(text="SLS Helper System")
    await ctx.reply(embed=embed, mention_author=False)


@bot.event
async def on_ready():
    bot.add_view(TicketDropdownView())
    bot.add_view(TicketPanelActionsView())
    logging.info("SLS Helper logged in as %s", bot.user)


load_config()
bot.run(TOKEN)
