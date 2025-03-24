# MCP Server Search

An MCP (Model Context Protocol) server that provides Google search functionality for AI models. This server allows models to search for up-to-date information from the web.

## Features

- Google search integration with caching
- Configurable request delays and retries to avoid rate limiting
- Support for both simple and advanced searches (with descriptions)
- Throttling and randomization to be a good web citizen

## Installation

### Using Docker (Recommended)

1. Build the Docker image:
   ```bash
   docker build -t mcp-server-search .
   ```

2. Create required directories for persistence:
   ```bash
   mkdir -p ./logs ./cache
   ```

3. Run the container:
   ```bash
   docker run --rm -i \
     -v "$(pwd)/logs:/app/logs" \
     -v "$(pwd)/cache:/app/cache" \
     mcp-server-search
   ```

The volumes ensure:
- Logs are persisted to `./logs` directory
- Search cache is persisted to `./cache` directory
- Both directories are automatically created by Docker if they don't exist

Note: The `-i` flag is required for MCP protocol communication, and `--rm` automatically removes the container when it exits.

### Cline Integration

To use this MCP server with Cline, add the following configuration to your Cline MCP settings file (located at `~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json` for VS Code):

```json
{
    "mcpServers": {
        "google_search": {
            "command": "docker",
            "args": [
                "run",
                "--rm",
                "-i",
                "mcp-server-search"
            ],
            "disabled": false,
            "alwaysAllow": []
        }
    }
}
```

This configuration:
- Sets up the search MCP server to run in a Docker container
- Uses the `--rm` flag to automatically remove the container when it exits
- Uses `-i` for interactive mode required by the MCP protocol
- Disables the server by default for security (set `disabled` to `false` to enable)
- Requires explicit approval for all tool uses (`alwaysAllow` is empty)

## Configuration

The server accepts the following command-line arguments:

- `--log-level`: Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO
- `--log-file`: Path to log file (default: stdout)
- `--cache-path`: Path to the search cache file (default: cache/google_cache.db)
- `--request-delay`: Delay between search requests in seconds (default: 5)
- `--max-retries`: Maximum number of retries for failed searches (default: 3)

## Usage

The server exposes the following MCP endpoints:

### Tools

- `google_search`: Search Google and return results. Results are presented in a formatted Markdown structure with titles, URLs, and descriptions (when enabled).

  Parameters:
  - `query` (string, required): The search query to execute
  - `num_results` (integer, optional): Number of results to return (min: 1, max: 20, default: 5)
  - `use_cache` (boolean, optional): Whether to use cached results if available (default: true)
  - `include_descriptions` (boolean, optional): Whether to include descriptions in results (default: true)

  Features:
  - Automatic request throttling and retry mechanism
  - Random user agent rotation for better request distribution
  - File-based caching with thread-safe access
  - Exponential backoff on rate limiting (HTTP 429)

### Prompts

- `google_search`: Search Google with the given query. Returns results in a conversational format.

  Parameters:
  - `query` (string, required): The search query to execute
  - `num_results` (integer, optional): Number of results to return (1-20, default: 5)

## About MCP

The Model Context Protocol (MCP) is a protocol for connecting Large Language Models (LLMs) with tools and data sources. Learn more at [github.com/modelcontextprotocol](https://github.com/modelcontextprotocol).