FROM python:3.11-slim-bullseye

WORKDIR /app

COPY requirements.txt .

# Install system dependencies for Poppler (for pdf2image), Pillow, and python-magic
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libmagic1 \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome for Selenium
RUN curl -sS -o - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable

# Set up Chrome headless environment variables
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8010

CMD ["uvicorn", "flux.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
