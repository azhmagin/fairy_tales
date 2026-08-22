FROM mcr.microsoft.com/playwright/python:v1.47.0-noble
# Playwright base image already contains Chromium + fonts (incl. Cyrillic). Pin the tag to the playwright version in pyproject.

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY storybook ./storybook
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir . && fc-cache -f

USER pwuser
CMD ["python", "-m", "storybook", "bot"]
