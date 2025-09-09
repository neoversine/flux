FROM python:3.11-slim-bullseye

WORKDIR /app

COPY requirements.txt .

# Install system dependencies for Poppler (for pdf2image), Pillow, and python-magic
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libmagic1 \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8010

CMD ["uvicorn", "flux.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
