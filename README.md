# hugging-face-bot

A Discord bot that posts Hugging Face news links from the Hugging Face blog RSS feed into a channel on a schedule using a shared news pipeline.

- Feed source: `https://huggingface.co/blog/feed.xml`

## Setup

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create your `.env` file from the template:

```bash
cp .env.example .env
```

3. Fill in `.env`:

- **DISCORD_TOKEN**: your bot token (Discord Developer Portal → your app → Bot)
- **CHANNEL_ID**: the *text channel ID* you want the bot to post in  
  (Discord Developer Mode ON → right-click channel → Copy Channel ID)
- **MAX_POSTS_PER_RUN**: how many articles to post each run (default: 3, newest first). The bot runs twice daily at fixed UTC times (see Notes).
- **POST_DELAY_SECONDS**: delay between posts in seconds (default: 5)
- **ARCHIVE_PATH**: append-only `.jsonl` archive of every posted article
- **DEDUPE_INDEX_PATH**: JSON dedupe index keyed by `sha256(canonical_url)`
- **POST_TEXT_DIGEST**: optionally send a plain text digest after the embeds (`true`/`false`)

## Run

**Option A – Docker (recommended, works on Raspberry Pi 24/7):**

1. Create `.env` from the template and fill in your values (see Setup above).
2. Build and run:
   ```bash
   docker compose up -d
   ```
   Or build and run in the foreground to see logs:
   ```bash
   docker compose up --build
   ```
3. The archive and dedupe index are stored in a Docker volume (`bot-data`) so the bot can dedupe, search old links, and repost from history later.
4. **Raspberry Pi**: Docker images support arm64/armv7. Build and run directly on your Pi; `restart: unless-stopped` keeps it running 24/7 and auto-starts after reboot.

**Option B – terminal (one-off):**
```bash
source .venv/bin/activate
python bot.py
```

**Option C – PM2 (survives reboot without Docker):**

Use PM2 so the bot runs in the background and restarts on crash. PM2 uses the project’s `.venv`, so **don’t** run `python3 bot.py` directly—that uses system Python and will fail with missing modules.

1. Start the bot with PM2:
   ```bash
   cd /home/kali/discordbots/Hugging-face-news
   pm2 start ecosystem.config.cjs
   ```

2. Make the bot start automatically when the Pi boots:
   ```bash
   pm2 startup
   ```
   Run the **exact command** it prints (the one that starts with `sudo env ...`).

3. Save the current process list so PM2 restores it on reboot:
   ```bash
   pm2 save
   ```

Useful PM2 commands:
- `pm2 status` – list apps and status
- `pm2 logs hugging-face-bot` – view logs
- `pm2 restart hugging-face-bot` – restart the bot
- `pm2 stop hugging-face-bot` – stop the bot

## Structure

- `news_core.py`: shared pipeline logic for feed fetching, URL normalization, dedupe, archive storage, embeds, and `/latestlinks`
- `huggingface_news_bot.py`: Hugging Face feed config plus channel/env wiring
- `bot.py`: compatibility entrypoint so existing PM2 and manual commands still work

## Notes

- Scheduling matches **dev-news-bot**: `discord.ext.tasks` runs at **09:00 UTC** and **17:00 UTC** each day (same as 09:00 / 17:00 GMT when the UK is on GMT). Each run posts at most **3** items from new feed entries (configurable via `MAX_POSTS_PER_RUN`).
- It dedupes by `sha256(canonical_url)` instead of feed GUIDs, stores every posted link in an append-only `.jsonl` archive, and keeps a separate dedupe index.
- Discord posts use embeds with a clickable title, cleaned summary, explicit `Read article` field, and a footer with source plus published date.
- `/latestlinks` shows the last saved archive entries from Discord.
- If the feed is unreachable, the bot logs the error and retries at the next scheduled run.

