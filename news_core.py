from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timezone
from html import unescape
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
import discord
import feedparser
from discord import app_commands
from discord.ext import tasks


TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref",
    "source",
    "spm",
    "trk",
}


@dataclass(frozen=True)
class NewsBotConfig:
    bot_name: str
    channel_id: int
    max_posts_per_run: int
    post_delay_seconds: int
    archive_path: str
    dedupe_index_path: str
    feeds: Sequence[Tuple[str, str]]
    post_text_digest: bool = False


# Same fixed schedule as dev-news-bot (09:00 and 17:00 UTC; aligns with GMT in winter).
UTC_POST_TIMES = (
    time(hour=9, tzinfo=timezone.utc),
    time(hour=17, tzinfo=timezone.utc),
)


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw

    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_PARAMS
    ]
    filtered_query.sort()

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def canonical_url_hash(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


def clean_summary(raw_summary: str) -> str:
    if not raw_summary:
        return ""

    summary = re.sub(r"<[^>]+>", "", raw_summary)
    summary = unescape(summary)
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) > 500:
        summary = summary[:497].rstrip() + "..."
    return summary


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_entry_published_at(entry: Any) -> Optional[str]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed_value = entry.get(key)
        if parsed_value:
            timestamp = calendar.timegm(parsed_value)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    return None


