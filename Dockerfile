FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system vaultroute && adduser --system --ingroup vaultroute vaultroute \
    && mkdir -p /models /app \
    && chown -R vaultroute:vaultroute /models /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY data ./data

RUN pip install --no-cache-dir .

USER vaultroute

EXPOSE 8000

CMD ["uvicorn", "vaultroute_rag.main:app", "--host", "0.0.0.0", "--port", "8000"]

