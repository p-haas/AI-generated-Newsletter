# Use Python 3.12 slim image
FROM python:3.12-slim

# Set non-interactive frontend for apt to silence debconf warnings
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY utils ./utils
COPY templates ./templates

# Create directory for credentials and tokens
RUN mkdir -p /app/credentials

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FUNCTION_TARGET=main_handler

# Expose port (Cloud Run will set PORT env var)
EXPOSE 8080

# Use Functions Framework for production
CMD exec functions-framework --target=main_handler --port=$PORT --host=0.0.0.0 