def published_sort_key(entry: Dict[str, Any]) -> float:
    published_at = entry.get("published_at")
    if not published_at:
        return 0.0

    try:
        return datetime.fromisoformat(published_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class NewsStorage:
    def __init__(self, archive_path: str, dedupe_index_path: str) -> None:
        self.archive_path = archive_path
        self.dedupe_index_path = dedupe_index_path
        self._ensure_parent(self.archive_path)
        self._ensure_parent(self.dedupe_index_path)
        self.index = self._load_index()

    @staticmethod
    def _ensure_parent(path: str) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self.dedupe_index_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[Warning] Failed to load dedupe index: {exc}")

        return self._rebuild_index_from_archive()

    def _rebuild_index_from_archive(self) -> Dict[str, Dict[str, Any]]:
        rebuilt: Dict[str, Dict[str, Any]] = {}
        try:
            with open(self.archive_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    canonical_url = record.get("canonical_url")
                    if not canonical_url:
                        continue

                    rebuilt[canonical_url_hash(canonical_url)] = {
                        "source": record.get("source"),
                        "title": record.get("title"),
                        "url": record.get("url"),
                        "canonical_url": canonical_url,
                        "published_at": record.get("published_at"),
                        "posted_at": record.get("posted_at"),
                        "discord_message_id": record.get("discord_message_id"),
                    }
        except FileNotFoundError:
            return {}

        if rebuilt:
            self._save_index(rebuilt)
        return rebuilt

    def _save_index(self, data: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        payload = data if data is not None else self.index
        temp_path = f"{self.dedupe_index_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(temp_path, self.dedupe_index_path)

    def contains(self, canonical_hash: str) -> bool:
        return canonical_hash in self.index

    def record_post(self, record: Dict[str, Any]) -> None:
        archive_record = {
            "source": record["source"],
            "title": record["title"],
            "url": record["url"],
            "canonical_url": record["canonical_url"],
            "published_at": record.get("published_at"),
            "posted_at": record.get("posted_at"),
            "discord_message_id": record.get("discord_message_id"),
        }

        with open(self.archive_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(archive_record) + "\n")

        dedupe_hash = canonical_url_hash(record["canonical_url"])
        self.index[dedupe_hash] = archive_record
        self._save_index()

    def latest_links(self, limit: int) -> List[Dict[str, Any]]:
        items: deque[Dict[str, Any]] = deque(maxlen=limit)
        try:
            with open(self.archive_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            return []
        return list(reversed(items))


class NewsBotClient(discord.Client):
    def __init__(self, config: NewsBotConfig) -> None:
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.storage = NewsStorage(
            archive_path=config.archive_path,
            dedupe_index_path=config.dedupe_index_path,
        )
        self.tree = app_commands.CommandTree(self)
        self._commands_synced = False
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="latestlinks", description="Show the most recent saved links.")
        @app_commands.describe(count="How many archived links to show")
        async def latestlinks(
            interaction: discord.Interaction,
            count: app_commands.Range[int, 1, 10] = 5,
        ) -> None:
            items = self.storage.latest_links(count)
            if not items:
                await interaction.response.send_message(
                    "No archived links have been saved yet.",
                    ephemeral=True,
                )
                return

            lines = []
            for item in items:
                source = item.get("source") or "Unknown source"
                title = item.get("title") or "(no title)"
                url = item.get("url") or item.get("canonical_url") or ""
                lines.append(f"- {source}: {title} <{url}>")

            await interaction.response.send_message(
                "\n".join(lines),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def on_ready(self) -> None:
        print(f"✓ Logged in as {self.user}")
        print(f"✓ Watching {len(self.config.feeds)} feeds")
        print("✓ Scheduled posts at 09:00 UTC and 17:00 UTC")

        channel = await self.get_post_channel()
        if channel is None:
            # Do not disconnect: a bad CHANNEL_ID or cache timing should not take the bot offline.
            print(
                f"ERROR: Cannot access channel {self.config.channel_id}. "
                "Posts will be skipped until this is fixed (wrong ID, bot not in server, or missing access)."
            )
            self._print_channel_diagnostics()
        else:
            print(f"✓ Target channel: #{channel.name}")

        if not self._commands_synced:
            synced = await self.tree.sync()
            self._commands_synced = True
            print(f"✓ Synced {len(synced)} application command(s)")

        if not self.poll_and_post.is_running():
            self.poll_and_post.start()

    def _print_channel_diagnostics(self) -> None:
        print(
            f"[Diagnostic] CHANNEL_ID = {self.config.channel_id!r} "
            f"(type: {type(self.config.channel_id).__name__})"
        )
        guilds = list(self.guilds)
        if not guilds:
            print(
                "[Diagnostic] Bot is not in any servers. Invite the bot to the server "
                "that owns the target channel first."
            )
            return

        found = False
        print(f"[Diagnostic] Bot is in {len(guilds)} server(s):")
        for guild in guilds:
            channels = [ch for ch in guild.channels if isinstance(ch, discord.TextChannel)]
            if self.config.channel_id in {ch.id for ch in channels}:
                found = True
                match = guild.get_channel(self.config.channel_id)
                if match is not None:
                    print(f"  -> Found #{match.name} in '{guild.name}' (id: {guild.id})")
            print(f"  - '{guild.name}' (id: {guild.id}): {len(channels)} text channels")

        if not found:
            print("[Diagnostic] CHANNEL_ID was not found in the bot's accessible guilds.")

    def _find_channel_in_cache(self) -> Optional[discord.abc.GuildChannel]:
        for guild in self.guilds:
            channel = guild.get_channel(self.config.channel_id)
            if channel is not None:
                return channel
            for thread in getattr(guild, "threads", []):
                if thread.id == self.config.channel_id:
                    return thread
        return None

    async def get_post_channel(self) -> Optional[discord.abc.Messageable]:
        channel = self.get_channel(self.config.channel_id)
        if channel is not None:
            return channel

        channel = self._find_channel_in_cache()
        if channel is not None:
            print(f"[Info] Resolved channel via cache: #{channel.name}")
            return channel

        try:
            return await self.fetch_channel(self.config.channel_id)
        except discord.NotFound:
            print("[Error] Channel not found (Discord 10003: Unknown Channel).")
            self._print_channel_diagnostics()
            return None
        except discord.Forbidden:
            print("[Error] Bot lacks permission to access the channel.")
            self._print_channel_diagnostics()
            return None

    async def fetch_feed(
        self,
        session: aiohttp.ClientSession,
        source: str,
        feed_url: str,
    ) -> List[Dict[str, Any]]:
        async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=25)) as response:
            response.raise_for_status()
            data = await response.read()

        parsed = feedparser.parse(data)
        items: List[Dict[str, Any]] = []
        for entry in parsed.entries:
            url = self._first_link(entry)
            title = str(entry.get("title", "")).strip()
            if not url or not title:
                continue

            canonical_url = normalize_url(url)
            items.append(
                {
                    "source": source,
                    "title": title,
                    "url": str(url),
                    "canonical_url": canonical_url,
                    "published_at": parse_entry_published_at(entry),
                    "summary": clean_summary(
                        entry.get("summary") or entry.get("description") or ""
                    ),
                    "dedupe_hash": canonical_url_hash(canonical_url),
                }
            )

        return items

    @staticmethod
    def _first_link(entry: Any) -> Optional[str]:
        link = entry.get("link")
        if link:
            return str(link)

        for candidate in entry.get("links") or []:
            href = candidate.get("href")
            if href:
                return str(href)
        return None

    async def collect_new_items(self) -> List[Dict[str, Any]]:
        headers = {
            "User-Agent": f"Mozilla/5.0 (compatible; {self.config.bot_name}/2.0)",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            results = await asyncio.gather(
                *(self.fetch_feed(session, source, url) for source, url in self.config.feeds),
                return_exceptions=True,
            )

        deduped_in_run: Dict[str, Dict[str, Any]] = {}
        for index, result in enumerate(results):
            source_name = self.config.feeds[index][0]
            if isinstance(result, Exception):
                print(f"[Error] Feed fetch failed for {source_name}: {result}")
                continue

            for item in result:
                deduped_in_run.setdefault(item["dedupe_hash"], item)

        ordered_items = sorted(
            deduped_in_run.values(),
            key=published_sort_key,
            reverse=True,
        )
        return [item for item in ordered_items if not self.storage.contains(item["dedupe_hash"])]

    @staticmethod
    def build_embed(item: Dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title=item["title"][:256],
            url=item["url"],
            description=item.get("summary") or f"Read more from {item['source']}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Read article", value=item["url"][:1024], inline=False)

        published_at = item.get("published_at")
        footer_parts = [item["source"]]
        if published_at:
            try:
                published_label = datetime.fromisoformat(
                    published_at.replace("Z", "+00:00")
                ).strftime("%Y-%m-%d")
                footer_parts.append(f"Published {published_label}")
            except ValueError:
                pass
        embed.set_footer(text=" | ".join(footer_parts))
        return embed

    @staticmethod
    def build_digest(items: Sequence[Dict[str, Any]]) -> Optional[str]:
        if not items:
            return None

        lines = ["Latest links:"]
        for item in items:
            lines.append(f"- {item['title']} <{item['url']}>")

        digest = "\n".join(lines)
        if len(digest) > 1900:
            digest = digest[:1897].rstrip() + "..."
        return digest

    @tasks.loop(time=UTC_POST_TIMES)
    async def poll_and_post(self) -> None:
        try:
            channel = await self.get_post_channel()
            if channel is None:
                return

            items_to_post = (await self.collect_new_items())[: self.config.max_posts_per_run]
            if not items_to_post:
                print("[Info] No new items to post")
                return

            posted_records: List[Dict[str, Any]] = []
            for index, item in enumerate(items_to_post):
                try:
                    message = await channel.send(
                        embed=self.build_embed(item),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    record = {
                        "source": item["source"],
                        "title": item["title"],
                        "url": item["url"],
                        "canonical_url": item["canonical_url"],
                        "published_at": item.get("published_at"),
                        "posted_at": utc_now_iso(),
                        "discord_message_id": str(message.id),
                    }
                    self.storage.record_post(record)
                    posted_records.append(record)
                    print(f"[Posted] {item['source']}: {item['title'][:80]}")
                except Exception as exc:
                    print(f"[Error] Failed to post {item['title'][:80]}: {exc}")

                if index < len(items_to_post) - 1:
                    await asyncio.sleep(self.config.post_delay_seconds)

            if self.config.post_text_digest and posted_records:
                digest = self.build_digest(posted_records)
                if digest:
                    await channel.send(
                        digest,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
        except Exception as exc:
            print(f"[Error] Poll cycle failed: {exc}")

    @poll_and_post.before_loop
    async def before_poll_and_post(self) -> None:
        await self.wait_until_ready()


def run_news_bot(config: NewsBotConfig) -> None:
    token = (os.getenv("DISCORD_TOKEN") or "").strip()
    if not token:
        raise SystemExit("ERROR: DISCORD_TOKEN not set in environment")
    if config.channel_id == 0:
        raise SystemExit("ERROR: CHANNEL_ID not set in environment")
    client = NewsBotClient(config)
    client.run(token)
