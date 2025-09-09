FROM python:3.11-slim-bullseye

WORKDIR /app

COPY requirements.txt .

# Install system dependencies for Poppler (pdf2image), Pillow, python-magic, Chromium + Chromedriver
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    poppler-utils \
    libmagic1 \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set up Chromium headless environment variables
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
