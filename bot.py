import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # optional but recommended for instant slash updates

intents = discord.Intents.default()
intents.message_content = True  # REQUIRED for prefix commands (!guess etc)

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,  # allow our custom /help hybrid command
)

COGS = [
    "cogs.music",
    "cogs.japan",
    "cogs.games",
    "cogs.help",
]

_synced_once = False


async def load_cogs():
    for ext in COGS:
        try:
            await bot.load_extension(ext)
            print(f"✅ Loaded: {ext}")
        except Exception as e:
            print(f"❌ Failed to load {ext}: {repr(e)}")


@bot.event
async def on_ready():
    global _synced_once
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")

    # Sync app commands ONE time (slash commands)
    if not _synced_once:
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))

                # Copy global commands into this guild then sync
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"✅ Synced {len(synced)} GUILD app commands to {GUILD_ID} (instant)")
            else:
                synced = await bot.tree.sync()
                print(f"✅ Synced {len(synced)} GLOBAL app commands (can take time to appear)")

            _synced_once = True
        except Exception as e:
            print("⚠️ Sync failed:", repr(e))

    # Print prefix commands
    try:
        cmds = sorted({c.name for c in bot.commands})
        print("✅ Registered prefix commands:", cmds)
    except Exception as e:
        print("⚠️ Could not list commands:", repr(e))


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"⚠️ Command error in {getattr(ctx, 'command', None)}: {repr(error)}")


async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing in .env")

    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())



