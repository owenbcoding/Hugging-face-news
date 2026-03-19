import os
import asyncio
import re
from typing import Dict, List, Tuple, Optional
from html import unescape

import aiohttp
import feedparser
import discord
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "180"))  # 180 = every 3 hours

# Hugging Face news feeds
FEEDS: List[Tuple[str, str]] = [
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
]

MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))  # Post this many items from feed each poll
POST_DELAY_SECONDS = int(os.getenv("POST_DELAY_SECONDS", "5"))  # Delay between posts to avoid spam

intents = discord.Intents.default()  # posting only; no message-content needed
client = discord.Client(intents=intents)


def _first_link(entry: dict) -> Optional[str]:
    link = entry.get("link")
    if link:
        return str(link)
    links = entry.get("links") or []
    for candidate in links:
        href = candidate.get("href")
        if href:
            return str(href)
    return None


def _make_uid(entry: dict, link: Optional[str]) -> Optional[str]:
    uid = entry.get("id") or entry.get("guid")
    if uid:
        return str(uid)
    if link:
        return str(link)
    title = entry.get("title")
    if title:
        return f"title:{title}"
    return None


async def fetch_feed(session: aiohttp.ClientSession, name: str, url: str) -> List[Dict]:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
        resp.raise_for_status()
        data = await resp.read()

    parsed = feedparser.parse(data)
    items = []
    for entry in parsed.entries:
        link = _first_link(entry)
        title = entry.get("title", "(no title)")
        uid = _make_uid(entry, link)
        if not uid or not link:
            continue

        # Extract description/summary from feed entry
        description = entry.get("summary") or entry.get("description") or ""
        # Clean HTML tags and decode HTML entities
        if description:
            # Remove HTML tags
            description = re.sub(r"<[^>]+>", "", description)
            # Decode HTML entities
            description = unescape(description)
            # Clean up whitespace
            description = re.sub(r"\s+", " ", description).strip()
            # Limit length for Discord embed (max 4096 chars, but we'll use 500 for readability)
            if len(description) > 500:
                description = description[:497] + "..."

        items.append(
            {
                "source": name,
                "uid": str(uid),
                "title": str(title),
                "link": str(link),
                "description": description,
            }
        )
    return items


def to_embed(item: Dict) -> discord.Embed:
    embed = discord.Embed(title=item["title"], url=item["link"])

    # Add description if available
    description = item.get("description", "")
    if description:
        embed.description = description
    else:
        embed.description = f"Read more from {item['source']}"

    embed.set_footer(text=item["source"])
    return embed


def _print_channel_diagnostics():
    """Print diagnostic info when channel access fails."""
    print(f"[Diagnostic] CHANNEL_ID = {CHANNEL_ID!r} (type: {type(CHANNEL_ID).__name__})")
    guilds = list(client.guilds)
    if not guilds:
        print(
            "[Diagnostic] Bot is in ZERO servers. You must invite the bot to your Discord "
            "server first. Use the OAuth2 URL Generator in the Discord Developer Portal."
        )
        return
    print(f"[Diagnostic] Bot is in {len(guilds)} server(s):")
    found = False
    for g in guilds:
        chans = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        ids = {c.id for c in chans}
        if CHANNEL_ID in ids:
            found = True
            ch = g.get_channel(CHANNEL_ID)
            print(f"  -> Found #{ch.name} in '{g.name}' (id: {g.id})")
        print(f"  - '{g.name}' (id: {g.id}): {len(chans)} text channels")
        for c in chans[:5]:  # first 5 as sample
            print(f"      #{c.name} id={c.id}")
        if len(chans) > 5:
            print(f"      ... and {len(chans) - 5} more")
    if not found:
        print(
            "[Diagnostic] CHANNEL_ID not in any server the bot is in. Either invite "
            "the bot to the server containing that channel, or use a channel ID from "
            "one of the servers listed above."
        )


def _find_channel_in_cache():
    """Search guild cache for channel - bypasses API, can work when fetch_channel 404s."""
    for guild in client.guilds:
        # Text channels, voice, categories, etc.
        ch = guild.get_channel(CHANNEL_ID)
        if ch is not None:
            return ch
        # Threads (forum posts, public/private threads)
        for thread in getattr(guild, "threads", []):
            if thread.id == CHANNEL_ID:
                return thread
        # Some older discord.py versions store threads differently
        for ch in guild.channels:
            if ch.id == CHANNEL_ID:
                return ch
    return None


async def get_post_channel():
    """Get the target channel, or None if inaccessible."""
    # 1. Quick cache lookup
    channel = client.get_channel(CHANNEL_ID)
    if channel is not None:
        return channel
    # 2. Search guild cache (bypasses API - can work when fetch returns 404)
    channel = _find_channel_in_cache()
    if channel is not None:
        print(f"[Info] Resolved channel via cache: #{channel.name}")
        return channel
    # 3. API fetch
    try:
        return await client.fetch_channel(CHANNEL_ID)
    except discord.NotFound:
        print("[Error] Channel not found (Discord 10003: Unknown Channel).")
        _print_channel_diagnostics()
        return None
    except discord.Forbidden:
        print("[Error] Bot lacks permission to access the channel.")
        _print_channel_diagnostics()
        return None


@tasks.loop(minutes=POLL_MINUTES)
async def poll_and_post():
    channel = await get_post_channel()
    if channel is None:
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; hugging-face-bot/1.0)",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        results = await asyncio.gather(
            *(fetch_feed(session, name, url) for name, url in FEEDS),
            return_exceptions=True,
        )

    # Collect items from all feeds (RSS feeds are newest-first)
    all_items: List[Dict] = []
    for i, res in enumerate(results):
        source_name = FEEDS[i][0]
        if isinstance(res, Exception):
            print(f"[Error] Feed fetch failed for {source_name}: {res}")
            continue
        all_items.extend(res)

    # Take up to MAX_POSTS_PER_RUN most recent items
    items_to_post = all_items[:MAX_POSTS_PER_RUN]

    if not items_to_post:
        print("[Info] No items from feed")
        return

    # Post to Discord with delay between posts
    for i, item in enumerate(items_to_post):
        try:
            embed = to_embed(item)
            await channel.send(embed=embed)
            print(f"[Posted] {item['source']}: {item['title'][:50]}...")
            if i < len(items_to_post) - 1:
                await asyncio.sleep(POST_DELAY_SECONDS)
        except Exception as e:
            print(f"[Error] Failed to post {item['title'][:50]}: {e}")


@client.event
async def on_ready():
    print(f"✓ Logged in as {client.user}")
    print(f"✓ Watching {len(FEEDS)} feeds")
    print(f"✓ Polling every {POLL_MINUTES} minutes ({POLL_MINUTES / 60:.1f} hours)")

    # Validate channel access before starting the poll loop
    channel = await get_post_channel()
    if channel is None:
        print(f"ERROR: Cannot access channel {CHANNEL_ID}. Fix CHANNEL_ID and restart.")
        exit(1)
    print(f"✓ Target channel: #{channel.name}")

    poll_and_post.start()


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        exit(1)
    if CHANNEL_ID == 0:
        print("ERROR: CHANNEL_ID not set in .env")
        exit(1)
    client.run(DISCORD_TOKEN)

