# Discord Archiver Bot

A robust Discord bot that archives channel attachments, supports concurrent download queues, and organizes files into a structured folder hierarchy.

## Features

- 📥 **Smart Downloads**: Archives all attachments from any channel
- 🧵 **Thread Support**: Automatically scans and archives all threads in a channel
- 📂 **Organized Structure**: Saves files to `Server/Channel/Thread/`
- 📋 **Queue System**: Queue multiple channels sequentially without conflicts
- 🛑 **Control**: Stop specific downloads or clear the entire queue
- 🔔 **Notifications**: Get a DM when your download queue finishes
- ⏱️ **Rate Limiting**: Configurable delay to prevent API spam
    - 🔄 **Resilient**: Handles expired tokens for long-running jobs automatically

## 🔒 Privacy & Usage

> [!IMPORTANT]
> **This bot downloads files directly to the computer running the script.**

- **Personal Use Only**: It is designed for single-user archiving.
- **Host Storage**: Files are saved to the local drive of the host machine.
- **Restricted Access**: Commands are restricted to the `OWNER_ID` specified in the configuration. Other users cannot trigger downloads.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

1. Rename `.env.example` to `.env`
2. Configure your keys:

```ini
# Bot Token from Discord Developer Portal
DISCORD_TOKEN=your_token_here

# Directory to save files
DOWNLOAD_DIRECTORY=./downloads

# Your User ID (Required) - Restricts usage to you only
OWNER_ID=123456789012345678
```

### 3. Run the Bot

```bash
python bot.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/download` | Incremental download (stops when it sees a message from this bot) |
| `/downloadall` | Queue the current channel (and its threads) for archiving |
| `/queue` | View your current download queue status |
| `/stop` | Cancel the currently active download |
| `/clearqueue` | Clear all pending downloads without stopping the current one |

## Project Structure

```
discord-archiver/
├── .env                    # Configuration (Keep secret!)
├── config.py              # Config loader
├── bot.py                 # Main entry point
└── cogs/
    └── archiver.py        # Core logic
```

## License

MIT License
