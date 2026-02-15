"""
Configuration loader for Discord Archiver Bot.
Loads environment variables and provides validation.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Bot configuration from environment variables."""
    
    # Discord Bot Token (required)
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    
    # Download directory (default: ./downloads)
    DOWNLOAD_DIRECTORY = os.getenv('DOWNLOAD_DIRECTORY', './downloads')
    
    # Download delay in seconds (default: 0.25)
    try:
        DOWNLOAD_DELAY = float(os.getenv('DOWNLOAD_DELAY', '0.25'))
    except ValueError:
        DOWNLOAD_DELAY = 0.25
    
    # Owner ID (required) - Only this user can use the bot
    OWNER_ID = os.getenv('OWNER_ID')

    # Approved Users (optional) - Comma-separated list of user IDs
    # These users can also use the bot and receive notifications
    try:
        users_str = os.getenv('APPROVED_USERS', '')
        APPROVED_USERS = [int(uid.strip()) for uid in users_str.split(',') if uid.strip()]
    except ValueError:
        print("⚠️ Warning: Invalid APPROVED_USERS format in .env (should be comma-separated IDs)")
        APPROVED_USERS = []
    
    @classmethod
    def validate(cls):
        """Validate required configuration values."""
        if not cls.DISCORD_TOKEN or cls.DISCORD_TOKEN == 'your_bot_token_here':
            raise ValueError(
                "DISCORD_TOKEN is not set in .env file!\n"
                "Please add your bot token from https://discord.com/developers/applications"
            )
            
        if not cls.OWNER_ID:
            raise ValueError(
                "OWNER_ID is not set in .env file!\n"
                "Please add your User ID to restrict access to the bot and enable notifications."
            )
        
        # Create download directory if it doesn't exist
        download_path = Path(cls.DOWNLOAD_DIRECTORY)
        download_path.mkdir(parents=True, exist_ok=True)
        
        print(f"✅ Configuration loaded:")
        print(f"   Download directory: {download_path.absolute()}")
        print(f"   Download delay: {cls.DOWNLOAD_DELAY}s")
        print(f"   Owner ID: {cls.OWNER_ID}")
        if cls.APPROVED_USERS:
            print(f"   Approved Users: {len(cls.APPROVED_USERS)}")

# Validate configuration on import
Config.validate()
