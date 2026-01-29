import json
import os
import random
from dataclasses import dataclass
from typing import Dict, Optional

from discord.ext import commands


DATA_DIR = "../data_old"
LEADERBOARD_FILE = os.path.join(DATA_DIR, "leaderboards.json")


def ensure_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)


def load_lb() -> dict:
    ensure_storage()
    with open(LEADERBOARD_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_lb(data: dict):
    ensure_storage()
    with open(LEADERBOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def add_points(guild_id: int, user_id: int, amount: int):
    data = load_lb()
    g = data.setdefault(str(guild_id), {})
    g[str(user_id)] = int(g.get(str(user_id), 0)) + int(amount)
    save_lb(data)


def get_top(guild_id: int, limit: int = 10):
    data = load_lb()
    g = data.get(str(guild_id), {})
    items = [(int(uid), int(score)) for uid, score in g.items()]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:limit]


@dataclass
class DuelState:
    p1: int
    p2: int
    active: bool = True


class GamesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.duels: Dict[int, DuelState] = {}  # guild_id -> duel state

    # ✅ Leaderboard command (Phase 5 requirement)
    @commands.command()
    async def leaderboard(self, ctx: commands.Context):
        top = get_top(ctx.guild.id, limit=10)
        if not top:
            return await ctx.send("🧠 Leaderboard is empty (for this server). Win some games first 😈")

        lines = []
        for i, (uid, score) in enumerate(top, start=1):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"User({uid})"
            lines.append(f"**{i}.** {name} — **{score}** pts")

        await ctx.send("🧠 **Server Leaderboard**\n" + "\n".join(lines))

    # ---- Phase 5 games (stubs for now; we fill logic next) ----

    @commands.command()
    async def duel(self, ctx: commands.Context, opponent: Optional[str] = None):
        await ctx.send("🗡️ Duel system placeholder — next step is adding full duel logic + scoring.")

    @commands.command()
    async def foodgame(self, ctx: commands.Context):
        await ctx.send("🍜 Food emoji guessing placeholder — next step is adding question pool + answers + scoring.")

    @commands.command()
    async def culturebattle(self, ctx: commands.Context):
        await ctx.send("🎌 Culture trivia battle placeholder — next step is adding questions + turn system + scoring.")


async def setup(bot: commands.Bot):
    ensure_storage()
    await bot.add_cog(GamesCog(bot))
