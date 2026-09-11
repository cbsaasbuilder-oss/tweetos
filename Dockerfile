FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 tweetos \
    && useradd --uid 10001 --gid tweetos --no-create-home --shell /usr/sbin/nologin tweetos \
    && mkdir -p /var/lib/tweetos/references \
    && chown -R tweetos:tweetos /var/lib/tweetos

WORKDIR /app
COPY SKILL.md ./
COPY references/guidelines.md references/guidelines.md
COPY scripts/telegram_bot.py scripts/telegram_bot.py
COPY scripts/archive_tweets.py scripts/archive_tweets.py

USER 10001:10001
ENTRYPOINT ["python", "scripts/telegram_bot.py"]
