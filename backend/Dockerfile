FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système + Ookla Speedtest CLI
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends gcc curl \
    && curl -sSL https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-x86_64.tgz \
       | tar xz -C /usr/local/bin speedtest \
    && rm -rf /var/lib/apt/lists/*

# Copier les requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Port d'écoute
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Commande de démarrage
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
