# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its browsers
RUN pip install playwright
RUN python3 -m playwright install

# Install additional dependencies for Playwright
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
    && rm -rf /var/lib/apt/lists/*


# Copy the rest of the application code
COPY . .

# Make port 8010 available to the world outside this container
EXPOSE 8010

# Define environment variable for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Run the application (replace with your actual command)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]

