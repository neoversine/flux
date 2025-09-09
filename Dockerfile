FROM python:3.11-slim-bullseye

WORKDIR /app

COPY requirements.txt .

# Install system dependencies (Chrome + Poppler + Pillow)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    poppler-utils \
    libmagic1 \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    sed \
    procps \
    fonts-liberation \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome + Chromium driver
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y \
       google-chrome-stable \
       chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Environment
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
