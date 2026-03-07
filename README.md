# hugging-face-bot

A Discord bot that posts Hugging Face news links from the Hugging Face blog RSS feed into a channel on a schedule.

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
- **POLL_MINUTES**: poll interval (in minutes)

## Run

**Option A – terminal (one-off):**
```bash
source .venv/bin/activate
python bot.py
```

**Option B – PM2 (recommended; survives reboot):**

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

## Notes

- The bot stores seen items in `seen.json` to avoid reposting. This file is ignored by git.
- If the feed is temporarily unreachable or blocked, the bot logs the error and tries again on the next poll.

