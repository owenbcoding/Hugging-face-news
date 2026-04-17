from __future__ import annotations

import os
import sys
from typing import List, Tuple

# If run with system python, re-exec with project .venv so dependencies are found.
if not (getattr(sys, "base_prefix", sys.prefix) != sys.prefix):
    venv_python = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python"
    )
    if os.path.isfile(venv_python):
        os.execv(venv_python, [venv_python] + sys.argv)

from dotenv import load_dotenv

from news_core import NewsBotConfig, run_news_bot

load_dotenv()

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))
POST_DELAY_SECONDS = int(os.getenv("POST_DELAY_SECONDS", "5"))
ARCHIVE_PATH = os.getenv("ARCHIVE_PATH", "data/news_archive.jsonl")
DEDUPE_INDEX_PATH = os.getenv("DEDUPE_INDEX_PATH", "data/dedupe_index.json")
POST_TEXT_DIGEST = os.getenv("POST_TEXT_DIGEST", "false").lower() in {"1", "true", "yes", "on"}

# Keep this list structure so additional bots can reuse the same pipeline with different feeds.
FEEDS: List[Tuple[str, str]] = [
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
]


def build_config() -> NewsBotConfig:
    return NewsBotConfig(
        bot_name="hugging-face-bot",
        channel_id=CHANNEL_ID,
        max_posts_per_run=MAX_POSTS_PER_RUN,
        post_delay_seconds=POST_DELAY_SECONDS,
        archive_path=ARCHIVE_PATH,
        dedupe_index_path=DEDUPE_INDEX_PATH,
        feeds=FEEDS,
        post_text_digest=POST_TEXT_DIGEST,
    )


def main() -> None:
    run_news_bot(build_config())


if __name__ == "__main__":
    main()
