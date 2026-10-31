FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
COPY data ./data
COPY certs ./certs
RUN pip install --no-cache-dir -e .
ENV CAMPAIGN_DB_PATH=/app/var/campaigns.db CAMPAIGN_LOG_PATH=/app/var/agent_actions.jsonl CAMPAIGN_IMAGE_DIR=/app/var/images
RUN mkdir -p /app/var
