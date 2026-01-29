import asyncio
import time
import random
from dataclasses import dataclass
from typing import Dict, Union, Optional

import discord
from discord.ext import commands
import yt_dlp


# ---------------- yt-dlp + ffmpeg settings ----------------

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    # Improves extraction reliability when YouTube changes stuff
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    },
}

RECONNECT_OPTS = "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTS = "-vn"


# ---------------- Random music queries (broad) ----------------

RANDOM_QUERIES = [
    "top hits mix", "pop mix", "new music mix", "chart hits playlist",
    "hip hop mix", "rap hits mix", "boom bap mix", "trap mix",
    "rock classics mix", "alternative rock mix", "metal mix", "punk rock mix",
    "edm mix", "house mix", "techno mix", "drum and bass mix", "trance mix",
    "r&b mix", "neo soul mix", "funk mix",
    "jazz mix", "smooth jazz", "blues mix",
    "classical music", "piano instrumental", "orchestral music",
    "country mix", "folk acoustic mix",
    "latin hits mix", "reggaeton mix",
    "reggae mix", "afrobeats mix",
    "k-pop mix", "j-pop mix",
    "lofi hip hop", "chill mix", "study music", "ambient music", "synthwave mix",
    "video game soundtrack mix", "anime openings mix", "movie soundtrack mix",
    "80s hits mix", "90s hits mix", "2000s hits mix",
]


# ---------------- Helpers ----------------

def parse_time(value: Union[str, float, int]) -> float:
    """Accept SS, MM:SS, HH:MM:SS."""
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        raise ValueError("Empty time value.")
    if s.replace(".", "", 1).isdigit():
        return float(s)

    parts = s.split(":")
    if not all(p.strip().isdigit() for p in parts):
        raise ValueError("Invalid time format. Use SS, MM:SS, or HH:MM:SS.")

    nums = [int(p) for p in parts]
    if len(nums) == 2:
        mm, ss = nums
        return mm * 60 + ss
    if len(nums) == 3:
        hh, mm, ss = nums
        return hh * 3600 + mm * 60 + ss

    raise ValueError("Invalid time format. Use SS, MM:SS, or HH:MM:SS.")


@dataclass
class TrackState:
    audio_url: str
    title: str
    base_offset: float = 0.0
    started_at: float = 0.0
    paused: bool = False
    paused_pos: float = 0.0

    def position(self) -> float:
        if self.paused:
            return self.paused_pos
        return self.base_offset + (time.perf_counter() - self.started_at)


def extract_info(query: str) -> dict:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info and info["entries"]:
            info = info["entries"][0]
        return info


def make_source(audio_url: str, seek_seconds: float = 0.0) -> discord.FFmpegPCMAudio:
    seek_seconds = max(0.0, float(seek_seconds))
    before = f"-ss {seek_seconds} {RECONNECT_OPTS}".strip()
    return discord.FFmpegPCMAudio(audio_url, before_options=before, options=FFMPEG_OPTS)


# ---------------- Cog ----------------

