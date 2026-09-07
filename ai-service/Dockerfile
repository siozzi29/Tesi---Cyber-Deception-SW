FROM python:3.11-slim

WORKDIR /app

# Installa strumenti di compilazione essenziali per pacchetti scientifici (numpy, scikit-learn, ecc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    gcc \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Aggiorna pip, setuptools e wheel prima di installare i requirements
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copia e installa le dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il resto dell'AI service
COPY . .

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]