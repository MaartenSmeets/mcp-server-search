FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /app/logs /app/cache

# Create a virtual environment
RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

# Upgrade pip
RUN pip install --upgrade pip

# Copy requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project source code
COPY . .

# Install the project itself
RUN pip install --no-cache-dir .

# Set up volumes for logs and cache
VOLUME ["/app/logs", "/app/cache"]

# Set the entrypoint to the installed command with logging enabled
ENTRYPOINT ["mcp-server-search", "--log-level", "INFO", "--log-file", "/app/logs/mcp-search.log"]

# Default command can be overridden
CMD []