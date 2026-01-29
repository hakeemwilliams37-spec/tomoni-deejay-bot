import asyncio
import json
import os
import random
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List

import discord
from discord.ext import commands

PREFIX = "!"
SLASH = "/"


# -----------------------
# Storage (per-server)
# -----------------------
DATA_DIR = "data"
LEADERBOARD_PATH = os.path.join(DATA_DIR, "leaderboards.json")
_lb_lock = asyncio.Lock()


def _ensure_storage():
    if os.path.exists(DATA_DIR) and not os.path.isdir(DATA_DIR):
        raise RuntimeError(f"'{DATA_DIR}' exists but is not a folder. Rename/remove it.")
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(LEADERBOARD_PATH) and os.path.isdir(LEADERBOARD_PATH):
        raise RuntimeError(f"'{LEADERBOARD_PATH}' exists but is a folder. Rename/remove it.")

    if not os.path.exists(LEADERBOARD_PATH):
        with open(LEADERBOARD_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _load_lb() -> dict:
    _ensure_storage()
    try:
        with open(LEADERBOARD_PATH, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            if not raw:
                return {}
            return json.loads(raw)
    except json.JSONDecodeError:
        try:
            ts = time.strftime("%Y%m%d-%H%M%S")
            bad_path = os.path.join(DATA_DIR, f"leaderboards.bad.{ts}.json")
            with open(LEADERBOARD_PATH, "r", encoding="utf-8") as src:
                bad = src.read()
            with open(bad_path, "w", encoding="utf-8") as dst:
                dst.write(bad)
        except Exception:
            pass

        with open(LEADERBOARD_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}


def _save_lb(data: dict):
    _ensure_storage()
    tmp_path = LEADERBOARD_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, LEADERBOARD_PATH)


async def add_points(guild_id: int, user_id: int, pts: int):
    async with _lb_lock:
        data = _load_lb()
        gk = str(guild_id)
        uk = str(user_id)
        if gk not in data:
            data[gk] = {}
        data[gk][uk] = int(data[gk].get(uk, 0)) + int(pts)
        _save_lb(data)


async def get_points(guild_id: int, user_id: int) -> int:
    async with _lb_lock:
        data = _load_lb()
        return int(data.get(str(guild_id), {}).get(str(user_id), 0))


async def top_points(guild_id: int, limit: int = 10) -> List[Tuple[int, int]]:
    async with _lb_lock:
        data = _load_lb()
        g = data.get(str(guild_id), {})
        pairs = [(int(uid), int(score)) for uid, score in g.items()]
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:limit]


# -----------------------
# Rank Titles
# -----------------------
RANKS = [
    (0, "Ashigaru 🪶"),
    (10, "Ronin 🥷"),
    (25, "Samurai ⚔️"),
    (50, "Daimyo 🏯"),
    (100, "Shogun 👑"),
    (200, "Legend 🐉"),
]


def rank_title(points: int) -> str:
    title = RANKS[0][1]
    for threshold, name in RANKS:
        if points >= threshold:
            title = name
        else:
            break
    return title


# -----------------------
# Duel System (DM-only moves)
# -----------------------
DUEL_MOVES = ("strike", "guard", "feint")


def duel_resolve(a_move: str, b_move: str) -> int:
    if a_move == b_move:
        return 0
    beats = {"strike": "feint", "feint": "guard", "guard": "strike"}
    return 1 if beats[a_move] == b_move else 2


@dataclass
class DuelState:
    challenger_id: int
    opponent_id: int
    created_at: float
    channel_id: int

    accepted: bool = False
    active: bool = False

    ch_hp: int = 3
    op_hp: int = 3

    mode: str = "hp"  # "hp" or "bo3"
    ch_wins: int = 0
    op_wins: int = 0
    target_wins: int = 2

    ch_move: Optional[str] = None
    op_move: Optional[str] = None
    round_started_at: float = 0.0

    round_task: Optional[asyncio.Task] = None
    timer_message_id: Optional[int] = None


# -----------------------
# Food Emoji Game
# -----------------------
FOOD_BANK = [
    ("🍣", "sushi"),
    ("🍜", "ramen"),
    ("🍕", "pizza"),
    ("🌮", "taco"),
    ("🍔", "burger"),
    ("🍩", "donut"),
    ("🥞", "pancakes"),
    ("🍛", "curry"),
    ("🍦", "icecream"),
    ("🍙", "onigiri"),
]

