import discord
from discord.ext import commands

# Discord embed limits (safe guards)
FIELD_VALUE_LIMIT = 1024
FIELD_NAME_LIMIT = 256
EMBED_DESC_LIMIT = 4096


def _chunks(text: str, limit: int):
    """Split text into chunks under `limit` chars, preferring newline breaks."""
    if len(text) <= limit:
        return [text]
    out = []
    cur = ""
    for line in text.split("\n"):
        # +1 for newline
        if len(cur) + len(line) + 1 > limit:
            out.append(cur.rstrip("\n"))
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur.rstrip("\n"))
    return out


def _add_field_safe(embed: discord.Embed, name: str, value: str, inline: bool = False):
    """Add field(s) safely, splitting value if too long."""
    name = (name or "Info")[:FIELD_NAME_LIMIT]
    parts = _chunks(value, FIELD_VALUE_LIMIT)
    for i, part in enumerate(parts):
        field_name = name if i == 0 else f"{name} (cont.)"
        embed.add_field(name=field_name[:FIELD_NAME_LIMIT], value=part, inline=inline)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------
    # MAIN HELP
    # -------------------------
    @commands.hybrid_command(
        name="help",
        description="Show command guide (all or by category: music/games/japan).",
    )
    async def help(self, ctx: commands.Context, category: str = None):
        """
        Usage:
          /help
          /help music
          /help games
          /help japan

          !help
          !help music
        """
        cat = (category or "").strip().lower()

        embed = discord.Embed(
            title="Tomoni DeeJay — Command Guide",
            description=(
                "Use **slash commands** (`/command`) **or** **prefix commands** (`!command`).\n"
                "Type `/help music`, `/help games`, or `/help japan` for a focused list.\n\n"
                "Tip: For mini-games, you can usually answer using either `!` or `/` versions."
            )[:EMBED_DESC_LIMIT],
        )

        if cat in ("", None):
            self._add_music(embed)
            self._add_japan(embed)
            self._add_games(embed)
            self._add_points(embed)
        elif cat == "music":
            self._add_music(embed, focused=True)
        elif cat == "japan":
            self._add_japan(embed, focused=True)
        elif cat == "games":
            self._add_games(embed, focused=True)
            self._add_points(embed, focused=True)
        else:
            embed.description = (
                "Unknown category. Use: `music`, `games`, or `japan`.\n"
                "Example: `/help japan` or `!help japan`"
            )[:EMBED_DESC_LIMIT]

        await ctx.reply(embed=embed)

    # -------------------------
    # SECTIONS
    # -------------------------
    def _add_music(self, embed: discord.Embed, focused: bool = False):
        header = "🎵 Music"
        lines = [
            "`/join` or `!join` — Join your voice channel",
            "`/play <song or url>` or `!play <song or url>` — Play now (or add to queue, if enabled)",
            "`/queue` or `!queue` — Show queue",
            "`/skip` or `!skip` — Skip current track",
            "`/stop` or `!stop` — Stop playback (keeps queue)",
            "`/pause` or `!pause` — Pause",
            "`/resume` or `!resume` — Resume",
            "`/np` or `!np` — Now playing",
            "`/seek <SS|MM:SS|HH:MM:SS>` or `!seek <time>` — Seek to time",
            "`/rewind <time>` / `!rewind <time>` — Jump back",
            "`/forward <time>` / `!forward <time>` — Jump forward",
            "`/remove <pos>` / `!remove <pos>` — Remove a queued track (1 = next)",
            "`/shuffle` or `!shuffle` — Shuffle queue",
            "`/clear` or `!clear` — Clear queue",
            "`/loop` or `!loop` — Toggle loop current track",
            "`/randomsong [1-10]` or `!randomsong [1-10]` — Queue a random mix",
            "`/leave` or `!leave` — Disconnect and clear queue",
        ]
        _add_field_safe(embed, header, "\n".join(lines), inline=False)

        if focused:
            embed.set_footer(text="Tip: music commands work best inside a server voice channel.")

    def _add_japan(self, embed: discord.Embed, focused: bool = False):
        header = "🇯🇵 Japan"
        lines = [
            "`/jptrivia` or `!jptrivia` — Random Japan trivia fact",
            "`/jponthisday` or `!jponthisday` — Japan-related “On This Day” event (Tokyo date)",
            "",
            "**Jokes:**",
            "`/joke` or `!joke` — Random joke from any category",
            "`/joke category:<name>` or `!joke <category>` — Joke from a specific category",
            "`/joke mood:<name>` — Joke from a mood (moods pick categories with weights)",
            "`/jokecategories` or `!jokecategories` — Show available joke categories",
            "`/jokemoods` or `!jokemoods` — Show available joke moods",
            "",
            "**How `/joke` works:**",
            "• The bot uses a **shuffle-bag** per category (no repeats until it cycles through all jokes).",
            "• `category` pulls jokes from one exact category (example: `anime`, `dajare`, `manzai`).",
            "• `mood` picks from a weighted pool of categories (example: `anime_vibes`, `punny`).",
            "• If you provide neither, it chooses **random category** and serves the next joke.",
        ]
        _add_field_safe(embed, header, "\n".join(lines), inline=False)

        if focused:
            embed.set_footer(text="Tip: Try `/joke mood:punny` or `!joke anime`.")

    def _add_games(self, embed: discord.Embed, focused: bool = False):
        header = "🎮 Games"
        lines = [
            "**Samurai Duel (1v1 mind game)**",
            "`/duel @user [bo3]` or `!duel @user [bo3]` — Start a duel (HP duel or best-of-3)",
            "`/duelaccept` / `!duelaccept` — Accept duel",
            "`/dueldecline` / `!dueldecline` — Decline duel",
            "`/duelcancel` / `!duelcancel` — Cancel duel",
            "`/duelmove` / `!duelmove` — Reminder of DM-only moves",
            "DM-only moves: `move strike` / `move guard` / `move feint` (DM the bot)",
            "Timer: 30s per round — no move = forfeit the round",
            "",
            "**Food Emoji Guessing**",
            "`/foodgame [rounds]` or `!foodgame [rounds]` — Start game",
            "`/guess <answer>` or `!guess <answer>` — Guess the food",
            "`/hint` or `!hint` — Get a hint",
            "`/foodstatus` or `!foodstatus` — Show round/time remaining",
            "`/foodstop` or `!foodstop` — Stop game",
            "",
            "**Culture Trivia Battle (first buzz wins)**",
            "`/battle start [n] [seconds]` or `!battle start [n] [seconds]` — Start battle",
            "`/buzz <answer>` or `!buzz <answer>` — Buzz answer (first buzz only)",
            "`/battlestatus` or `!battlestatus` — Show battle status",
            "`/battle stop` or `!battle stop` — Stop battle",
            "Scoring: Correct +2, Wrong -1 (never below 0)",
        ]
        _add_field_safe(embed, header, "\n".join(lines), inline=False)

        if focused:
            embed.set_footer(text="Tip: You can answer games using either slash or prefix commands.")

    def _add_points(self, embed: discord.Embed, focused: bool = False):
        header = "🏆 Points"
        lines = [
            "`/myscore` or `!myscore` — Show your points + rank",
            "`/leaderboard` or `!leaderboard` — Top 10 server scores",
        ]
        _add_field_safe(embed, header, "\n".join(lines), inline=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))

