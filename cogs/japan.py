import asyncio
import random
import ssl
import aiohttp
import certifi
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

import discord
from discord.ext import commands

# -----------------------------
# Paths / Data
# -----------------------------
DATA_DIR = "data"
JOKES_BASE_PATH = os.path.join(DATA_DIR, "jokes_japan.json")
JOKES_EXTRA_PATH = os.path.join(DATA_DIR, "jokes_japan_extra.json")

def _ensure_data_dir():
    if os.path.exists(DATA_DIR) and not os.path.isdir(DATA_DIR):
        raise RuntimeError(f"'{DATA_DIR}' exists but is not a folder.")
    os.makedirs(DATA_DIR, exist_ok=True)

def _safe_load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            return json.loads(raw) if raw else {}
    except Exception:
        return {}

def _merge_jokes(base: dict, extra: dict) -> dict:
    """
    Merge dicts like:
      {"anime": ["..."], "dad": ["..."]}
    Combine lists, remove obvious duplicates (exact-match).
    """
    out: Dict[str, List[str]] = {}

    for src in (base, extra):
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, list):
                continue
            out.setdefault(k, [])
            for item in v:
                if isinstance(item, str):
                    out[k].append(item.strip())

    # de-dupe exact matches per category
    for k in list(out.keys()):
        seen = set()
        deduped = []
        for j in out[k]:
            if not j:
                continue
            if j in seen:
                continue
            seen.add(j)
            deduped.append(j)
        out[k] = deduped

    return out


# -----------------------------
# Wikimedia "On this day" API
# -----------------------------
WIKI_ONTHISDAY = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{mm:02d}/{dd:02d}"
HTTP_HEADERS = {"User-Agent": "TomoniMusicBot/1.0 (Discord bot; learning project)"}

