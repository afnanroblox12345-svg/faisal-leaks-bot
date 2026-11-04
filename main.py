import os
import random
import sqlite3
import time
import asyncio
from pathlib import Path
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DATABASE_PATH", "funbot.sqlite3")
# After uploading emoji.gg emojis to your server, set these env vars to values like <:coin:1234567890>.
COIN = os.getenv("EMOJI_COIN", "🪙")
GUILD_EMOJIS = {}
EMOJI_NAMES = {"coin": "supreme_coin", "party": "supreme_confetti", "shield": "supreme_shield"}
def guild_emoji(guild, key, fallback):
    if not guild: return fallback
    cached = GUILD_EMOJIS.get(guild.id, {}).get(key)
    if cached: return cached
    stored = discord.utils.get(guild.emojis, name=EMOJI_NAMES.get(key, ""))
    return str(stored) if stored else fallback
SPARKLE = os.getenv("EMOJI_SPARKLE", "✨")
PARTY = os.getenv("EMOJI_PARTY", "🎉")
SHIELD = os.getenv("EMOJI_SHIELD", "🛡️")

if not TOKEN:
    raise RuntimeError("Set the DISCORD_TOKEN environment variable in your hosting panel.")

intents = discord.Intents.default()
intents.message_content = True  # Enable Message Content Intent in the Discord Developer Portal too.
bot = commands.Bot(command_prefix=";", intents=intents, help_command=None)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS wallets (
                guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                coins INTEGER NOT NULL DEFAULT 0, last_daily INTEGER NOT NULL DEFAULT 0,
                last_work INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL, created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inventory (
                guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, item TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, item)
            );
        """)


def wallet(guild_id: int, user_id: int):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        return conn.execute("SELECT * FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()


def change_coins(guild_id: int, user_id: int, delta: int):
    wallet(guild_id, user_id)
    with db() as conn:
        conn.execute("UPDATE wallets SET coins=MAX(0, coins+?) WHERE guild_id=? AND user_id=?", (delta, guild_id, user_id))
        return conn.execute("SELECT coins FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()["coins"]


def embed(title: str, description: str, color=0x9B59B6):
    return discord.Embed(title=title, description=description, color=color)




async def require_mod(interaction: discord.Interaction, permission: str) -> bool:
    perms = interaction.user.guild_permissions
    if not (perms.administrator or getattr(perms, permission, False)):
        await interaction.response.send_message(f"{guild_emoji(interaction.guild, 'shield', SHIELD)} You need that specific moderator permission to use this command.", ephemeral=True)
        return False
    return True


@bot.command(name="help")
async def prefix_help(ctx):
    e = embed(f"{guild_emoji(ctx.guild, 'party', PARTY)} Supreme Bot Commands", "Prefix commands start with `;`. Slash commands are available too.")
    e.add_field(name="🎮 Fun & social", value="`;ping` `;roll` `;coinflip` `;8ball` `;ship` `;choose` `;rps` `;rate` `;compliment` `;joke` `;trivia` `;avatar` `;userinfo` `;serverinfo` `;poll`", inline=False)
    e.add_field(name="💰 Economy", value="`;balance` `;daily` `;work` `;leaderboard` `;shop` `;buy` `;inventory` `;pay` `;slots` `;gamble` `;beg`", inline=False)
    e.add_field(name="🛡️ Moderation", value="`;kick` `;ban` `;timeout` `;untimeout` `;clear` `;warn` `;warnings` `;unwarn` `;unban` `;slowmode` `;lock` `;unlock` `;nickname` `;addrole` `;removerole`", inline=False)
    e.add_field(name="🔧 Other", value="`;setupemojis` uploads emoji.gg custom emojis", inline=False)
    await ctx.send(embed=e)

@bot.command(name="ping")
async def prefix_ping(ctx):
    await ctx.send(f"🏓 Pong! `{round(bot.latency * 1000)} ms` {SPARKLE}")

@bot.command(name="roll")
async def prefix_roll(ctx, maximum: int = 100):
    if not 2 <= maximum <= 100000:
        await ctx.send("Choose a maximum between 2 and 100000.")
        return
    await ctx.send(f"🎲 You rolled **{random.randint(1, maximum)}** (1–{maximum})!")

@bot.command(name="coinflip", aliases=["flip"])
async def prefix_coinflip(ctx):
    await ctx.send(f"🪙 **{random.choice(['Heads', 'Tails'])}!**")

@bot.command(name="balance", aliases=["bal"])
@commands.guild_only()
async def prefix_balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = wallet(ctx.guild.id, member.id)
    await ctx.send(f"💰 **{member.display_name}** has **{row['coins']:,}** {guild_emoji(ctx.guild, 'coin', COIN)}.")

@bot.command(name="daily")
@commands.guild_only()
async def prefix_daily(ctx):
    row = wallet(ctx.guild.id, ctx.author.id)
    now = int(time.time())
    wait = 86400 - (now - row["last_daily"])
    if wait > 0:
        await ctx.send(f"⏰ Your next daily reward is in **{wait // 3600}h {(wait % 3600) // 60}m**.")
        return
    amount = random.randint(100, 175)
    with db() as conn:
        conn.execute("UPDATE wallets SET coins=coins+?, last_daily=? WHERE guild_id=? AND user_id=?", (amount, now, ctx.guild.id, ctx.author.id))
    await ctx.send(f"🎁 Daily claimed! You got **{amount}** {guild_emoji(ctx.guild, 'coin', COIN)}. See you tomorrow!")

@bot.command(name="work")
@commands.guild_only()
async def prefix_work(ctx):
    row = wallet(ctx.guild.id, ctx.author.id)
    now = int(time.time())
    wait = 60 - (now - row["last_work"])
    if wait > 0:
        await ctx.send(f"😴 You need a break! Try again in **{wait}s**.")
        return
    amount = random.randint(15, 55)
    jobs = ["walked a dragon", "DJ'd a party", "delivered moon mail", "helped a wizard", "found a lost sock"]
    with db() as conn:
        conn.execute("UPDATE wallets SET coins=coins+?, last_work=? WHERE guild_id=? AND user_id=?", (amount, now, ctx.guild.id, ctx.author.id))
    await ctx.send(f"🧰 You {random.choice(jobs)} and earned **{amount}** {guild_emoji(ctx.guild, 'coin', COIN)}!")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing something. Try `;help`.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("I couldn't understand that argument. Try `;help`.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("That command only works in a server.")
    else:
        raise error
@bot.command(name="8ball")
async def prefix_8ball(ctx, *, question: str):
    answer = random.choice(["Absolutely!", "Definitely not.", "The stars say yes.", "Ask again after a snack.", "Maybe…", "100% certified chaos.", "I have a good feeling about it."])
    await ctx.send(f"🎱 **{question}**\n✨ {answer}")

@bot.command(name="ship")
async def prefix_ship(ctx, person_a: str, person_b: str = None):
    if person_b is None:
        person_a, person_b = str(ctx.author.display_name), person_a
    score = random.randint(0, 100)
    await ctx.send(f"💞 **{person_a} + {person_b}** = **{score}%** {('💖' if score >= 70 else '💛' if score >= 40 else '🫶')}")

@bot.command(name="leaderboard", aliases=["top", "richlist"])
@commands.guild_only()
async def prefix_leaderboard(ctx):
    with db() as conn:
        rows = conn.execute("SELECT user_id,coins FROM wallets WHERE guild_id=? ORDER BY coins DESC LIMIT 10", (ctx.guild.id,)).fetchall()
    lines = [f"**{i}.** <@{r['user_id']}> — {r['coins']:,} {guild_emoji(ctx.guild, 'coin', COIN)}" for i, r in enumerate(rows, 1)]
    await ctx.send(embed=embed("🏆 Coin Leaders", "\n".join(lines) or "No coins yet—start with `;daily`!"))

@bot.command(name="shop")
async def prefix_shop(ctx):
    lines = [f"`{item}` — **{price}** {guild_emoji(ctx.guild, 'coin', COIN)} • {label}" for item, (price, label) in SHOP.items()]
    await ctx.send(embed=embed("🛍️ Fun Shop", "Buy an item with `;buy <item>`\n\n" + "\n".join(lines)))

@bot.command(name="buy")
async def prefix_buy(ctx, item: str):
    item = item.lower()
    if item not in SHOP:
        await ctx.send("That item isn't in the shop. Try `;shop`.")
        return
    price, label = SHOP[item]
    row = wallet(ctx.guild.id, ctx.author.id)
    if row["coins"] < price:
        await ctx.send(f"You need **{price - row['coins']}** more {guild_emoji(ctx.guild, 'coin', COIN)}.")
        return
    change_coins(ctx.guild.id, ctx.author.id, -price)
    with db() as conn:
        conn.execute("INSERT INTO inventory(guild_id,user_id,item,quantity) VALUES(?,?,?,1) ON CONFLICT(guild_id,user_id,item) DO UPDATE SET quantity=quantity+1", (ctx.guild.id, ctx.author.id, item))
    await ctx.send(f"🛒 Bought **{label}**! Check `;inventory`.")

@bot.command(name="inventory", aliases=["inv"])
async def prefix_inventory(ctx, member: discord.Member = None):
    member = member or ctx.author
    with db() as conn:
        rows = conn.execute("SELECT item,quantity FROM inventory WHERE guild_id=? AND user_id=? AND quantity>0", (ctx.guild.id, member.id)).fetchall()
    desc = "\n".join(f"{SHOP[r['item']][1]} × **{r['quantity']}**" for r in rows) or "Their pockets are empty. Visit `;shop`!"
    await ctx.send(embed=embed(f"🎒 {member.display_name}'s Inventory", desc))

@bot.command(name="pay", aliases=["give"])
async def prefix_pay(ctx, member: discord.Member, amount: int):
    if member.bot or member.id == ctx.author.id or amount < 1:
        await ctx.send("Choose another member and an amount of at least 1 coin.")
        return
    row = wallet(ctx.guild.id, ctx.author.id)
    if row["coins"] < amount:
        await ctx.send("You don't have enough coins.")
        return
    change_coins(ctx.guild.id, ctx.author.id, -amount)
    change_coins(ctx.guild.id, member.id, amount)
    await ctx.send(f"💸 Sent **{amount}** {guild_emoji(ctx.guild, 'coin', COIN)} to {member.mention}!")

async def prefix_mod_check(ctx, permission="manage_messages"):
    perms = ctx.author.guild_permissions
    if not (perms.administrator or getattr(perms, permission, False)):
        await ctx.send("🛡️ You need moderator permissions to use that command.")
        return False
    return True


@bot.command(name="kick")
async def prefix_kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await prefix_mod_check(ctx, 'kick_members'): return
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("You can't kick someone with an equal or higher role."); return
    try:
        await member.kick(reason=f"{reason} | By {ctx.author}")
        await ctx.send(f"👢 Kicked **{member}**. Reason: {reason}")
    except discord.Forbidden:
        await ctx.send("I can't kick that member. Check my role and permissions.")

@bot.command(name="ban")
async def prefix_ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await prefix_mod_check(ctx, 'ban_members'): return
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("You can't ban someone with an equal or higher role."); return
    try:
        await member.ban(reason=f"{reason} | By {ctx.author}")
        await ctx.send(f"🔨 Banned **{member}**. Reason: {reason}")
    except discord.Forbidden:
        await ctx.send("I can't ban that member. Check my role and permissions.")

@bot.command(name="timeout", aliases=["mute"])
async def prefix_timeout(ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):
    if not await prefix_mod_check(ctx, 'moderate_members'): return
    if not 1 <= minutes <= 40320:
        await ctx.send("Choose a timeout between 1 and 40320 minutes."); return
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("You can't timeout someone with an equal or higher role."); return
    try:
        await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | By {ctx.author}")
        await ctx.send(f"🔇 Timed out **{member}** for **{minutes} minutes**. Reason: {reason}")
    except discord.Forbidden:
        await ctx.send("I can't timeout that member. Check my role and permissions.")

@bot.command(name="untimeout", aliases=["unmute"])
async def prefix_untimeout(ctx, member: discord.Member, *, reason="Timeout removed"):
    if not await prefix_mod_check(ctx, 'moderate_members'): return
    try:
        await member.timeout(None, reason=f"{reason} | By {ctx.author}")
        await ctx.send(f"🔊 Removed timeout for {member.mention}.")
    except discord.Forbidden:
        await ctx.send("I can't edit that member. Check my role and permissions.")

@bot.command(name="clear", aliases=["purge", "clean"])
async def prefix_clear(ctx, amount: int):
    if not await prefix_mod_check(ctx, 'manage_messages'): return
    if not 1 <= amount <= 100:
        await ctx.send("Choose a number from 1 to 100."); return
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        notice = await ctx.send(f"🧹 Cleared **{max(0, len(deleted)-1)}** messages.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("I need Manage Messages permission here.")

@bot.command(name="warn")
async def prefix_warn(ctx, member: discord.Member, *, reason: str):
    if not await prefix_mod_check(ctx, 'manage_messages'): return
    if member.bot or member.id == ctx.author.id:
        await ctx.send("Choose a different member."); return
    with db() as conn:
        conn.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)", (ctx.guild.id, member.id, ctx.author.id, reason, int(time.time())))
        count = conn.execute("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)).fetchone()["n"]
    await ctx.send(f"⚠️ Warned {member.mention}. They now have **{count}** warning(s). Reason: {reason}")

@bot.command(name="warnings", aliases=["warns"])
async def prefix_warnings(ctx, member: discord.Member):
    if not await prefix_mod_check(ctx, 'manage_messages'): return
    with db() as conn:
        rows = conn.execute("SELECT moderator_id,reason,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10", (ctx.guild.id, member.id)).fetchall()
    lines = [f"<t:{r['created_at']}:d> — {r['reason']} (by <@{r['moderator_id']}>)" for r in rows]
    await ctx.send(embed=embed(f"⚠️ Warnings for {member}", "\n".join(lines) or "No warnings found."))

@bot.command(name="unwarn")
async def prefix_unwarn(ctx, member: discord.Member, warning_id: int = None):
    if not await prefix_mod_check(ctx, 'manage_messages'): return
    with db() as conn:
        row = conn.execute("SELECT id FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1", (ctx.guild.id, member.id)).fetchone()
        if row:
            conn.execute("DELETE FROM warnings WHERE id=?", (row["id"],))
    await ctx.send(f"✅ Removed the latest warning for {member.mention}." if row else "No warning to remove.")
@bot.command(name="choose")
async def choose(ctx, *, options: str):
    picks = [x.strip() for x in options.split(",") if x.strip()]
    if len(picks) < 2:
        await ctx.send("Give me at least two choices, separated by commas."); return
    await ctx.send(f"🤔 I choose **{random.choice(picks)}**!")

@bot.command(name="rps", aliases=["rockpaperscissors"])
async def rps(ctx, choice: str):
    mapping = {"r":"rock", "rock":"rock", "p":"paper", "paper":"paper", "s":"scissors", "scissors":"scissors"}
    player = mapping.get(choice.lower())
    if not player:
        await ctx.send("Choose rock, paper, or scissors."); return
    cpu = random.choice(["rock", "paper", "scissors"])
    result = "It's a tie!" if player == cpu else "You win!" if (player, cpu) in [("rock","scissors"),("paper","rock"),("scissors","paper")] else "I win this round!"
    await ctx.send(f"✊ You picked **{player}**; I picked **{cpu}**. {result}")

@bot.command(name="rate")
async def rate(ctx, *, thing: str):
    await ctx.send(f"📊 I rate **{thing}** a **{random.randint(0, 100)}/100**. Extremely scientific.")

@bot.command(name="compliment")
async def compliment(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(f"💖 {member.mention}, {random.choice(['you make this server brighter','your vibe is immaculate','you are an absolute legend','you deserve a little treat today','you bring excellent energy'])}!")

@bot.command(name="joke")
async def joke(ctx):
    await ctx.send(random.choice(["Why did the bot cross the road? To get better Wi-Fi.", "I told my computer I needed a break. It said: no problem, I'll go to sleep.", "Why was the math book sad? Too many problems.", "What do you call a fish with no eyes? Fsh.", "I tried to catch fog yesterday. Mist."]))

@bot.command(name="trivia")
async def trivia(ctx):
    q, answer = random.choice([("What is the largest planet in our solar system?", "jupiter"), ("How many sides does a hexagon have?", "6"), ("What is the capital of Japan?", "tokyo"), ("Which ocean is the largest?", "pacific"), ("How many colors are in a rainbow?", "7")])
    await ctx.send(f"🧠 **Trivia:** {q}\nReply with your guess!")
    def check(m): return m.channel == ctx.channel and not m.author.bot
    try:
        reply = await bot.wait_for("message", check=check, timeout=20)
        await ctx.send("✅ Correct!" if reply.content.lower().strip() == answer else f"❌ The answer was **{answer.title()}**.")
    except TimeoutError:
        await ctx.send(f"⌛ Time's up! The answer was **{answer.title()}**.")

@bot.command(name="avatar", aliases=["pfp"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    e = embed(f"🖼️ {member.display_name}'s avatar", ""); e.set_image(url=member.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="userinfo", aliases=["whois"])
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    e = embed(f"👤 {member.display_name}", f"**Account created:** <t:{int(member.created_at.timestamp())}:R>\n**Joined server:** <t:{int(member.joined_at.timestamp())}:R>\n**Top role:** {member.top_role.mention}\n**ID:** `{member.id}`")
    e.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="serverinfo", aliases=["server"])
@commands.guild_only()
async def serverinfo(ctx):
    g = ctx.guild
    e = embed(f"🏰 {g.name}", f"**Members:** {g.member_count}\n**Created:** <t:{int(g.created_at.timestamp())}:D>\n**Channels:** {len(g.channels)}\n**Roles:** {len(g.roles)}\n**Owner:** <@{g.owner_id}>")
    if g.icon: e.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=e)

@bot.command(name="poll")
async def poll(ctx, *, question: str):
    msg = await ctx.send(embed=embed("📊 Quick Poll", question))
    for reaction in ("👍", "👎"):
        try: await msg.add_reaction(reaction)
        except discord.Forbidden: break

@bot.command(name="slots")
@commands.guild_only()
async def slots(ctx, bet: int):
    if not 1 <= bet <= 10000:
        await ctx.send("Bet between 1 and 10,000 coins."); return
    row = wallet(ctx.guild.id, ctx.author.id)
    if row["coins"] < bet:
        await ctx.send("You don't have enough coins."); return
    spin = [random.choice(["🍒", "🍋", "🔔", "⭐", "7️⃣"]) for _ in range(3)]
    if len(set(spin)) == 1: payout = bet * 5
    elif len(set(spin)) == 2: payout = bet
    else: payout = -bet
    total = change_coins(ctx.guild.id, ctx.author.id, payout)
    outcome = f"won **{payout:,}**" if payout > 0 else f"lost **{bet:,}**"
    await ctx.send(f"🎰 {' | '.join(spin)}\nYou {outcome} {guild_emoji(ctx.guild, 'coin', COIN)}. Balance: **{total:,}**.")

@bot.command(name="gamble", aliases=["coinbet"])
@commands.guild_only()
async def gamble(ctx, bet: int):
    if not 1 <= bet <= 10000:
        await ctx.send("Bet between 1 and 10,000 coins."); return
    if wallet(ctx.guild.id, ctx.author.id)["coins"] < bet:
        await ctx.send("You don't have enough coins."); return
    win = random.choice([True, False])
    total = change_coins(ctx.guild.id, ctx.author.id, bet if win else -bet)
    await ctx.send(f"🪙 The coin landed **{'heads — you win' if win else 'tails — you lose'}**! Balance: **{total:,}** {guild_emoji(ctx.guild, 'coin', COIN)}.")

@bot.command(name="beg")
@commands.guild_only()
@commands.cooldown(1, 45, commands.BucketType.user)
async def beg(ctx):
    amount = random.randint(1, 35)
    if random.random() < .2:
        await ctx.send("🫣 Nobody had spare change this time."); return
    total = change_coins(ctx.guild.id, ctx.author.id, amount)
    await ctx.send(f"🥺 A kind stranger gave you **{amount}** {guild_emoji(ctx.guild, 'coin', COIN)}. Balance: **{total:,}**.")

@bot.command(name="slowmode")
async def slowmode(ctx, seconds: int):
    if not await prefix_mod_check(ctx, 'manage_channels'): return
    if not 0 <= seconds <= 21600:
        await ctx.send("Slowmode must be from 0 to 21600 seconds."); return
    try:
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"By {ctx.author}")
        await ctx.send(f"🐢 Slowmode set to **{seconds}s**.")
    except discord.Forbidden: await ctx.send("I need Manage Channels permission.")

@bot.command(name="lock")
async def lock(ctx):
    if not await prefix_mod_check(ctx, 'manage_channels'): return
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Channel locked for @everyone.")
    except discord.Forbidden: await ctx.send("I need Manage Channels permission.")

@bot.command(name="unlock")
async def unlock(ctx):
    if not await prefix_mod_check(ctx, 'manage_channels'): return
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None)
        await ctx.send("🔓 Channel unlocked for @everyone.")
    except discord.Forbidden: await ctx.send("I need Manage Channels permission.")

@bot.command(name="nickname", aliases=["nick"])
async def nickname(ctx, member: discord.Member, *, name: str = None):
    if not await prefix_mod_check(ctx, 'manage_nicknames'): return
    try:
        await member.edit(nick=name, reason=f"By {ctx.author}")
        await ctx.send(f"✅ Updated nickname for {member.mention}.")
    except discord.Forbidden: await ctx.send("I can't edit that member's nickname. Check role order.")

@bot.command(name="addrole")
async def addrole(ctx, member: discord.Member, *, role: discord.Role):
    if not await prefix_mod_check(ctx, 'manage_roles'): return
    try:
        await member.add_roles(role, reason=f"By {ctx.author}")
        await ctx.send(f"✅ Added {role.mention} to {member.mention}.")
    except discord.Forbidden: await ctx.send("I can't assign that role. Check role order and permissions.")

@bot.command(name="removerole")
async def removerole(ctx, member: discord.Member, *, role: discord.Role):
    if not await prefix_mod_check(ctx, 'manage_roles'): return
    try:
        await member.remove_roles(role, reason=f"By {ctx.author}")
        await ctx.send(f"✅ Removed {role.mention} from {member.mention}.")
    except discord.Forbidden: await ctx.send("I can't remove that role. Check role order and permissions.")

@bot.command(name="unban")
async def unban(ctx, user_id: int, *, reason="Ban removed"):
    if not await prefix_mod_check(ctx, 'ban_members'): return
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"{reason} | By {ctx.author}")
        await ctx.send(f"✅ Unbanned **{user}**.")
    except discord.NotFound: await ctx.send("That user isn't banned.")
    except discord.Forbidden: await ctx.send("I need Ban Members permission.")

EMOJI_ASSETS = {
    "supreme_coin": "https://cdn3.emoji.gg/emojis/39708-coin.png",
    "supreme_confetti": "https://cdn3.emoji.gg/emojis/425769-confetti.png",
    "supreme_shield": "https://cdn3.emoji.gg/emojis/shield.png",
}

def _download_emoji_assets():
    from pathlib import Path
    from urllib.request import Request, urlopen
    folder = Path(__file__).resolve().parent / "assets" / "emojis"
    folder.mkdir(parents=True, exist_ok=True)
    for name, url in EMOJI_ASSETS.items():
        path = folder / f"{name}.png"
        if not path.exists():
            request = Request(url, headers={"User-Agent": "SupremeBot/1.0 (Discord emoji setup)"})
            with urlopen(request, timeout=20) as response:
                data = response.read(256_001)
            if not data or len(data) > 256_000:
                raise ValueError(f"{name} image is empty or too large")
            path.write_bytes(data)
    return folder

async def install_emojis(guild):
    import asyncio
    folder = await asyncio.to_thread(_download_emoji_assets)
    installed = []
    for name in EMOJI_ASSETS:
        existing = discord.utils.get(guild.emojis, name=name)
        if existing:
            installed.append(str(existing)); continue
        path = folder / f"{name}.png"
        emoji = await guild.create_custom_emoji(name=name, image=path.read_bytes(), reason="Supreme Bot emoji setup")
        installed.append(str(emoji))
    GUILD_EMOJIS[guild.id] = dict(zip(("coin", "party", "shield"), installed))
    return installed

@bot.tree.command(name="setupemojis", description="Install Supreme Bot emoji pack to this server")
async def slash_setupemojis(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("Only server managers can install the bot emoji pack.", ephemeral=True); return
    if not interaction.guild.me.guild_permissions.manage_emojis_and_stickers:
        await interaction.response.send_message("I need Manage Expressions permission to upload emojis.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        added = await install_emojis(interaction.guild)
        await interaction.followup.send("Emoji pack saved in `assets/emojis/` and installed: " + " ".join(added), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Emoji setup failed: `{type(exc).__name__}`. Check permissions, network, and available emoji slots.", ephemeral=True)

@bot.command(name="setupemojis")
@commands.guild_only()
async def prefix_setupemojis(ctx):
    if not (ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator):
        await ctx.send("Only server managers can install the bot's emoji pack."); return
    if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
        await ctx.send("I need Manage Expressions permission to upload emojis."); return
    try:
        added = await install_emojis(ctx.guild)
        await ctx.send("✅ Emoji pack saved in `assets/emojis/` and available in this server: " + " ".join(added))
    except Exception as exc:
        await ctx.send(f"Emoji setup couldn't finish: `{type(exc).__name__}`. Check the bot's permissions, network access, and available emoji slots.")
@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Supreme Bot ready as {bot.user}; synced {len(synced)} slash commands.")
    except discord.HTTPException as exc:
        print(f"Command sync failed: {exc}")


@bot.tree.command(name="help", description="See all the fun and useful commands")
async def help_command(interaction: discord.Interaction):
    e = embed(f"{guild_emoji(interaction.guild, 'party', PARTY)} Supreme Bot Command Menu", "Pick a command and let the chaos begin!")
    e.add_field(name="🎮 Fun & social", value="`/ping` `/roll` `/coinflip` `/8ball` `/ship` and matching `;` commands; prefix also has `;choose` `;rps` `;rate` `;compliment` `;joke` `;trivia` `;avatar` `;userinfo` `;serverinfo` `;poll`", inline=False)
    e.add_field(name="💰 Economy", value="Slash and prefix: `balance` `daily` `work` `leaderboard` `shop` `buy` `inventory` `pay`; prefix also has `;slots` `;gamble` `;beg`", inline=False)
    e.add_field(name="🛡️ Moderation", value="Slash and prefix: `kick` `ban` `timeout` `clear` `warn` `warnings`; prefix adds `untimeout` `unwarn` `unban` `slowmode` `lock` `unlock` `nickname` `addrole` `removerole`", inline=False)
    e.set_footer(text="Economy is per-server. Have fun and be kind!")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="ping", description="Check if the bot is awake")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! `{round(bot.latency * 1000)} ms` {SPARKLE}")


@bot.tree.command(name="roll", description="Roll a number between 1 and your chosen maximum")
@app_commands.describe(maximum="Highest number to roll (2–100000)")
async def roll(interaction: discord.Interaction, maximum: app_commands.Range[int, 2, 100000] = 100):
    await interaction.response.send_message(f"🎲 You rolled **{random.randint(1, maximum)}** (1–{maximum})!")


@bot.tree.command(name="coinflip", description="Flip a coin")
async def coinflip(interaction: discord.Interaction):
    await interaction.response.send_message(f"🪙 **{random.choice(['Heads', 'Tails'])}!**")


@bot.tree.command(name="8ball", description="Ask the magic 8-ball")
@app_commands.describe(question="What do you want to know?")
async def eight_ball(interaction: discord.Interaction, question: str):
    answer = random.choice(["Absolutely!", "Definitely not.", "The stars say yes.", "Ask again after a snack.", "Maybe…", "100% certified chaos.", "I have a good feeling about it."])
    await interaction.response.send_message(f"🎱 **{question}**\n{SPARKLE} {answer}")


@bot.tree.command(name="ship", description="Calculate two people's totally scientific compatibility")
@app_commands.describe(person_a="First person", person_b="Second person")
async def ship(interaction: discord.Interaction, person_a: str, person_b: str):
    score = random.randint(0, 100)
    await interaction.response.send_message(f"💞 **{person_a} + {person_b}** = **{score}%** {('💖' if score >= 70 else '💛' if score >= 40 else '🫶')}")


@bot.tree.command(name="balance", description="Check your server coin balance")
@app_commands.describe(member="Whose balance to check")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    row = wallet(interaction.guild_id, member.id)
    await interaction.response.send_message(f"💰 **{member.display_name}** has **{row['coins']:,}** {guild_emoji(interaction.guild, 'coin', COIN)}.")


@bot.tree.command(name="daily", description="Claim your daily coin reward")
async def daily(interaction: discord.Interaction):
    row = wallet(interaction.guild_id, interaction.user.id)
    now = int(time.time())
    wait = 86400 - (now - row["last_daily"])
    if wait > 0:
        await interaction.response.send_message(f"⏰ Your next daily reward is in **{wait // 3600}h {(wait % 3600) // 60}m**.", ephemeral=True)
        return
    amount = random.randint(100, 175)
    with db() as conn:
        conn.execute("UPDATE wallets SET coins=coins+?, last_daily=? WHERE guild_id=? AND user_id=?", (amount, now, interaction.guild_id, interaction.user.id))
    await interaction.response.send_message(f"🎁 Daily claimed! You got **{amount}** {guild_emoji(interaction.guild, 'coin', COIN)}. See you tomorrow!")


@bot.tree.command(name="work", description="Do a little job for some coins (60-second cooldown)")
async def work(interaction: discord.Interaction):
    row = wallet(interaction.guild_id, interaction.user.id)
    now = int(time.time())
    wait = 60 - (now - row["last_work"])
    if wait > 0:
        await interaction.response.send_message(f"😴 You need a break! Try again in **{wait}s**.", ephemeral=True)
        return
    amount = random.randint(15, 55)
    jobs = ["walked a dragon", "DJ'd a party", "delivered moon mail", "helped a wizard", "found a lost sock"]
    with db() as conn:
        conn.execute("UPDATE wallets SET coins=coins+?, last_work=? WHERE guild_id=? AND user_id=?", (amount, now, interaction.guild_id, interaction.user.id))
    await interaction.response.send_message(f"🧰 You {random.choice(jobs)} and earned **{amount}** {guild_emoji(interaction.guild, 'coin', COIN)}!")


@bot.tree.command(name="leaderboard", description="See the richest players in this server")
async def leaderboard(interaction: discord.Interaction):
    with db() as conn:
        rows = conn.execute("SELECT user_id,coins FROM wallets WHERE guild_id=? ORDER BY coins DESC LIMIT 10", (interaction.guild_id,)).fetchall()
    lines = [f"**{i}.** <@{r['user_id']}> — {r['coins']:,} {guild_emoji(interaction.guild, 'coin', COIN)}" for i, r in enumerate(rows, 1)]
    await interaction.response.send_message(embed=embed("🏆 Coin Leaders", "\n".join(lines) or "No coins yet—start with `/daily`!"))


SHOP = {"party_hat": (150, "🎉 Party Hat"), "lucky_charm": (300, "🍀 Lucky Charm"), "space_snack": (500, "🚀 Space Snack")}


@bot.tree.command(name="shop", description="Browse the silly little shop")
async def shop(interaction: discord.Interaction):
    lines = [f"`{item}` — **{price}** {guild_emoji(interaction.guild, 'coin', COIN)} • {label}" for item, (price, label) in SHOP.items()]
    await interaction.response.send_message(embed=embed("🛍️ Fun Shop", "Buy an item with `/buy item:<name>`\n\n" + "\n".join(lines)))


@bot.tree.command(name="buy", description="Buy an item from the shop")
@app_commands.choices(item=[app_commands.Choice(name=f"{name} — {price} coins", value=name) for name, (price, _) in SHOP.items()])
async def buy(interaction: discord.Interaction, item: app_commands.Choice[str]):
    price, label = SHOP[item.value]
    row = wallet(interaction.guild_id, interaction.user.id)
    if row["coins"] < price:
        await interaction.response.send_message(f"You need **{price - row['coins']}** more {guild_emoji(interaction.guild, 'coin', COIN)}.", ephemeral=True)
        return
    change_coins(interaction.guild_id, interaction.user.id, -price)
    with db() as conn:
        conn.execute("INSERT INTO inventory(guild_id,user_id,item,quantity) VALUES(?,?,?,1) ON CONFLICT(guild_id,user_id,item) DO UPDATE SET quantity=quantity+1", (interaction.guild_id, interaction.user.id, item.value))
    await interaction.response.send_message(f"🛒 Bought **{label}**! Check `/inventory`.")


@bot.tree.command(name="inventory", description="Show your shop items")
async def inventory(interaction: discord.Interaction):
    with db() as conn:
        rows = conn.execute("SELECT item,quantity FROM inventory WHERE guild_id=? AND user_id=? AND quantity>0", (interaction.guild_id, interaction.user.id)).fetchall()
    desc = "\n".join(f"{SHOP[r['item']][1]} × **{r['quantity']}**" for r in rows) or "Your pockets are empty. Visit `/shop`!"
    await interaction.response.send_message(embed=embed(f"🎒 {interaction.user.display_name}'s Inventory", desc))


@bot.tree.command(name="pay", description="Send coins to another member")
@app_commands.describe(member="Who to pay", amount="Number of coins")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Pick another human member to pay!", ephemeral=True)
        return
    row = wallet(interaction.guild_id, interaction.user.id)
    if row["coins"] < amount:
        await interaction.response.send_message("You don't have enough coins.", ephemeral=True)
        return
    change_coins(interaction.guild_id, interaction.user.id, -amount)
    change_coins(interaction.guild_id, member.id, amount)
    await interaction.response.send_message(f"💸 Sent **{amount}** {guild_emoji(interaction.guild, 'coin', COIN)} to {member.mention}!")


@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Why they are being kicked")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await require_mod(interaction, 'kick_members'): return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("You can't kick someone with an equal or higher role.", ephemeral=True); return
    try:
        await member.kick(reason=f"{reason} | By {interaction.user}")
        await interaction.response.send_message(f"👢 Kicked **{member}**. Reason: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("I can't kick that member. Check my role and permissions.", ephemeral=True)


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Why they are being banned")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await require_mod(interaction, 'ban_members'): return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("You can't ban someone with an equal or higher role.", ephemeral=True); return
    try:
        await member.ban(reason=f"{reason} | By {interaction.user}")
        await interaction.response.send_message(f"🔨 Banned **{member}**. Reason: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("I can't ban that member. Check my role and permissions.", ephemeral=True)


@bot.tree.command(name="timeout", description="Timeout a member for up to 28 days")
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes", reason="Why they are being timed out")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
    if not await require_mod(interaction, 'moderate_members'): return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("You can't timeout someone with an equal or higher role.", ephemeral=True); return
    try:
        await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | By {interaction.user}")
        await interaction.response.send_message(f"🔇 Timed out **{member}** for **{minutes} minutes**. Reason: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("I can't timeout that member. Check my role and permissions.", ephemeral=True)


@bot.tree.command(name="clear", description="Delete up to 100 recent messages")
@app_commands.describe(amount="Number of messages to delete (1–100)")
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    if not await require_mod(interaction, 'manage_messages'): return
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("Use this in a text channel.", ephemeral=True); return
    try:
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Cleared **{len(deleted)}** messages.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I need Manage Messages permission here.", ephemeral=True)


@bot.tree.command(name="warn", description="Give a member a recorded warning")
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not await require_mod(interaction, 'manage_messages'): return
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose a different member.", ephemeral=True); return
    with db() as conn:
        conn.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)", (interaction.guild_id, member.id, interaction.user.id, reason, int(time.time())))
        count = conn.execute("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild_id, member.id)).fetchone()["n"]
    await interaction.response.send_message(f"⚠️ Warned {member.mention}. They now have **{count}** warning(s). Reason: {reason}")


@bot.tree.command(name="warnings", description="View a member's warning history")
@app_commands.describe(member="Member whose warnings to view")
async def warnings(interaction: discord.Interaction, member: discord.Member):
    if not await require_mod(interaction, 'manage_messages'): return
    with db() as conn:
        rows = conn.execute("SELECT moderator_id,reason,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10", (interaction.guild_id, member.id)).fetchall()
    lines = [f"<t:{r['created_at']}:d> — {r['reason']} (by <@{r['moderator_id']}>)" for r in rows]
    await interaction.response.send_message(embed=embed(f"⚠️ Warnings for {member}", "\n".join(lines) or "No warnings found."), ephemeral=True)


if __name__ == "__main__":
    init_db()
    bot.run(TOKEN)








