"""
Discord Archiver Bot - Main Entry Point
Downloads all attachments from a channel using /downloadall command.
"""
import discord
from discord.ext import commands
from config import Config

# Create bot instance with required intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read message attachments
intents.messages = True         # Required to read message history

bot = commands.Bot(
    command_prefix='!',  # Required by discord.py (won't be used)
    intents=intents,
    help_command=None
)

@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    print(f"\n{'='*50}")
    print(f"✅ Bot logged in as: {bot.user.name}")
    print(f"   Bot ID: {bot.user.id}")
    print(f"   Connected to {len(bot.guilds)} server(s)")
    print(f"{'='*50}\n")
    
    # Sync slash commands with Discord
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

@bot.event
async def on_guild_join(guild):
    """Called when bot joins a new server."""
    print(f"📥 Joined new server: {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_remove(guild):
    """Called when bot leaves a server."""
    print(f"📤 Left server: {guild.name} (ID: {guild.id})")

async def load_extensions():
    """Load all cogs (command modules)."""
    try:
        await bot.load_extension('cogs.archiver')
        print("✅ Loaded archiver cog")
    except Exception as e:
        print(f"❌ Failed to load archiver cog: {e}")
        raise

async def main():
    """Main bot startup function."""
    async with bot:
        await load_extensions()
        await bot.start(Config.DISCORD_TOKEN)

if __name__ == '__main__':
    import asyncio
    
    print("\n🤖 Starting Discord Archiver Bot...")
    print("   Press Ctrl+C to stop\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        raise
