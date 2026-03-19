import os
import json
import asyncio
import re
from typing import Dict, List, Set, Tuple, Optional
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

# Allow override for Docker (e.g. /app/data/seen.json)
SEEN_PATH = os.getenv("SEEN_PATH", "seen.json")
MAX_POSTS_PER_RUN = 4  # Post items from all feeds in each batch
MAX_PER_SOURCE = 3  # Max items per source per batch

intents = discord.Intents.default()  # posting only; no message-content needed
client = discord.Client(intents=intents)


def load_seen() -> Set[str]:
    try:
        path = os.path.abspath(SEEN_PATH)
        dirpath = os.path.dirname(path)
        if dirpath and not os.path.isdir(dirpath):
            os.makedirs(dirpath, exist_ok=True)
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()
    except Exception:
        return set()


def save_seen(seen: Set[str]) -> None:
    path = os.path.abspath(SEEN_PATH)
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.isdir(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen)[-2000:], f)  # keep last ~2000 IDs


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


@tasks.loop(minutes=POLL_MINUTES)
async def poll_and_post():
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        channel = await client.fetch_channel(CHANNEL_ID)

    seen = load_seen()

    headers = {
        # Some feeds are picky; a browser-like UA reduces random 403/400s.
        "User-Agent": "Mozilla/5.0 (compatible; hugging-face-bot/1.0)",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        results = await asyncio.gather(
            *(fetch_feed(session, name, url) for name, url in FEEDS),
            return_exceptions=True,
        )

        # Group items by source
        items_by_source: Dict[str, List[Dict]] = {}

        for i, res in enumerate(results):
            source_name = FEEDS[i][0]
            if isinstance(res, Exception):
                print(f"[Error] Feed fetch failed for {source_name}: {res}")
                items_by_source[source_name] = []
                continue

            source_items = []
            for item in res:
                if item["uid"] not in seen:
                    source_items.append(item)
            items_by_source[source_name] = source_items

    # Distribute items from all sources in round-robin fashion
    new_items: List[Dict] = []
    source_indices = {source: 0 for source in items_by_source.keys()}

    # Round-robin: take up to MAX_PER_SOURCE from each source
    while len(new_items) < MAX_POSTS_PER_RUN:
        added_any = False
        for source_name in items_by_source.keys():
            if len(new_items) >= MAX_POSTS_PER_RUN:
                break
            source_items = items_by_source[source_name]
            idx = source_indices[source_name]

            # Take items from this source (up to MAX_PER_SOURCE per source)
            items_taken = 0
            while (
                idx < len(source_items)
                and items_taken < MAX_PER_SOURCE
                and len(new_items) < MAX_POSTS_PER_RUN
            ):
                new_items.append(source_items[idx])
                idx += 1
                items_taken += 1
                added_any = True
            source_indices[source_name] = idx

        # If we didn't add any items, break to avoid infinite loop
        if not added_any:
            break

    if not new_items:
        print("[Info] No new items to post")
        return

    # Post to Discord
    for item in new_items:
        try:
            embed = to_embed(item)
            await channel.send(embed=embed)
            seen.add(item["uid"])
            print(f"[Posted] {item['source']}: {item['title'][:50]}...")
        except Exception as e:
            print(f"[Error] Failed to post {item['title'][:50]}: {e}")

    save_seen(seen)


@client.event
async def on_ready():
    print(f"✓ Logged in as {client.user}")
    print(f"✓ Watching {len(FEEDS)} feeds")
    print(f"✓ Polling every {POLL_MINUTES} minutes ({POLL_MINUTES / 60:.1f} hours)")
    poll_and_post.start()


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        exit(1)
    if CHANNEL_ID == 0:
        print("ERROR: CHANNEL_ID not set in .env")
        exit(1)
    client.run(DISCORD_TOKEN)

