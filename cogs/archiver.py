"""
Archiver Cog - Download command implementation.
Downloads all attachments from a Discord channel.
"""
import asyncio
import re
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from config import Config


class Archiver(commands.Cog):
    """Cog for archiving Discord attachments."""
    
    def __init__(self, bot):
        self.bot = bot
        self.download_delay = Config.DOWNLOAD_DELAY
        self.owner_id = int(Config.OWNER_ID) if Config.OWNER_ID else None
        self.approved_users = Config.APPROVED_USERS
        self.download_queues = {}  # Queue of download jobs per user_id
        self.active_downloads = {}  # Track currently processing download by user_id
        self.queue_locks = {}  # Locks to prevent race conditions

    def is_authorized(self, user_id: int) -> bool:
        """Check if user is owner or in approved users list."""
        if not self.owner_id:
            return False
            
        if user_id == self.owner_id:
            return True
            
        return user_id in self.approved_users
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Remove invalid characters from filename.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename safe for Windows/Linux/Mac
        """
        # Remove or replace invalid characters
        # Windows: < > : " / \ | ? *
        # Also remove control characters
        invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
        sanitized = re.sub(invalid_chars, '_', filename)
        
        # Remove leading/trailing spaces and dots (Windows issues)
        sanitized = sanitized.strip('. ')
        
        # Ensure filename is not empty
        if not sanitized:
            sanitized = 'unnamed_file'
        
        return sanitized
    
    def create_folder_structure(
        self,
        guild_name: str,
        channel_name: str,
        thread_name: Optional[str] = None
    ) -> Path:
        """
        Create organized folder structure for downloads.
        
        Args:
            guild_name: Discord server name
            channel_name: Channel name
            thread_name: Thread name (if applicable)
            
        Returns:
            Path object for the download directory
        """
        # Start with base download directory
        base_path = Path(Config.DOWNLOAD_DIRECTORY)
        
        # Sanitize folder names
        guild_folder = self.sanitize_filename(guild_name)
        channel_folder = self.sanitize_filename(channel_name)
        
        # Build path: base/server/channel or base/server/channel/thread
        if thread_name:
            thread_folder = self.sanitize_filename(thread_name)
            full_path = base_path / guild_folder / channel_folder / thread_folder
        else:
            full_path = base_path / guild_folder / channel_folder
        
        # Create directory structure
        full_path.mkdir(parents=True, exist_ok=True)
        
        return full_path
    
    async def download_file(
        self,
        session: aiohttp.ClientSession,
        url: str,
        save_path: Path
    ) -> bool:
        """
        Download a file from URL to local path.
        
        Args:
            session: aiohttp session for downloading
            url: File URL
            save_path: Local path to save file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    # Read and write file in chunks to handle large files
                    with open(save_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                    return True
                else:
                    print(f"❌ Failed to download {url}: HTTP {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Error downloading {url}: {e}")
            return False
    
    def get_unique_filename(self, directory: Path, filename: str) -> Path:
        """
        Get a unique filename by appending a counter if file exists.
        
        Args:
            directory: Directory to save file
            filename: Original filename
            
        Returns:
            Unique file path
        """
        file_path = directory / filename
        
        # If file doesn't exist, return as-is
        if not file_path.exists():
            return file_path
        
        # Split filename and extension
        stem = file_path.stem
        suffix = file_path.suffix
        
        # Try appending counter until we find an unused name
        counter = 1
        while True:
            new_filename = f"{stem}_{counter}{suffix}"
            new_path = directory / new_filename
            if not new_path.exists():
                return new_path
            counter += 1
    
    async def process_download_queue(self, user_id: int):
        """
        Process download queue for a user sequentially.
        
        Args:
            user_id: Discord user ID
        """
        # Get or create lock for this user
        if user_id not in self.queue_locks:
            self.queue_locks[user_id] = asyncio.Lock()
        
        # Track cumulative stats
        all_failures = []
        
        async with self.queue_locks[user_id]:
            while user_id in self.download_queues and self.download_queues[user_id]:
                # Get next job from queue
                job = self.download_queues[user_id].pop(0)
                
                # Process the download and get failures
                job_failures = await self._execute_download(job)
                all_failures.extend(job_failures)
                
            # Clean up empty queue
            if user_id in self.download_queues and not self.download_queues[user_id]:
                del self.download_queues[user_id]
                
                # Notify owner and the user who requested logic
                completion_msg = (f"✅ **All queued downloads complete!**\n"
                                  f"📂 Archive ready in: `{Config.DOWNLOAD_DIRECTORY}`")
                
                # Add failure report if any
                if all_failures:
                    completion_msg += f"\n\n❌ **{len(all_failures)} Failed Downloads:**"
                    
                    # Split into chunks if too long (Discord limit 2000 chars)
                    failure_text = ""
                    for fail in all_failures:
                        line = f"\n• [{fail['filename']}]({fail['url']})"
                        if len(completion_msg) + len(failure_text) + len(line) < 1900:
                            failure_text += line
                        else:
                            failure_text += f"\n• ...and {len(all_failures) - all_failures.index(fail)} more."
                            break
                    completion_msg += failure_text

                # List of users to notify
                notification_targets = {self.owner_id}
                if user_id != self.owner_id:
                    notification_targets.add(user_id)

                for target_id in notification_targets:
                    if not target_id:
                        continue
                    try:
                        target_user = await self.bot.fetch_user(target_id)
                        if target_user:
                            await target_user.send(completion_msg)
                    except Exception as e:
                        print(f"⚠️ Failed to notify user {target_id}: {e}")
    
    async def _safe_edit(self, message, content):
        """
        Safely edit a message, falling back to sending a new one if token expired.
        
        Args:
            message: The message to edit
            content: New content
            
        Returns:
            The message object (updated or new)
        """
        try:
            await message.edit(content=content)
            return message
        except discord.HTTPException as e:
            # Error 50027: Invalid Webhook Token (expired)
            # Error 404: Message deleted
            if e.code == 50027 or e.status == 401 or e.status == 404:
                # Token expired or message gone, send new message to channel
                try:
                    # Try to get channel from message attribute or fallback
                    channel = message.channel
                    new_message = await channel.send(content)
                    return new_message
                except Exception as send_error:
                    print(f"❌ Failed to send new status message: {send_error}")
                    return message
            else:
                print(f"⚠️ Error editing status message: {e}")
                return message
        except Exception as e:
            print(f"⚠️ Unexpected error editing message: {e}")
            return message

    async def _execute_download(self, job: dict) -> list:
        """
        Execute a single download job.
        
        Args:
            job: Dictionary containing download job details
            
        Returns:
            List of dictionaries containing failed download info
        """
        interaction = job['interaction']
        channel = job['channel']
        guild = job['guild']
        channel_name = job['channel_name']
        thread_name = job['thread_name']
        channel_name = job['channel_name']
        thread_name = job['thread_name']
        status_message = job['status_message']
        stop_on_bot = job.get('stop_on_bot', False)
        user_id = interaction.user.id
        
        job_failures = []
        
        # Update status to show processing
        queue_position = len(self.download_queues.get(user_id, [])) + 1
        status_message = await self._safe_edit(
            status_message,
            f"⚙️ **Processing download...** (Queue: {queue_position} remaining)\n"
            f"Channel: **{channel.name}**"
        )
        print(f"⬇️ Starting download from channel: #{channel.name}")
        
        # Create folder structure
        download_dir = self.create_folder_structure(
            guild.name,
            channel_name,
            thread_name
        )
        
        # Update message
        status_message = await self._safe_edit(
            status_message,
            f"🔍 Scanning messages in **{channel.name}**..."
        )
        
        # Collect all messages with attachments
        messages_with_attachments = []
        total_messages = 0
        
        try:
            async for message in channel.history(limit=None):
                # Check for incremental stop condition
                if stop_on_bot and message.author.id == self.bot.user.id and message.id != status_message.id:
                    print(f"🛑 Reached bot message (ID: {message.id}), stopping scan.")
                    break
                    
                total_messages += 1
                if message.attachments:
                    messages_with_attachments.append(message)
        except discord.Forbidden:
            status_message = await self._safe_edit(
                status_message,
                "❌ I don't have permission to read message history in this channel!"
            )
            return []
        except Exception as e:
            status_message = await self._safe_edit(
                status_message,
                f"❌ Error reading messages: {e}"
            )
            return []
        
        # Count total attachments
        total_attachments = sum(len(msg.attachments) for msg in messages_with_attachments)
        
        if total_attachments == 0:
            status_message = await self._safe_edit(
                status_message,
                f"📭 No attachments found in **{channel.name}** (scanned {total_messages} messages)"
            )
            return []
        
        # Update message with found count
        status_message = await self._safe_edit(
            status_message,
            f"📥 Found {total_attachments} attachment(s) in {len(messages_with_attachments)} message(s)\n"
            f"⬇️ Starting download to: `{download_dir}`"
        )
        
        # Download all attachments
        downloaded = 0
        failed = 0
        
        # Track this download
        self.active_downloads[user_id] = {'cancelled': False, 'channel': channel.name}
        
        try:
            async with aiohttp.ClientSession() as session:
                for msg_index, message in enumerate(messages_with_attachments, 1):
                    # Check if download was cancelled
                    if self.active_downloads[user_id]['cancelled']:
                        status_message = await self._safe_edit(
                            status_message,
                            f"🛑 **Download Cancelled!**\n\n"
                            f"Downloaded {downloaded}/{total_attachments} files before cancellation.\n"
                            f"Location: `{download_dir.absolute()}`"
                        )
                        return job_failures
                    
                    for attachment in message.attachments:
                        # Check cancellation before each file
                        if self.active_downloads[user_id]['cancelled']:
                            status_message = await self._safe_edit(
                                status_message,
                                f"🛑 **Download Cancelled!**\n\n"
                                f"Downloaded {downloaded}/{total_attachments} files before cancellation.\n"
                                f"Location: `{download_dir.absolute()}`"
                            )
                            return job_failures
                        
                        # Sanitize filename
                        safe_filename = self.sanitize_filename(attachment.filename)
                        
                        # Get unique filename to avoid overwrites
                        save_path = self.get_unique_filename(download_dir, safe_filename)
                        
                        # Download file
                        success = await self.download_file(session, attachment.url, save_path)
                        
                        if success:
                            downloaded += 1
                            print(f"✅ Downloaded: {save_path.name}")
                        else:
                            failed += 1
                            job_failures.append({
                                'filename': attachment.filename,
                                'url': message.jump_url
                            })
                        
                        # Apply rate limiting
                        await asyncio.sleep(self.download_delay)
                        
                        # Update progress every 10 files
                        if downloaded % 10 == 0:
                            remaining_in_queue = len(self.download_queues.get(user_id, []))
                            queue_text = f" ({remaining_in_queue} in queue)" if remaining_in_queue > 0 else ""
                            status_message = await self._safe_edit(
                                status_message,
                                f"📥 Downloading... {downloaded}/{total_attachments} files{queue_text}\n"
                                f"💡 Use `/stop` to cancel"
                            )
        finally:
            # Clean up tracking
            if user_id in self.active_downloads:
                del self.active_downloads[user_id]
        
        # Final summary
        remaining_in_queue = len(self.download_queues.get(user_id, []))
        summary_lines = [
            f"✅ **Download Complete!**",
            f"",
            f"📊 **Summary:**",
            f"• Downloaded: {downloaded} file(s)",
        ]
        
        if failed > 0:
            summary_lines.append(f"• Failed: {failed} file(s)")
        
        summary_lines.extend([
            f"• Location: `{download_dir.absolute()}`",
        ])
        
        if remaining_in_queue > 0:
            summary_lines.append(f"")
            summary_lines.append(f"⏭️ Processing next download... ({remaining_in_queue} remaining in queue)")
        
        status_message = await self._safe_edit(status_message, "\n".join(summary_lines))
        return job_failures
    
    @app_commands.command(
        name="downloadall",
        description="Download all attachments from this channel"
    )
    @app_commands.guild_only()
    async def downloadall_command(self, interaction: discord.Interaction):
        """
        Slash command to download all attachments from current channel.
        
        Args:
            interaction: Discord interaction object
        """
        # Defer response since this will take time
        # Check authorization
        if not self.is_authorized(interaction.user.id):
            await interaction.response.send_message(
                "⛔ **Access Denied**\n"
                "You are not authorized to use this bot.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)
        
        user_id = interaction.user.id
        channel = interaction.channel
        guild = interaction.guild
        
        # Check if we're in a thread
        thread_name = None
        if isinstance(channel, discord.Thread):
            thread_name = channel.name
            parent_channel = channel.parent
            channel_name = parent_channel.name if parent_channel else "unknown-channel"
        else:
            channel_name = channel.name
        
        # Create or get queue for this user
        if user_id not in self.download_queues:
            self.download_queues[user_id] = []
        
        # Check queue position
        queue_position = len(self.download_queues[user_id]) + 1
        
        # Send status message
        if queue_position == 1:
            status_message = await interaction.followup.send(
                f"📥 **Queued download for #{channel.name}**\n"
                f"Starting immediately...",
                wait=True
            )
        else:
            status_message = await interaction.followup.send(
                f"📥 **Download queued for #{channel.name}**\n"
                f"Position in queue: **{queue_position}**\n"
                f"Your download will start automatically when ready.",
                wait=True
            )
        
        # Add job for the main channel
        job = {
            'interaction': interaction,
            'channel': channel,
            'guild': guild,
            'channel_name': channel_name,
            'thread_name': thread_name,
            'status_message': status_message
        }
        self.download_queues[user_id].append(job)
        
        # Check for threads if this is a text channel (not a thread itself)
        thread_count = 0
        if isinstance(channel, discord.TextChannel):
            try:
                # Get active threads
                threads = channel.threads
                
                # Get archived threads (requires history permission)
                async for thread in channel.archived_threads(limit=None):
                    threads.append(thread)
                
                # Add each thread as a separate job
                for thread in threads:
                    thread_job = {
                        'interaction': interaction,
                        'channel': thread,
                        'guild': guild,
                        'channel_name': channel_name,
                        'thread_name': thread.name,
                        'status_message': status_message  # Reuse status message to update user
                    }
                    self.download_queues[user_id].append(thread_job)
                    thread_count += 1
                    
            except Exception as e:
                print(f"⚠️ Failed to scan threads for {channel.name}: {e}")
        
        # Update status message with queue info
        msg_content = ""
        if queue_position == 1:
            msg_content = f"📥 **Queued download for #{channel.name}**"
        else:
            msg_content = f"📥 **Download queued for #{channel.name}**\nPosition in queue: **{queue_position}**"
            
        if thread_count > 0:
            msg_content += f"\n➕ Also queued **{thread_count}** thread(s) from this channel!"
            
        if queue_position == 1:
            msg_content += "\nStarting immediately..."
        else:
            msg_content += "\nYour download will start automatically when ready."
            
        await status_message.edit(content=msg_content)
        
        # Start processing queue if this is the only job (and we haven't started yet)
        if queue_position == 1:
            # Process queue in background
            asyncio.create_task(self.process_download_queue(user_id))

    @app_commands.command(
        name="download",
        description="Incremental download (stops at bot's last message)"
    )
    @app_commands.guild_only()
    async def download_command(self, interaction: discord.Interaction):
        """
        Slash command to download attachments until a bot message is found.
        
        Args:
            interaction: Discord interaction object
        """
        # Defer response since this will take time
        # Check authorization
        if not self.is_authorized(interaction.user.id):
            await interaction.response.send_message(
                "⛔ **Access Denied**\n"
                "You are not authorized to use this bot.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)
        
        user_id = interaction.user.id
        channel = interaction.channel
        guild = interaction.guild
        
        # Check if we're in a thread
        thread_name = None
        if isinstance(channel, discord.Thread):
            thread_name = channel.name
            parent_channel = channel.parent
            channel_name = parent_channel.name if parent_channel else "unknown-channel"
        else:
            channel_name = channel.name
        
        # Create or get queue for this user
        if user_id not in self.download_queues:
            self.download_queues[user_id] = []
        
        # Check queue position
        queue_position = len(self.download_queues[user_id]) + 1
        
        # Send status message
        if queue_position == 1:
            status_message = await interaction.followup.send(
                f"📥 **Queued incremental download for #{channel.name}**\n"
                f"Starting immediately...",
                wait=True
            )
        else:
            status_message = await interaction.followup.send(
                f"📥 **Incremental download queued for #{channel.name}**\n"
                f"Position in queue: **{queue_position}**\n"
                f"Your download will start automatically when ready.",
                wait=True
            )
        
        # Find last bot message for incremental cutoff
        cutoff_id = 0
        cutoff_message_url = None
        
        # We need to find the last message from the bot *before* the current status message
        async for message in channel.history(limit=100):
            if message.author.id == self.bot.user.id and message.id != status_message.id:
                cutoff_id = message.id
                cutoff_message_url = message.jump_url
                break
        
        if cutoff_id > 0:
            await status_message.edit(content=f"🔍 Found previous bot message. Incremental scan starting from: {cutoff_message_url}")
        else:
            await status_message.edit(content=f"ℹ️ No previous bot message found. Doing full scan.")

        # Add job for the main channel
        job = {
            'interaction': interaction,
            'channel': channel,
            'guild': guild,
            'channel_name': channel_name,
            'thread_name': thread_name,
            'status_message': status_message,
            'stop_on_bot': True  # Enable incremental stop
        }
        self.download_queues[user_id].append(job)
        
        # Check for threads if this is a text channel (not a thread itself)
        thread_count = 0
        skipped_threads = 0
        
        if isinstance(channel, discord.TextChannel):
            try:
                # Get active threads
                threads = channel.threads
                
                # Get archived threads (requires history permission)
                async for thread in channel.archived_threads(limit=None):
                    threads.append(thread)
                
                # Add each thread as a separate job
                for thread in threads:
                    # Check if thread is older than cutoff
                    if cutoff_id > 0 and thread.id <= cutoff_id:
                        skipped_threads += 1
                        continue
                        
                    thread_job = {
                        'interaction': interaction,
                        'channel': thread,
                        'guild': guild,
                        'channel_name': channel_name,
                        'thread_name': thread.name,
                        'status_message': status_message,  # Reuse status message to update user
                        'stop_on_bot': True
                    }
                    self.download_queues[user_id].append(thread_job)
                    thread_count += 1
                    
            except Exception as e:
                print(f"⚠️ Failed to scan threads for {channel.name}: {e}")
        
        # Update status message with queue info
        msg_content = ""
        if queue_position == 1:
            msg_content = f"📥 **Queued incremental download for #{channel.name}**"
        else:
            msg_content = f"📥 **Incremental download queued for #{channel.name}**\nPosition in queue: **{queue_position}**"
            
        if thread_count > 0:
            msg_content += f"\n➕ Also queued **{thread_count}** new thread(s)!"
            
        if skipped_threads > 0:
            msg_content += f"\n⏩ Skipped **{skipped_threads}** old thread(s)."
            
        if queue_position == 1:
            msg_content += "\nStarting immediately..."
        else:
            msg_content += "\nYour download will start automatically when ready."
            
        await status_message.edit(content=msg_content)
        
        # Start processing queue if this is the only job (and we haven't started yet)
        if queue_position == 1:
            # Process queue in background
            asyncio.create_task(self.process_download_queue(user_id))
    
    @app_commands.command(
        name="stop",
        description="Stop current download and clear your download queue"
    )
    @app_commands.guild_only()
    async def stop_command(self, interaction: discord.Interaction):
        """
        Slash command to cancel ongoing download and clear queue.
        
        Args:
            interaction: Discord interaction object
        """
        user_id = interaction.user.id

        # Check authorization
        if not self.is_authorized(user_id):
            await interaction.response.send_message(
                "⛔ **Access Denied**\n"
                "You are not authorized to use this bot.",
                ephemeral=True
            )
            return
        
        has_active = user_id in self.active_downloads
        has_queue = user_id in self.download_queues and self.download_queues[user_id]
        
        if not has_active and not has_queue:
            await interaction.response.send_message(
                "❌ You don't have any active downloads or queued jobs.",
                ephemeral=True
            )
            return
        
        # Cancel active download
        if has_active:
            self.active_downloads[user_id]['cancelled'] = True
        
        # Clear queue
        queue_count = 0
        if has_queue:
            queue_count = len(self.download_queues[user_id])
            self.download_queues[user_id].clear()
        
        # Build response message
        msg_parts = []
        if has_active:
            msg_parts.append("🛑 Stopping current download...")
        if queue_count > 0:
            msg_parts.append(f"🗑️ Cleared {queue_count} queued download(s)")
        
        await interaction.response.send_message(
            "\n".join(msg_parts),
            ephemeral=True
        )
    
    @app_commands.command(
        name="queue",
        description="View your current download queue"
    )
    @app_commands.guild_only()
    async def queue_command(self, interaction: discord.Interaction):
        """
        Slash command to view download queue status.
        
        Args:
            interaction: Discord interaction object
        """
        user_id = interaction.user.id
        
        # Check authorization
        if not self.is_authorized(user_id):
            await interaction.response.send_message(
                "⛔ **Access Denied**\n"
                "You are not authorized to use this bot.",
                ephemeral=True
            )
            return
        
        has_active = user_id in self.active_downloads
        has_queue = user_id in self.download_queues and self.download_queues[user_id]
        
        if not has_active and not has_queue:
            await interaction.response.send_message(
                "📭 You have no active downloads or queued jobs.",
                ephemeral=True
            )
            return
        
        # Build status message
        status_lines = ["📊 **Your Download Queue**", ""]
        
        if has_active:
            channel_name = self.active_downloads[user_id].get('channel', 'Unknown')
            status_lines.append(f"⚙️ **Currently downloading:** #{channel_name}")
        
        if has_queue:
            queue = self.download_queues[user_id]
            status_lines.append(f"")
            status_lines.append(f"📋 **Queued downloads:** {len(queue)}")
            for i, job in enumerate(queue, 1):
                channel_name = job['channel'].name
                status_lines.append(f"  {i}. #{channel_name}")
        
        status_lines.append("")
        status_lines.append("💡 Use `/stop` to cancel all downloads")
        
        await interaction.response.send_message(
            "\n".join(status_lines),
            ephemeral=True
        )

    @app_commands.command(
        name="clearqueue",
        description="Clear your download queue without stopping current download"
    )
    @app_commands.guild_only()
    async def clearqueue_command(self, interaction: discord.Interaction):
        """
        Slash command to clear pending downloads.
        
        Args:
            interaction: Discord interaction object
        """
        user_id = interaction.user.id
        
        # Check authorization
        if not self.is_authorized(user_id):
            await interaction.response.send_message(
                "⛔ **Access Denied**\n"
                "You are not authorized to use this bot.",
                ephemeral=True
            )
            return
        
        has_queue = user_id in self.download_queues and self.download_queues[user_id]
        
        if not has_queue:
            await interaction.response.send_message(
                "📭 Your download queue is already empty.",
                ephemeral=True
            )
            return
        
        # Clear queue
        queue_count = len(self.download_queues[user_id])
        self.download_queues[user_id].clear()
        
        await interaction.response.send_message(
            f"🗑️ Cleared **{queue_count}** items from your download queue.\n"
            f"Note: The currently active download will continue.",
            ephemeral=True
        )


async def setup(bot):
    """Required setup function for cog loading."""
    await bot.add_cog(Archiver(bot))