class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.state: Dict[int, TrackState] = {}
        self.idle_tasks: Dict[int, asyncio.Task] = {}

    async def maybe_defer(self, ctx: commands.Context, *, thinking: bool = True):
        """Prevents 'application did not respond' on slash commands."""
        inter = getattr(ctx, "interaction", None)
        if inter and not inter.response.is_done():
            try:
                await inter.response.defer(thinking=thinking)
            except Exception:
                pass

    async def safe_send(self, ctx: commands.Context, content: str):
        """Works for both prefix and slash (after defer)."""
        try:
            return await ctx.send(content)
        except Exception:
            # If ctx.send fails for some reason, try interaction followup
            inter = getattr(ctx, "interaction", None)
            if inter:
                try:
                    return await inter.followup.send(content)
                except Exception:
                    return None
            return None

    async def ensure_connected(self, ctx: commands.Context) -> discord.VoiceClient:
        if not ctx.guild:
            raise commands.CommandError("Use this in a server, not DMs.")

        if ctx.voice_client and ctx.voice_client.is_connected():
            return ctx.voice_client

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError("Join a voice channel first.")

        # Voice connect can be slow — don't let slash command timeout
        return await ctx.author.voice.channel.connect()

    def cancel_idle(self, guild_id: int):
        t = self.idle_tasks.pop(guild_id, None)
        if t and not t.done():
            t.cancel()

    def reset_state(self, guild_id: int):
        self.cancel_idle(guild_id)
        self.state.pop(guild_id, None)

    def schedule_idle_disconnect(self, guild_id: int, vc: discord.VoiceClient, timeout: int = 120):
        self.cancel_idle(guild_id)

        async def _idle():
            try:
                await asyncio.sleep(timeout)
                if vc and vc.is_connected() and (not vc.is_playing()) and (not vc.is_paused()):
                    await vc.disconnect()
                    self.reset_state(guild_id)
            except asyncio.CancelledError:
                return
            except Exception as e:
                print("idle_disconnect error:", repr(e))

        self.idle_tasks[guild_id] = asyncio.create_task(_idle())

    def _after_play(self, ctx: commands.Context, source: Optional[discord.AudioSource], error: Optional[Exception]):
        def _safe():
            if error:
                print("Player error:", repr(error))

            if source and hasattr(source, "cleanup"):
                try:
                    source.cleanup()
                except Exception:
                    pass

            vc = ctx.voice_client
            if vc and vc.is_connected() and ctx.guild:
                self.schedule_idle_disconnect(ctx.guild.id, vc, timeout=120)

        try:
            self.bot.loop.call_soon_threadsafe(_safe)
        except Exception:
            try:
                asyncio.get_event_loop().call_soon_threadsafe(_safe)
            except Exception:
                pass

    async def do_seek(self, ctx: commands.Context, new_pos: float):
        vc = ctx.voice_client
        st = self.state.get(ctx.guild.id) if ctx.guild else None
        if not vc or not st or (not vc.is_playing() and not vc.is_paused()):
            return await self.safe_send(ctx, "Nothing is playing to seek.")

        new_pos = max(0.0, float(new_pos))
        self.cancel_idle(ctx.guild.id)

        vc.stop()
        source = make_source(st.audio_url, seek_seconds=new_pos)
        vc.play(source, after=lambda e: self._after_play(ctx, source, e))

        st.base_offset = new_pos
        st.started_at = time.perf_counter()
        st.paused = False
        st.paused_pos = 0.0

        await self.safe_send(ctx, f"⏩ Seeked to **{int(new_pos)}s** in **{st.title}**")

    # ---------------- Hybrid Commands (slash + prefix) ----------------

    @commands.hybrid_command(name="join", description="Join your voice channel")
    async def join(self, ctx: commands.Context):
        await self.maybe_defer(ctx)
        try:
            await self.ensure_connected(ctx)
            await self.safe_send(ctx, f"Joined **{ctx.author.voice.channel}**.")
        except commands.CommandError as e:
            await self.safe_send(ctx, str(e))

    @commands.hybrid_command(name="leave", description="Disconnect from voice")
    async def leave(self, ctx: commands.Context):
        await self.maybe_defer(ctx)
        if ctx.voice_client and ctx.guild:
            self.reset_state(ctx.guild.id)
            await ctx.voice_client.disconnect()
            await self.safe_send(ctx, "Disconnected.")
        else:
            await self.safe_send(ctx, "I'm not connected.")

    @commands.hybrid_command(name="stop", description="Stop playback")
    async def stop(self, ctx: commands.Context):
        await self.maybe_defer(ctx)
        vc = ctx.voice_client
        if ctx.guild and vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            self.reset_state(ctx.guild.id)
            self.schedule_idle_disconnect(ctx.guild.id, vc, timeout=15)
            await self.safe_send(ctx, "⏹ Stopped.")
        else:
            await self.safe_send(ctx, "Nothing is playing.")

    @commands.hybrid_command(name="pause", description="Pause playback")
    async def pause(self, ctx: commands.Context):
        await self.maybe_defer(ctx)
        vc = ctx.voice_client
        st = self.state.get(ctx.guild.id) if ctx.guild else None
        if not vc or not st or not vc.is_playing():
            return await self.safe_send(ctx, "Nothing is playing.")

        self.cancel_idle(ctx.guild.id)
        st.paused_pos = st.position()
        st.paused = True
        vc.pause()
        await self.safe_send(ctx, "⏸ Paused.")

    @commands.hybrid_command(name="resume", description="Resume playback")
    async def resume(self, ctx: commands.Context):
        await self.maybe_defer(ctx)
        vc = ctx.voice_client
        st = self.state.get(ctx.guild.id) if ctx.guild else None
        if not vc or not st or not vc.is_paused():
            return await self.safe_send(ctx, "Nothing is paused.")

        self.cancel_idle(ctx.guild.id)
        st.base_offset = st.paused_pos
        st.started_at = time.perf_counter()
        st.paused = False
        vc.resume()
        await self.safe_send(ctx, "▶ Resumed.")

    @commands.hybrid_command(name="play", description="Play a song or add to queue")
    async def play(self, ctx: commands.Context, *, query: str):
        await self.maybe_defer(ctx)
        try:
            vc = await self.ensure_connected(ctx)
        except commands.CommandError as e:
            return await self.safe_send(ctx, str(e))

        self.cancel_idle(ctx.guild.id)

        if vc.is_playing() or vc.is_paused():
            vc.stop()

        await self.safe_send(ctx, "Fetching audio…")

        try:
            info = await asyncio.to_thread(extract_info, query)
            audio_url = info["url"]
            title = info.get("title", "Unknown title")

            source = make_source(audio_url, seek_seconds=0.0)
            vc.play(source, after=lambda e: self._after_play(ctx, source, e))

            self.state[ctx.guild.id] = TrackState(
                audio_url=audio_url,
                title=title,
                base_offset=0.0,
                started_at=time.perf_counter(),
                paused=False,
                paused_pos=0.0,
            )

            await self.safe_send(ctx, f"🎶 Now playing: **{title}**")

        except Exception as e:
            await self.safe_send(ctx, f"Failed to play that. Error: `{type(e).__name__}`")
            print("play error:", repr(e))
            self.schedule_idle_disconnect(ctx.guild.id, vc, timeout=15)

    @commands.hybrid_command(name="seek", description="Seek to a timestamp (SS, MM:SS, HH:MM:SS)")
    async def seek(self, ctx: commands.Context, *, when: str):
        await self.maybe_defer(ctx)
        try:
            seconds = parse_time(when)
        except ValueError as e:
            return await self.safe_send(ctx, str(e))
        await self.do_seek(ctx, seconds)

    @commands.hybrid_command(name="rewind", description="Rewind by time (SS, MM:SS, HH:MM:SS)")
    async def rewind(self, ctx: commands.Context, *, amount: str):
        await self.maybe_defer(ctx)
        st = self.state.get(ctx.guild.id) if ctx.guild else None
        if not st:
            return await self.safe_send(ctx, "Nothing is playing to rewind.")
        try:
            delta = parse_time(amount)
        except ValueError as e:
            return await self.safe_send(ctx, str(e))
        await self.do_seek(ctx, max(0.0, st.position() - delta))

    @commands.hybrid_command(name="forward", description="Forward by time (SS, MM:SS, HH:MM:SS)")
    async def forward(self, ctx: commands.Context, *, amount: str):
        await self.maybe_defer(ctx)
        st = self.state.get(ctx.guild.id) if ctx.guild else None
        if not st:
            return await self.safe_send(ctx, "Nothing is playing to forward.")
        try:
            delta = parse_time(amount)
        except ValueError as e:
            return await self.safe_send(ctx, str(e))
        await self.do_seek(ctx, max(0.0, st.position() + delta))

    @commands.hybrid_command(name="np", description="Show the current track")
    async def np(self, ctx: commands.Context):
        await self.maybe_defer(ctx)
        st = self.state.get(ctx.guild.id) if ctx.guild else None
        if not st:
            return await self.safe_send(ctx, "Nothing is playing.")
        await self.safe_send(ctx, f"🎵 **{st.title}** — ~**{int(st.position())}s**")

    @commands.hybrid_command(name="randomsong", description="Queue a random mix (1-10 rolls)")
    async def randomsong(self, ctx: commands.Context, rolls: int = 1):
        await self.maybe_defer(ctx)
        rolls = max(1, min(int(rolls), 10))
        choices = random.sample(RANDOM_QUERIES, k=min(rolls, len(RANDOM_QUERIES)))
        query = random.choice(choices)
        await self.safe_send(ctx, f"🎲 Random pick: **{query}**")
        await self.play(ctx, query=query)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
