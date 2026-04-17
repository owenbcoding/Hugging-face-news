# Hugging Face news Discord bot
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code — list each file explicitly (avoids empty/wrong COPY *.py on some builders)
COPY bot.py huggingface_news_bot.py news_core.py ./

# Fail the build immediately if sources are missing or broken (catches stale cache / bad context)
RUN ls -la /app/*.py && python -c "import huggingface_news_bot; import news_core; print('imports OK')"

# Run as non-root user
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

# Direct entry avoids an extra import hop via bot.py
ENTRYPOINT ["python", "-u", "huggingface_news_bot.py"]
