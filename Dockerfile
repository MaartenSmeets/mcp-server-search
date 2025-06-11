FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /app/logs /app/cache

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

# Expose the port for the SSE
EXPOSE 8000

# Use Uvicorn to run the FastAPI app for MCP and health endpoint
CMD ["uvicorn", "mcp_server_search.server:api", "--host", "0.0.0.0", "--port", "8000"]