FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 agentguard \
    && useradd --uid 10001 --gid agentguard --no-create-home agentguard
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    AGENTGUARD_HOST=0.0.0.0 \
    AGENTGUARD_DB=/data/agentguard.db \
    PORT=8000
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY agentguard ./agentguard
COPY main.py ./main.py
COPY --from=frontend /build/dist ./frontend/dist
COPY deploy/entrypoint.sh /usr/local/bin/agentguard-entrypoint
RUN chmod 755 /usr/local/bin/agentguard-entrypoint && mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/health',timeout=4)"
ENTRYPOINT ["agentguard-entrypoint"]
CMD ["python", "main.py"]
