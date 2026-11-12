FROM python:3.9-slim

WORKDIR /app

# Install wkhtmltopdf for ticket generation and postgresql-client for pg_isready health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV PYTHONUNBUFFERED=1

RUN chmod +x server.sh worker.sh

EXPOSE 8000
