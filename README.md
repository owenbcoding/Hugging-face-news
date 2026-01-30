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

```bash
source .venv/bin/activate
python bot.py
```

## Notes

- The bot stores seen items in `seen.json` to avoid reposting. This file is ignored by git.
- If the feed is temporarily unreachable or blocked, the bot logs the error and tries again on the next poll.