FOOD_DEFAULT_ROUNDS = 1
FOOD_DEFAULT_SECONDS = 30
FOOD_GUESS_COOLDOWN = 1.25


@dataclass
class FoodState:
    answer: str
    emoji: str
    started_at: float
    active: bool = True
    rounds_total: int = 1
    round_index: int = 1
    seconds: int = 30
    hints_used: int = 0
    timer_task: Optional[asyncio.Task] = None
    channel_id: int = 0
    last_guess_at: Dict[int, float] = None

    def __post_init__(self):
        if self.last_guess_at is None:
            self.last_guess_at = {}


# -----------------------
# Culture Battle
# -----------------------
CULTURE_Q = [
    ("Japan’s capital city is?", "tokyo"),
    ("Famous Japanese bullet train is called?", "shinkansen"),
    ("Traditional Japanese warrior class is?", "samurai"),
    ("Japanese currency is the?", "yen"),
    ("Famous mountain often seen in art is Mount?", "fuji"),
    ("The traditional Japanese tea ceremony centers on?", "matcha"),
]

CULTURE_DEFAULT_Q = 5
CULTURE_DEFAULT_SECONDS = 20


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    keep = []
    for ch in s:
        if ch.isalnum():
            keep.append(ch)
    return "".join(keep)


@dataclass
class BattleState:
    channel_id: int
    questions_left: List[Tuple[str, str]]

    active: bool = False
    started_by: int = 0

    current_q: Optional[Tuple[str, str]] = None
    asked_at: float = 0.0
    seconds_per_q: int = CULTURE_DEFAULT_SECONDS

    accepting: bool = False
    buzz_winner_id: Optional[int] = None

    timer_task: Optional[asyncio.Task] = None
    timer_message_id: Optional[int] = None


class GamesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.duels: Dict[int, DuelState] = {}
        self.food: Dict[int, FoodState] = {}
        self.battle: Dict[int, BattleState] = {}

    async def _get_channel(self, channel_id: int) -> Optional[discord.abc.Messageable]:
        chan = self.bot.get_channel(channel_id)
        if chan is not None:
            return chan
        try:
            return await self.bot.fetch_channel(channel_id)
        except Exception:
            return None

    async def _announce(self, channel_id: int, text: str):
        chan = await self._get_channel(channel_id)
        if chan is None:
            return
        try:
            await chan.send(text)  # type: ignore
        except Exception:
            pass

    # ---------- duel helpers ----------
    def _duel_expired(self, st: DuelState) -> bool:
        return (time.time() - st.created_at) > 120

    def _strip_move(self, raw: str) -> str:
        m = (raw or "").strip().lower()
        if m.startswith("<") and m.endswith(">") and len(m) >= 3:
            m = m[1:-1].strip().lower()
        return m

    def _cancel_round_timer(self, st: DuelState):
        t = st.round_task
        st.round_task = None
        if t and not t.done():
            t.cancel()

    def _timer_bar(self, elapsed: float, total: float = 30.0, width: int = 12) -> str:
        elapsed = max(0.0, min(elapsed, total))
        filled = int(round((elapsed / total) * width))
        empty = max(0, width - filled)
        return "🕒 [" + ("█" * filled) + ("░" * empty) + "]"

    async def _post_or_edit_timer(self, st: DuelState, text: str):
        chan = await self._get_channel(st.channel_id)
        if chan is None:
            return

        try:
            if st.timer_message_id:
                msg = await chan.fetch_message(st.timer_message_id)  # type: ignore
                await msg.edit(content=text)
                return
        except Exception:
            st.timer_message_id = None

        try:
            msg = await chan.send(text)  # type: ignore
            st.timer_message_id = msg.id
        except Exception:
            pass

    async def _try_dm(self, user: discord.User, text: str) -> bool:
        try:
            await user.send(text)
            return True
        except (discord.Forbidden, Exception):
            return False

    async def _start_round(self, guild_id: int, st: DuelState):
        st.ch_move = None
        st.op_move = None
        st.round_started_at = time.time()

        await self._announce(
            st.channel_id,
            "🕵️ **New round!** DM the bot your move:\n"
            "`move strike` / `move guard` / `move feint` (**30s**)",
        )

        self._cancel_round_timer(st)
        st.round_task = self.bot.loop.create_task(self._round_loop(guild_id, st, total=30, tick=5))

    async def _round_loop(self, guild_id: int, st: DuelState, total: int = 30, tick: int = 5):
        try:
            while True:
                elapsed = time.time() - st.round_started_at
                remaining = int(max(0, total - elapsed))
                bar = self._timer_bar(elapsed, total=float(total), width=12)

                if st.mode == "bo3":
                    status = f"⚔️ BO3: Challenger **{st.ch_wins}** - Opponent **{st.op_wins}** (first to {st.target_wins})"
                else:
                    status = f"❤️ HP: Challenger **{st.ch_hp}** | Opponent **{st.op_hp}**"

                await self._post_or_edit_timer(st, f"{bar} **{remaining}s** left\n{status}")

                if st.ch_move and st.op_move:
                    await self._resolve_round(guild_id, st, forced=False)
                    return

                if elapsed >= total:
                    await self._resolve_round(guild_id, st, forced=True)
                    return

                await asyncio.sleep(tick)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("Round loop error:", repr(e))

    async def _resolve_round(self, guild_id: int, st: DuelState, forced: bool):
        self._cancel_round_timer(st)

        a = st.ch_move
        b = st.op_move

        if forced and (a is None or b is None):
            if a is None and b is None:
                await self._announce(st.channel_id, "⏱️ Time expired — nobody submitted a move. No damage. Next round.")
                await self._start_round(guild_id, st)
                return

            if a is None:
                await self._announce(st.channel_id, "⏱️ Challenger did not submit a move in time — challenger forfeits the round!")
                if st.mode == "bo3":
                    st.op_wins += 1
                else:
                    st.ch_hp -= 1
            else:
                await self._announce(st.channel_id, "⏱️ Opponent did not submit a move in time — opponent forfeits the round!")
                if st.mode == "bo3":
                    st.ch_wins += 1
                else:
                    st.op_hp -= 1

            st.ch_move = None
            st.op_move = None

            if await self._check_duel_end(guild_id, st):
                return

            await self._start_round(guild_id, st)
            return

        if a is None or b is None:
            return

        outcome = duel_resolve(a, b)

        if outcome == 0:
            await self._announce(st.channel_id, f"⚔️ **Reveal:** Challenger **{a}** vs Opponent **{b}** — 🤝 **TIE!**")
        elif outcome == 1:
            await self._announce(st.channel_id, f"⚔️ **Reveal:** Challenger **{a}** beats Opponent **{b}** ✅")
            if st.mode == "bo3":
                st.ch_wins += 1
            else:
                st.op_hp -= 1
        else:
            await self._announce(st.channel_id, f"⚔️ **Reveal:** Opponent **{b}** beats Challenger **{a}** ✅")
            if st.mode == "bo3":
                st.op_wins += 1
            else:
                st.ch_hp -= 1

        st.ch_move = None
        st.op_move = None

        if await self._check_duel_end(guild_id, st):
            return

        await self._start_round(guild_id, st)

    async def _check_duel_end(self, guild_id: int, st: DuelState) -> bool:
        winner_id: Optional[int] = None
        loser_id: Optional[int] = None

        if st.mode == "bo3":
            if st.ch_wins >= st.target_wins:
                winner_id = st.challenger_id
                loser_id = st.opponent_id
            elif st.op_wins >= st.target_wins:
                winner_id = st.opponent_id
                loser_id = st.challenger_id
        else:
            if st.ch_hp <= 0:
                winner_id = st.opponent_id
                loser_id = st.challenger_id
            elif st.op_hp <= 0:
                winner_id = st.challenger_id
                loser_id = st.opponent_id

        if winner_id is None or loser_id is None:
            return False

        self.duels.pop(guild_id, None)
        self._cancel_round_timer(st)

        await add_points(guild_id, winner_id, 3)
        await add_points(guild_id, loser_id, 1)

        await self._announce(
            st.channel_id,
            f"🏆 **Duel Over!** Winner: <@{winner_id}> (+3)\n"
            f"Consolation: <@{loser_id}> (+1)\n"
            f"Check scores: `{SLASH}myscore` / `{PREFIX}myscore` • `{SLASH}leaderboard` / `{PREFIX}leaderboard`"
        )
        return True

    # ---------- DM listener for duel moves ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is not None:
            return  # only DMs

        content = (message.content or "").strip()
        if not content:
            return

        lower = content.lower().strip()
        if lower.startswith("!"):
            lower = lower[1:].strip()

        if lower.startswith("move "):
            raw_move = lower.split(" ", 1)[1]
        elif lower.startswith("duelmove "):
            raw_move = lower.split(" ", 1)[1]
        else:
            return

        move = self._strip_move(raw_move)
        if move not in DUEL_MOVES:
            return await message.channel.send("Invalid move. Use: `move strike`, `move guard`, or `move feint`.")

        found: Optional[Tuple[int, DuelState]] = None
        for gid, st in self.duels.items():
            if st.active and message.author.id in (st.challenger_id, st.opponent_id):
                found = (gid, st)
                break

        if not found:
            return await message.channel.send(f"No active duel found. Start one with `{SLASH}duel` or `{PREFIX}duel`.")

        guild_id, st = found

        if message.author.id == st.challenger_id:
            if st.ch_move is not None:
                return await message.channel.send("You already submitted a move for this round.")
            st.ch_move = move
        else:
            if st.op_move is not None:
                return await message.channel.send("You already submitted a move for this round.")
            st.op_move = move

        await message.channel.send("✅ Move received (hidden).")

        if st.ch_move and st.op_move:
            await self._resolve_round(guild_id, st, forced=False)

    # ---------- HYBRID COMMANDS ----------
    @commands.hybrid_command(name="duel", description="Challenge someone to a duel (HP or BO3).")
    async def duel(self, ctx: commands.Context, opponent: Optional[discord.Member] = None, mode: Optional[str] = None):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        if opponent is None:
            return await ctx.reply(f"🗡️ Usage: `{SLASH}duel @opponent [bo3]` or `{PREFIX}duel @opponent [bo3]`")
        if opponent.bot:
            return await ctx.reply("🗡️ You can’t duel a bot.")
        if opponent.id == ctx.author.id:
            return await ctx.reply("🗡️ You can’t duel yourself.")

        gid = ctx.guild.id
        existing = self.duels.get(gid)
        if existing and (existing.active or not self._duel_expired(existing)):
            return await ctx.reply(f"🗡️ A duel is already pending/active here. Use `{SLASH}duelcancel` / `{PREFIX}duelcancel`.")

        duel_mode = "bo3" if (mode or "").strip().lower() == "bo3" else "hp"

        self.duels[gid] = DuelState(
            challenger_id=ctx.author.id,
            opponent_id=opponent.id,
            created_at=time.time(),
            channel_id=ctx.channel.id,
            accepted=False,
            active=False,
            mode=duel_mode,
            ch_hp=3,
            op_hp=3,
            ch_wins=0,
            op_wins=0,
            target_wins=2,
        )

        label = "Best-of-3" if duel_mode == "bo3" else "HP Duel"
        await ctx.reply(
            f"🗡️ **Duel challenge ({label})!** {ctx.author.mention} vs {opponent.mention}\n"
            f"{opponent.mention} respond with `{SLASH}duelaccept` / `{PREFIX}duelaccept` "
            f"or `{SLASH}dueldecline` / `{PREFIX}dueldecline` (expires in 2 minutes)."
        )

    @commands.hybrid_command(name="duelaccept", description="Accept the pending duel.")
    async def duelaccept(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.duels.get(gid)
        if not st:
            return await ctx.reply("🗡️ No duel is pending.")
        if st.active:
            return await ctx.reply("🗡️ Duel already active. Submit moves by DM: `move strike/guard/feint`.")

        if self._duel_expired(st):
            self.duels.pop(gid, None)
            return await ctx.reply(f"🗡️ That duel expired. Start a new one with `{SLASH}duel` / `{PREFIX}duel`.")
        if ctx.author.id != st.opponent_id:
            return await ctx.reply("🗡️ Only the challenged opponent can accept.")

        st.accepted = True
        st.active = True
        st.ch_hp, st.op_hp = 3, 3
        st.ch_wins, st.op_wins = 0, 0
        st.ch_move, st.op_move = None, None

        challenger = self.bot.get_user(st.challenger_id) or await self.bot.fetch_user(st.challenger_id)
        opponent = self.bot.get_user(st.opponent_id) or await self.bot.fetch_user(st.opponent_id)

        ch_ok = await self._try_dm(challenger, "🗡️ Duel started! DM me: `move strike` / `move guard` / `move feint`.")
        op_ok = await self._try_dm(opponent, "🗡️ Duel started! DM me: `move strike` / `move guard` / `move feint`.")

        warn = ""
        if not ch_ok or not op_ok:
            warn = "\n⚠️ One or both players have DMs closed. Enable DMs for this server (Server → Privacy Settings)."

        label = "Best-of-3 (first to 2 round wins)" if st.mode == "bo3" else "HP Duel (3 HP each)"
        await ctx.reply(
            f"⚔️ **Duel started!** Mode: **{label}**\n"
            "**Moves are DM-only** (no counter-picking).\n"
            "DM the bot: `move strike` / `move guard` / `move feint`.\n"
            "Round reveals when both submit or **30s** passes."
            + warn
        )
        await self._start_round(gid, st)

    @commands.hybrid_command(name="dueldecline", description="Decline the pending duel.")
    async def dueldecline(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.duels.get(gid)
        if not st:
            return await ctx.reply("🗡️ No duel is pending.")
        if ctx.author.id != st.opponent_id:
            return await ctx.reply("🗡️ Only the challenged opponent can decline.")
        self.duels.pop(gid, None)
        await ctx.reply("🗡️ Duel declined.")

    @commands.hybrid_command(name="duelcancel", description="Cancel the duel (participants only).")
    async def duelcancel(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.duels.get(gid)
        if not st:
            return await ctx.reply("🗡️ No duel is pending/active.")
        if ctx.author.id not in (st.challenger_id, st.opponent_id):
            return await ctx.reply("🗡️ Only duel participants can cancel.")
        self.duels.pop(gid, None)
        self._cancel_round_timer(st)
        await ctx.reply("🗡️ Duel canceled.")

    @commands.hybrid_command(name="duelmove", description="Reminder: duel moves are DM-only.")
    async def duelmove(self, ctx: commands.Context):
        await ctx.reply("🕵️ Duel moves are **DM-only**.\nDM the bot: `move strike` / `move guard` / `move feint`")

    # ---------- FOOD ----------
    def _food_hint(self, answer: str, hints_used: int) -> str:
        a = answer.lower().strip()
        if hints_used == 0:
            return f"Hint: starts with **{a[0].upper()}** and has **{len(a)}** letters."
        if hints_used == 1:
            vowels = set("aeiou")
            masked = "".join(ch if ch in vowels else "•" for ch in a)
            return f"Hint: vowels revealed → **{masked}**"
        if hints_used == 2:
            return f"Hint: first 2 letters → **{a[:2].upper()}**"
        return "No more hints 😈"

    def _cancel_food_timer(self, st: FoodState):
        t = st.timer_task
        st.timer_task = None
        if t and not t.done():
            t.cancel()

    async def _food_timeout(self, guild_id: int, st: FoodState):
        try:
            await asyncio.sleep(st.seconds)
        except asyncio.CancelledError:
            return

        cur = self.food.get(guild_id)
        if not cur or cur is not st or not st.active:
            return

        st.active = False
        await self._announce(
            st.channel_id,
            f"⏱️ Time! The answer was **{st.answer}**.\n"
            f"Start again: `{SLASH}foodgame` / `{PREFIX}foodgame`"
        )

        if st.round_index < st.rounds_total:
            await asyncio.sleep(1.0)
            await self._start_next_food_round(
                guild_id,
                st.channel_id,
                rounds_total=st.rounds_total,
                next_round=st.round_index + 1,
                seconds=st.seconds
            )

    async def _start_next_food_round(self, guild_id: int, channel_id: int, rounds_total: int, next_round: int, seconds: int):
        emoji, ans = random.choice(FOOD_BANK)
        st = FoodState(
            answer=ans.lower(),
            emoji=emoji,
            started_at=time.time(),
            active=True,
            rounds_total=rounds_total,
            round_index=next_round,
            seconds=seconds,
            hints_used=0,
            timer_task=None,
            channel_id=channel_id,
        )
        self.food[guild_id] = st

        await self._announce(
            channel_id,
            f"🍜 **Food Emoji Guessing!** (Round {st.round_index}/{st.rounds_total})\n"
            f"Guess the food: **{st.emoji}**\n"
            f"Answer with: `{SLASH}guess <answer>` or `{PREFIX}guess <answer>`\n"
            f"Hint: `{SLASH}hint` / `{PREFIX}hint`  |  Status: `{SLASH}foodstatus` / `{PREFIX}foodstatus`  |  Stop: `{SLASH}foodstop` / `{PREFIX}foodstop`\n"
            f"⏱️ You have **{st.seconds}s**"
        )

        self._cancel_food_timer(st)
        st.timer_task = self.bot.loop.create_task(self._food_timeout(guild_id, st))

    @commands.hybrid_command(name="foodgame", description="Start Food Emoji Guessing (optionally set rounds).")
    async def foodgame(self, ctx: commands.Context, rounds: Optional[int] = None):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        existing = self.food.get(gid)
        if existing and existing.active:
            self._cancel_food_timer(existing)

        rt = FOOD_DEFAULT_ROUNDS if rounds is None else max(1, min(int(rounds), 20))
        await self._start_next_food_round(gid, ctx.channel.id, rounds_total=rt, next_round=1, seconds=FOOD_DEFAULT_SECONDS)
        await ctx.reply("🍜 Game started!")

    @commands.hybrid_command(name="foodstop", description="Stop the active food game.")
    async def foodstop(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.food.get(gid)
        if not st or not st.active:
            return await ctx.reply("🍜 No active food game to stop.")
        st.active = False
        self._cancel_food_timer(st)
        await ctx.reply("🍜 Food game stopped.")

    @commands.hybrid_command(name="foodstatus", description="Show status of current food game.")
    async def foodstatus(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.food.get(gid)
        if not st or not st.active:
            return await ctx.reply(f"🍜 No active food game. Start with `{SLASH}foodgame` / `{PREFIX}foodgame`.")
        elapsed = int(time.time() - st.started_at)
        remaining = max(0, st.seconds - elapsed)
        await ctx.reply(
            f"🍜 Round **{st.round_index}/{st.rounds_total}** | Emoji: **{st.emoji}** | ⏱️ **{remaining}s** left | Hints used: **{st.hints_used}**"
        )

    @commands.hybrid_command(name="hint", description="Get a hint for the food game.")
    async def hint(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.food.get(gid)
        if not st or not st.active:
            return await ctx.reply(f"🍜 No active food game. Start with `{SLASH}foodgame` / `{PREFIX}foodgame`.")

        st.hints_used += 1
        msg = self._food_hint(st.answer, st.hints_used - 1)
        await ctx.reply(f"🍜 {msg}")

    @commands.hybrid_command(name="guess", description="Guess the food emoji answer.")
    async def guess(self, ctx: commands.Context, *, answer: Optional[str] = None):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.food.get(gid)
        if not st or not st.active:
            return await ctx.reply(f"🍜 No food game active. Start with `{SLASH}foodgame` / `{PREFIX}foodgame`.")

        if not answer:
            return await ctx.reply(f"🍜 Usage: `{SLASH}guess <answer>` or `{PREFIX}guess <answer>`")

        now = time.time()
        last = st.last_guess_at.get(ctx.author.id, 0.0)
        if (now - last) < FOOD_GUESS_COOLDOWN:
            return
        st.last_guess_at[ctx.author.id] = now

        ans = answer.strip().lower()
        if ans == st.answer:
            st.active = False
            self._cancel_food_timer(st)

            elapsed = max(1, int(now - st.started_at))
            speed_bonus = 1 if elapsed <= 10 else 0
            hint_penalty = min(st.hints_used, 2)
            pts = max(1, 2 + speed_bonus - hint_penalty)

            await add_points(gid, ctx.author.id, pts)
            await ctx.reply(f"✅ Correct! It was **{st.answer}**. {ctx.author.mention} gains **+{pts}** points!")

            if st.round_index < st.rounds_total:
                await asyncio.sleep(1.0)
                await self._start_next_food_round(
                    gid,
                    st.channel_id,
                    rounds_total=st.rounds_total,
                    next_round=st.round_index + 1,
                    seconds=st.seconds,
                )
            return

        await ctx.reply("❌ Nope — try again!")

    # ---------- BATTLE ----------
    def _cancel_battle_timer(self, st: BattleState):
        t = st.timer_task
        st.timer_task = None
        if t and not t.done():
            t.cancel()

    async def _post_or_edit_battle_timer(self, st: BattleState, text: str):
        chan = await self._get_channel(st.channel_id)
        if chan is None:
            return
        try:
            if st.timer_message_id:
                msg = await chan.fetch_message(st.timer_message_id)  # type: ignore
                await msg.edit(content=text)
                return
        except Exception:
            st.timer_message_id = None

        try:
            msg = await chan.send(text)  # type: ignore
            st.timer_message_id = msg.id
        except Exception:
            pass

    async def _battle_timer_loop(self, guild_id: int, st: BattleState):
        tick = 5
        total = st.seconds_per_q
        try:
            while True:
                if not st.active or not st.current_q:
                    return

                elapsed = time.time() - st.asked_at
                remaining = int(max(0, total - elapsed))

                bar = self._timer_bar(elapsed, total=float(total), width=12)
                qn_left = (1 if st.current_q else 0) + len(st.questions_left)

                await self._post_or_edit_battle_timer(
                    st,
                    f"{bar} **{remaining}s** left | Questions remaining: **{qn_left}**\n"
                    f"Answer with `{SLASH}buzz <answer>` or `{PREFIX}buzz <answer>` (first buzz only)"
                )

                if elapsed >= total:
                    await self._battle_timeout(guild_id, st)
                    return

                await asyncio.sleep(tick)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("Battle timer error:", repr(e))

    async def _battle_timeout(self, guild_id: int, st: BattleState):
        if not st.active or not st.current_q:
            return

        _, ans = st.current_q
        st.accepting = False
        st.buzz_winner_id = None

        await self._announce(st.channel_id, f"⏱️ Time! The answer was **{ans}**.")
        await asyncio.sleep(1.0)
        await self._ask_next_question(guild_id)

    async def _ask_next_question(self, guild_id: int):
        st = self.battle.get(guild_id)
        if not st or not st.active:
            return

        self._cancel_battle_timer(st)

        if not st.questions_left:
            st.active = False
            st.current_q = None
            st.accepting = False
            st.buzz_winner_id = None
            await self._announce(st.channel_id, f"🏁 **Battle finished!** Check `{SLASH}leaderboard` / `{PREFIX}leaderboard`")
            return

        st.current_q = st.questions_left.pop(0)
        st.asked_at = time.time()
        st.accepting = True
        st.buzz_winner_id = None

        qtext, _ = st.current_q
        await self._announce(
            st.channel_id,
            f"🎌 **Question:** {qtext}\n"
            f"Answer with `{SLASH}buzz <answer>` or `{PREFIX}buzz <answer>` (**first buzz only**, {st.seconds_per_q}s)"
        )

        st.timer_task = self.bot.loop.create_task(self._battle_timer_loop(guild_id, st))

    @commands.hybrid_command(name="battle", description="Start/stop Culture Trivia Battle.")
    async def battle_cmd(self, ctx: commands.Context, action: Optional[str] = None, n: Optional[int] = None, seconds: Optional[int] = None):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        action = (action or "").lower().strip()

        if action not in ("start", "stop"):
            return await ctx.reply(f"🏮 Usage: `{SLASH}battle start [n] [seconds]` or `{PREFIX}battle start [n] [seconds]` • stop: `{SLASH}battle stop` / `{PREFIX}battle stop`")

        if action == "stop":
            st = self.battle.get(gid)
            if not st or not st.active:
                return await ctx.reply("🏮 No active battle to stop.")
            st.active = False
            self._cancel_battle_timer(st)
            await ctx.reply("🛑 Battle stopped.")
            return

        total_q = CULTURE_DEFAULT_Q if n is None else max(1, min(int(n), 50))
        sec = CULTURE_DEFAULT_SECONDS if seconds is None else max(8, min(int(seconds), 60))

        qpool = CULTURE_Q.copy()
        random.shuffle(qpool)
        chosen = qpool[: min(total_q, len(qpool))]

        self.battle[gid] = BattleState(
            channel_id=ctx.channel.id,
            questions_left=chosen,
            current_q=None,
            active=True,
            started_by=ctx.author.id,
            asked_at=0.0,
            seconds_per_q=sec,
            accepting=False,
            buzz_winner_id=None,
            timer_task=None,
            timer_message_id=None,
        )

        await ctx.reply(
            f"🏮 **Culture Trivia Battle started!** ({len(chosen)} questions)\n"
            f"Rules: first person to `{SLASH}buzz` or `{PREFIX}buzz` gets checked. Correct = **+2**. Wrong = **-1** (min 0).\n"
            f"Time per question: **{sec}s**"
        )
        await self._ask_next_question(gid)

    @commands.hybrid_command(name="buzz", description="Buzz an answer for the culture battle.")
    async def buzz(self, ctx: commands.Context, *, answer: Optional[str] = None):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.battle.get(gid)
        if not st or not st.active or not st.current_q:
            return await ctx.reply(f"🏮 No active battle. Start with `{SLASH}battle start` / `{PREFIX}battle start`.")
        if ctx.channel.id != st.channel_id:
            return
        if not answer:
            return await ctx.reply(f"🏮 Usage: `{SLASH}buzz <answer>` or `{PREFIX}buzz <answer>`")

        if not st.accepting:
            return

        st.accepting = False
        st.buzz_winner_id = ctx.author.id

        _, correct_raw = st.current_q
        correct = _norm(correct_raw)
        guess = _norm(answer)

        if guess == correct:
            await add_points(gid, ctx.author.id, 2)
            await ctx.reply(f"✅ **Correct!** {ctx.author.mention} gains **+2** points!")
            await asyncio.sleep(1.0)
            await self._ask_next_question(gid)
            return

        cur_pts = await get_points(gid, ctx.author.id)
        new_pts = max(0, cur_pts - 1)
        async with _lb_lock:
            data = _load_lb()
            gk = str(gid)
            uk = str(ctx.author.id)
            if gk not in data:
                data[gk] = {}
            data[gk][uk] = new_pts
            _save_lb(data)

        await ctx.reply(f"❌ **Wrong!** {ctx.author.mention} loses **-1** point. Correct answer was **{correct_raw}**.")
        await asyncio.sleep(1.0)
        await self._ask_next_question(gid)

    @commands.hybrid_command(name="battlestatus", description="Show battle status.")
    async def battlestatus(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        gid = ctx.guild.id
        st = self.battle.get(gid)
        if not st or not st.active:
            return await ctx.reply(f"🏮 No active battle. Start with `{SLASH}battle start` / `{PREFIX}battle start`.")
        remaining_q = (1 if st.current_q else 0) + len(st.questions_left)
        elapsed = int(time.time() - st.asked_at) if st.current_q else 0
        remaining = max(0, st.seconds_per_q - elapsed)
        await ctx.reply(f"🏮 Battle active | Questions remaining: **{remaining_q}** | ⏱️ **{remaining}s** left.")

    # ---------- Scores ----------
    @commands.hybrid_command(name="myscore", description="Show your points and rank.")
    async def myscore(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        pts = await get_points(ctx.guild.id, ctx.author.id)
        await ctx.reply(f"🧠 {ctx.author.mention} score: **{pts}** pts — **{rank_title(pts)}**")

    @commands.hybrid_command(name="leaderboard", description="Show the top server scores.")
    async def leaderboard(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.reply("Use this in a server, not DMs.")
        top = await top_points(ctx.guild.id, limit=10)
        if not top:
            return await ctx.reply("🧠 Leaderboard is empty for this server. Win some games first 😈")

        lines = []
        for i, (uid, score) in enumerate(top, start=1):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"User({uid})"
            lines.append(f"**{i}.** {name} — **{score}** pts — {rank_title(score)}")

        await ctx.reply("🧠 **Server Leaderboard**\n" + "\n".join(lines))


async def setup(bot: commands.Bot):
    _ensure_storage()
    await bot.add_cog(GamesCog(bot))




