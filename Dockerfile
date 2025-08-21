FROM python:3.9-slim-bullseye

WORKDIR /app

COPY requirements.txt .

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libgtk-3-0 \
    libasound2 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers into /ms-playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install playwright \
    && python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8440

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8440"]