async def fetch_json(url: str) -> dict:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    last_err = None
    for attempt in range(1, 4):
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(headers=HTTP_HEADERS, timeout=timeout) as session:
                async with session.get(url, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
                    return await resp.json()
        except Exception as e:
            last_err = e
            await asyncio.sleep(1.0 * attempt)
    raise last_err

def pick_japanish_event(items: list) -> Optional[str]:
    keywords = ("Japan", "Japanese", "Tokyo", "Kyoto", "Osaka", "Hokkaido", "Okinawa", "shogun", "samurai")
    candidates = []
    for it in items:
        text = (it.get("text") or "").strip()
        year = it.get("year")
        if text and any(k.lower() in text.lower() for k in keywords):
            candidates.append((year, text))
    if not candidates:
        return None
    year, text = random.choice(candidates)
    return f"📅 On this day ({year}): {text}"

async def get_on_this_day_japan() -> str:
    tokyo_now = datetime.now(ZoneInfo("Asia/Tokyo"))
    url = WIKI_ONTHISDAY.format(mm=tokyo_now.month, dd=tokyo_now.day)
    data = await fetch_json(url)
    events = data.get("events", [])
    picked = pick_japanish_event(events)
    return picked or "📅 On this day: No Japan-keyword match today. Try again tomorrow!"


# -----------------------------
# JP Trivia (static)
# -----------------------------
JP_TRIVIA_BANK = [
    "Japan’s first permanent capital is often associated with Nara (Heijō-kyō), established in the 8th century.",
    "Kyoto served as Japan’s imperial capital for over a thousand years (from 794).",
    "The Tale of Genji (early 11th century) is often called one of the world’s earliest novels.",
    "The title 'shōgun' became the center of political power for long periods of Japanese history.",
    "Castle towns grew around major fortresses and shaped many modern Japanese cities.",
    "Edo (now Tokyo) became one of the world’s largest cities during the Edo period.",
    "Kabuki theater developed in the early 1600s and became a major form of popular entertainment.",
    "Japan’s high-speed rail (Shinkansen) began service in 1964.",
]


# -----------------------------
# Joke system: shuffle-bag (prevents repeats)
# -----------------------------
DEFAULT_JOKES = {
    "anime": [
        "😂 Why did the anime character bring a ladder?\n➡️ To reach the next arc.",
        "😂 Why did the shounen hero refuse to skip leg day?\n➡️ Because the power-up always starts in the lower body.",
        "😂 Why do anime protagonists love bread?\n➡️ Because it’s the easiest “budget animation” snack.",
        "😂 Why did the anime villain start a podcast?\n➡️ He needed a monologue outlet.",
    ],
    "dad": [
        "😂 I tried to catch fog yesterday.\n➡️ Mist.",
        "😂 I used to hate facial hair.\n➡️ But then it grew on me.",
    ],
    "dajare": [
        "😂 Why did the sushi chef blush?\n➡️ Because he saw the wasabi!",
    ],
    "jp_dajare": [
        "😂 Why don’t chopsticks ever get lost?\n➡️ Because they always come in a pair. (hashi = chopsticks)",
    ],
    "everyday_jp": [
        "😂 Japanese convenience stores are so strong...\n➡️ even your diet loses to seasonal snacks.",
    ],
    "manzai": [
        "😂 (Boke) I’m a ninja.\n➡️ (Tsukkomi) Then why are you announcing it?!",
    ],
}

MOODS = {
    # mood -> weighted category list (repeats = higher chance)
    "punny": ["dad", "dad", "dajare", "jp_dajare"],
    "anime_vibes": ["anime", "anime", "anime", "everyday_jp"],
    "everyday": ["everyday_jp", "everyday_jp", "anime"],
    "manzai": ["manzai", "manzai", "anime"],
}

@dataclass
class JokeShuffleBag:
    # category -> shuffled queue of jokes
    bag: Dict[str, List[str]] = field(default_factory=dict)

    def next(self, category: str, library: Dict[str, List[str]]) -> str:
        jokes = library.get(category, [])
        if not jokes:
            return "😅 I don’t have jokes for that category yet."

        # (Re)fill if empty or if bag has stale jokes count mismatched
        cur = self.bag.get(category, [])
        if not cur:
            cur = jokes.copy()
            random.shuffle(cur)
            self.bag[category] = cur

        # Pop one
        return self.bag[category].pop()

class JapanCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.jokes_lock = asyncio.Lock()
        self.joke_library: Dict[str, List[str]] = {}
        self.shuffle = JokeShuffleBag()

        self.reload_jokes()

    # ------------- joke loading -------------
    def reload_jokes(self):
        _ensure_data_dir()
        base = _safe_load_json(JOKES_BASE_PATH)
        extra = _safe_load_json(JOKES_EXTRA_PATH)

        merged = _merge_jokes(base, extra)

        # ensure defaults exist (and fill missing categories)
        for k, v in DEFAULT_JOKES.items():
            merged.setdefault(k, [])
            merged[k].extend(v)

        # de-dupe again after adding defaults
        merged = _merge_jokes(merged, {})

        self.joke_library = merged

        # Reset shuffle bags so new content gets used immediately
        self.shuffle = JokeShuffleBag()

    def _all_categories(self) -> List[str]:
        cats = sorted(self.joke_library.keys())
        return ["random"] + cats

    def _pick_category_from_mood(self, mood: str) -> Optional[str]:
        mood = (mood or "").strip().lower()
        if mood not in MOODS:
            return None
        pool = MOODS[mood]
        # only pick categories that actually exist
        valid = [c for c in pool if c in self.joke_library and self.joke_library[c]]
        if not valid:
            return None
        return random.choice(valid)

    async def _send_joke(self, ctx: commands.Context, category: Optional[str], mood: Optional[str]):
        category = (category or "").strip().lower()
        mood = (mood or "").strip().lower()

        # mood overrides category if provided
        if mood:
            picked = self._pick_category_from_mood(mood)
            if not picked:
                return await ctx.reply("😅 Unknown mood. Try `!jokemoods` or `/jokemoods`.")
            category = picked

        if not category or category == "random":
            # random category
            options = [k for k, v in self.joke_library.items() if v]
            if not options:
                return await ctx.reply("😅 No jokes loaded.")
            category = random.choice(options)

        if category not in self.joke_library or not self.joke_library[category]:
            return await ctx.reply("😅 Unknown category. Try `!jokecategories` or `/jokecategories`.")

        # shuffle-bag next (prevents repeats)
        async with self.jokes_lock:
            joke = self.shuffle.next(category, self.joke_library)

        await ctx.reply(joke)

    # ------------- commands -------------
    @commands.hybrid_command(name="jptrivia", description="Get a random Japan trivia fact.")
    async def jptrivia(self, ctx: commands.Context):
        await ctx.reply(f"🇯🇵 Trivia: {random.choice(JP_TRIVIA_BANK)}")

    @commands.hybrid_command(name="jponthisday", description="Japan-related 'On This Day' event (Tokyo date).")
    async def jponthisday(self, ctx: commands.Context):
        try:
            msg = await get_on_this_day_japan()
            await ctx.reply(msg)
        except Exception as e:
            await ctx.reply("📅 On this day: I couldn't reach the trivia source right now—try again later.")
            print("jponthisday error:", repr(e))

    @commands.hybrid_command(
        name="joke",
        description="Tell a Japan-themed joke (category or mood).",
    )
    async def joke(
        self,
        ctx: commands.Context,
        category: Optional[str] = None,
        mood: Optional[str] = None,
    ):
        """
        Usage:
          /joke category:<cat>
          /joke mood:<mood>
          !joke
          !joke anime
          !joke mood punny    (optional style if you want; see below)
        """
        # Allow prefix style: "!joke mood punny"
        # If category == "mood" and mood is None, treat "category" as mood selector.
        if category and category.lower() == "mood" and not mood:
            return await ctx.reply("Use `!joke mood <mood>` like: `!joke mood punny`")

        await self._send_joke(ctx, category=category, mood=mood)

    @joke.autocomplete("category")
    async def joke_category_autocomplete(self, interaction: discord.Interaction, current: str):
        current = (current or "").lower()
        opts = [c for c in self._all_categories() if current in c.lower()]
        return [discord.app_commands.Choice(name=o, value=o) for o in opts[:25]]

    @joke.autocomplete("mood")
    async def joke_mood_autocomplete(self, interaction: discord.Interaction, current: str):
        current = (current or "").lower()
        opts = [m for m in sorted(MOODS.keys()) if current in m.lower()]
        return [discord.app_commands.Choice(name=o, value=o) for o in opts[:25]]

    @commands.hybrid_command(name="jokecategories", description="List all joke categories.")
    async def jokecategories(self, ctx: commands.Context):
        cats = sorted([k for k, v in self.joke_library.items() if v])
        if not cats:
            return await ctx.reply("No joke categories loaded.")
        await ctx.reply("🗂️ Joke categories:\n" + ", ".join(f"`{c}`" for c in cats))

    @commands.hybrid_command(name="jokemoods", description="List all joke moods.")
    async def jokemoods(self, ctx: commands.Context):
        moods = sorted(MOODS.keys())
        await ctx.reply("🎭 Joke moods:\n" + ", ".join(f"`{m}`" for m in moods))

    @commands.hybrid_command(name="jokeload", description="(Admin) Reload jokes from JSON files.")
    @commands.has_permissions(manage_guild=True)
    async def jokeload(self, ctx: commands.Context):
        self.reload_jokes()
        await ctx.reply("✅ Reloaded joke libraries and reset shuffle rotation.")


async def setup(bot: commands.Bot):
    await bot.add_cog(JapanCog(bot))
