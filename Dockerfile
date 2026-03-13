# Hugging Face news Discord bot
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY bot.py .

# Run as non-root user
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

# seen.json is written at runtime; use a volume when running
ENTRYPOINT ["python", "-u", "bot.py"]
