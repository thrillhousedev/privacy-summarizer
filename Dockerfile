# Multi-stage build for Signal Summarizer
FROM debian:trixie-slim AS signal-cli-builder

# Install dependencies for signal-cli
RUN apt-get update && apt-get install -y \
    wget \
    openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Download and install signal-cli (native version for AMD64)
ARG SIGNAL_CLI_VERSION=0.13.21
RUN wget https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}-Linux-native.tar.gz \
    && tar xf signal-cli-${SIGNAL_CLI_VERSION}-Linux-native.tar.gz -C /opt

# Final stage
FROM python:3.11-slim

# Install Java runtime for signal-cli, SQLCipher dependencies, and curl for healthchecks
RUN apt-get update && apt-get install -y \
    openjdk-21-jre-headless \
    libsqlite3-0 \
    libsqlcipher-dev \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy signal-cli from builder stage
COPY --from=signal-cli-builder /opt/signal-cli/ /opt/signal-cli/
RUN ln -sf /opt/signal-cli/signal-cli /usr/local/bin/signal-cli

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for data
RUN mkdir -p /data /signal-cli-config

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV SIGNAL_CLI_CONFIG_DIR=/signal-cli-config

# Default command
CMD ["python", "-m", "src.main"]
