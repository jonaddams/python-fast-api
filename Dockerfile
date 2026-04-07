# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.12-slim

# System dependencies required by Nutrient SDK native code
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    fontconfig \
    libicu72 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY . .

EXPOSE 8080

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
