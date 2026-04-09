from __future__ import annotations

import os
from typing import List, Tuple

from dotenv import load_dotenv

from news_core import NewsBotClient, NewsBotConfig

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
POLL_MINUTES = max(60, int(os.getenv("POLL_MINUTES", "180")))
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))
POST_DELAY_SECONDS = int(os.getenv("POST_DELAY_SECONDS", "5"))
ARCHIVE_PATH = os.getenv("ARCHIVE_PATH", "data/news_archive.jsonl")
DEDUPE_INDEX_PATH = os.getenv("DEDUPE_INDEX_PATH", "data/dedupe_index.json")
POST_TEXT_DIGEST = os.getenv("POST_TEXT_DIGEST", "false").lower() in {"1", "true", "yes", "on"}

# Keep this list structure so additional bots can reuse the same pipeline with different feeds.
FEEDS: List[Tuple[str, str]] = [
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
]
SCHEDULED_HOURS_UTC = (9, 17)


def build_config() -> NewsBotConfig:
    return NewsBotConfig(
        bot_name="hugging-face-bot",
        channel_id=CHANNEL_ID,
        poll_minutes=POLL_MINUTES,
        max_posts_per_run=MAX_POSTS_PER_RUN,
        post_delay_seconds=POST_DELAY_SECONDS,
        archive_path=ARCHIVE_PATH,
        dedupe_index_path=DEDUPE_INDEX_PATH,
        feeds=FEEDS,
        post_text_digest=POST_TEXT_DIGEST,
        scheduled_hours_utc=SCHEDULED_HOURS_UTC,
    )


def main() -> None:
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        raise SystemExit(1)
    if CHANNEL_ID == 0:
        print("ERROR: CHANNEL_ID not set in .env")
        raise SystemExit(1)

    client = NewsBotClient(build_config())
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
