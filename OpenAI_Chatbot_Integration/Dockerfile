# Dockerfile (place this in the ROOT of your repo, next to requirements.txt)

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# (Optional but safe) CA certs for HTTPS calls (OpenAI, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app
COPY . .

# Cloud Run provides $PORT; default to 8080
ENV PORT=8080
EXPOSE 8080

# IMPORTANT: If your Flask app object isn't in app.py as "app",
# change "app:app" to "main:app" or "src.app:app" etc.
CMD ["gunicorn", "-b", "0.0.0.0:8080", "--workers=2", "--threads=4", "--timeout=0", "app:app"]