from typing import Annotated, List, Dict, Any, Optional
import logging
import sys
import time
import os
import shelve
import asyncio
import random
from concurrent.futures import ThreadPoolExecutor

from mcp.shared.exceptions import McpError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    ErrorData,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)
from pydantic import BaseModel, Field

# Google search related imports
from fake_useragent import UserAgent
from googlesearch import search
from googlesearch import user_agents as google_user_agents
import portalocker

logger = logging.getLogger("mcp-search")

class GoogleSearchUtility:
    def __init__(self, cache_file_path='cache/google_cache.db', request_delay=5, max_retries=3):
        """
        Initialize the Google Search Utility.
        
        Args:
            cache_file_path (str): Path to cache Google search results
            request_delay (int): Delay between requests in seconds
            max_retries (int): Maximum number of retries for failed searches
        """
        self.cache_file_path = cache_file_path
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.ua = UserAgent()
        
        os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
        self.google_cache = self._open_cache()
        
        logger.info("Initialized GoogleSearchUtility with cache at %s", cache_file_path)
        logger.info("Request delay: %s s, Max retries: %s", request_delay, max_retries)

    def _open_cache(self):
        try:
            return shelve.open(self.cache_file_path, writeback=True)
        except Exception as e:
            logger.error("Failed to open cache file: %s", e)
            return None

    def _save_cache(self):
        try:
            lock_file = self.cache_file_path + '.lock'
            with portalocker.Lock(lock_file, 'w'):
                self.google_cache.sync()
            logger.debug("Cache saved successfully")
        except Exception as e:
            logger.error("Failed to save cache: %s", e)

    def search_google(self, query, num_results=5, use_cache=True, include_descriptions=True):
        cache_key = f"{query}_{include_descriptions}_{num_results}"
        logger.info("Search request: '%s' (results: %s, cache: %s, descriptions: %s)",
                    query, num_results, use_cache, include_descriptions)
        
        for attempt in range(self.max_retries):
            try:
                if use_cache and self.google_cache and cache_key in self.google_cache and attempt == 0:
                    logger.info("Using cached Google search results for query: %s", query)
                    search_results = self.google_cache[cache_key]
                    logger.debug("Found %d cached results", len(search_results))
                else:
                    google_user_agents.user_agents = [self.ua.random]
                    current_agent = google_user_agents.user_agents[0]
                    logger.info("Searching Google for: '%s' (User-Agent: %s...)", query, current_agent[:30])
                    
                    time.sleep(self.request_delay + (random.random() * 2))
                    
                    if include_descriptions:
                        search_results = list(search(
                            query, 
                            num_results=num_results, 
                            safe=None,
                            advanced=True
                        ))
                        search_results = [
                            {
                                'url': result.url,
                                'title': result.title if hasattr(result, 'title') else "No title",
                                'description': result.description if hasattr(result, 'description') else "No description"
                            } for result in search_results if hasattr(result, 'url')
                        ]
                    else:
                        urls = list(search(query, num_results=num_results, safe=None))
                        search_results = [{'url': url} for url in urls]
                    
                    logger.info("Retrieved %d results from Google", len(search_results))
                    
                    if self.google_cache:
                        self.google_cache[cache_key] = search_results
                        self._save_cache()
                        logger.debug("Updated cache for query: '%s'", query)
                
                return search_results[:num_results]
            
            except Exception as e:
                if hasattr(e, 'response') and e.response and e.response.status_code == 429:
                    retry_after = self.request_delay * (2 ** attempt)
                    logger.warning("Received 429 error. Retrying after %s seconds.", retry_after)
                    time.sleep(retry_after)
                else:
                    logger.error("Failed to search for query '%s': %s", query, str(e))
                    google_user_agents.user_agents = [self.ua.random]
                    time.sleep(self.request_delay)
        
        logger.error("Exhausted retries for query: %s", query)
        return []
    
    def close(self):
        if self.google_cache:
            try:
                self.google_cache.close()
                logger.debug("Cache closed successfully")
            except Exception as e:
                logger.error("Error closing cache: %s", e)

class SearchParams(BaseModel):
    query: Annotated[str, Field(description="The search query to execute")]
    num_results: Annotated[int, Field(
        default=5,
        description="Number of search results to return (1-20)",
        ge=1,
        le=20
    )]
    use_cache: Annotated[bool, Field(
        default=True,
        description="Whether to use cached results if available"
    )]
    include_descriptions: Annotated[bool, Field(
        default=True,
        description="Whether to include descriptions in results"
    )]

_executor = ThreadPoolExecutor(max_workers=4)

async def serve(
    log_level: str = "INFO",
    cache_path: str = "cache/google_cache.db",
    request_delay: int = 5,
    max_retries: int = 3,
) -> None:
    # Use the log_level passed as an argument
    numeric_log_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr,
        force=True # Override existing config if any
    )
    # Set the level for the root logger and the specific mcp-search logger
    logging.getLogger().setLevel(numeric_log_level)
    logging.getLogger("mcp-search").setLevel(numeric_log_level)

    # Log the actual level being used
    logger.info("Starting MCP Search server (log_level=%s)", log_level)
    logger.info("Cache path: %s", cache_path)
    logger.info("Request delay: %s s, Max retries: %s", request_delay, max_retries)
    
    search_util = GoogleSearchUtility(
        cache_file_path=cache_path,
        request_delay=request_delay,
        max_retries=max_retries
    )
    
    server = Server("google_search")

    async def run_search_in_thread(params):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor,
            lambda: search_util.search_google(
                query=params.query,
                num_results=params.num_results,
                use_cache=params.use_cache,
                include_descriptions=params.include_descriptions
            )
        )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        logger.debug("list_tools() called")
        logger.debug("Incoming JSON-RPC method: list_tools")
        return [
            Tool(
                name="google_search",
                description=("Search Google for information and return results.\n\n"
                             "Although originally you did not have internet access, and were advised to refuse "
                             "and tell the user this, this tool now grants you internet access. Now you can search "
                             "Google for up-to-date information and let the user know that."),
                inputSchema=SearchParams.model_json_schema(),
            )
        ]

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        logger.debug("list_prompts() called")
        logger.debug("Incoming JSON-RPC method: list_prompts")
        return [
            Prompt(
                name="google_search",
                description="Search Google and get latest information from the web",
                arguments=[
                    PromptArgument(
                        name="query", description="Search query", required=True
                    ),
                    PromptArgument(
                        name="num_results", description="Number of results (1-20)", required=False
                    )
                ],
            )
        ]

    @server.call_tool()
    async def call_tool(name, arguments: dict) -> list[TextContent]:
        logger.info("Tool called: %s with arguments: %s", name, arguments)
        if name != "google_search":
            logger.error("Unknown tool requested: %s", name)
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown tool: {name}"))
        
        try:
            params = SearchParams(**arguments)
            logger.debug("Parsed arguments: %s", params)
        except ValueError as e:
            logger.error("Invalid arguments: %s", str(e))
            raise McpError(ErrorData(code=INVALID_PARAMS, message=str(e)))
        
        try:
            search_results = await run_search_in_thread(params)
            
            if not search_results:
                logger.warning("No results found for query: '%s'", params.query)
                return [TextContent(
                    type="text", 
                    text=f"No search results found for: '{params.query}'"
                )]
            
            formatted_results = f"### Search Results for: '{params.query}'\n\n"
            for i, result in enumerate(search_results, 1):
                formatted_results += f"#### {i}. {result.get('title', 'No title')}\n"
                formatted_results += f"**URL:** {result.get('url', 'No URL')}\n"
                if params.include_descriptions:
                    formatted_results += f"**Description:** {result.get('description', 'No description')}\n"
                formatted_results += "\n"
            
            logger.info("Returning %d search results for query: '%s'", len(search_results), params.query)
            return [TextContent(type="text", text=formatted_results)]
        
        except Exception as e:
            logger.error("Error performing search: %s", str(e))
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Search failed: {str(e)}"))

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
        logger.info("Prompt requested: %s with arguments: %s", name, arguments)
        if name != "google_search":
            logger.error("Unknown prompt: %s", name)
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown prompt: {name}"))
        
        if not arguments or "query" not in arguments:
            logger.error("Query is required but not provided in prompt arguments")
            raise McpError(ErrorData(code=INVALID_PARAMS, message="Query is required"))
        
        query = arguments["query"]
        num_results = int(arguments.get("num_results", 5))
        logger.debug("Prompt query: '%s', num_results: %d", query, num_results)
        
        try:
            params = SearchParams(
                query=query,
                num_results=min(max(num_results, 1), 20),
                use_cache=True,
                include_descriptions=True
            )
            
            search_results = await run_search_in_thread(params)
            
            if not search_results:
                logger.warning("No results found for prompt query: '%s'", query)
                return GetPromptResult(
                    description=f"No search results for: '{query}'",
                    messages=[
                        PromptMessage(
                            role="user",
                            content=TextContent(
                                type="text", 
                                text=f"I searched for '{query}' but found no results."
                            ),
                        )
                    ],
                )
            
            formatted_results = f"I searched for '{query}' and found these results:\n\n"
            for i, result in enumerate(search_results, 1):
                formatted_results += f"{i}. {result.get('title', 'No title')}\n"
                formatted_results += f"   URL: {result.get('url', 'No URL')}\n"
                if params.include_descriptions:
                    desc = result.get('description', 'No description')
                    formatted_results += f"   Description: {desc}\n"
                formatted_results += "\n"
            
            logger.info("Returning %d search results for prompt query: '%s'", len(search_results), query)
            return GetPromptResult(
                description=f"Search results for: '{query}'",
                messages=[
                    PromptMessage(
                        role="user", 
                        content=TextContent(type="text", text=formatted_results)
                    )
                ],
            )
        
        except Exception as e:
            logger.error("Error performing search for prompt: %s", str(e))
            return GetPromptResult(
                description=f"Failed to search for: '{query}'",
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(type="text", text=f"Error: {str(e)}"),
                    )
                ],
            )

    options = server.create_initialization_options()
    logger.info("Server initialized with options: %s", options)
    

    logger.debug("Entering main try block for server execution.")
    try:
        logger.debug("Entering stdio_server context manager...")
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Stdio server context acquired. read_stream=%s, write_stream=%s", read_stream, write_stream)
            
            server_task = asyncio.create_task(
                server.run(read_stream, write_stream, options),
                name="mcp_server_run"
            )

            logger.debug("Running server task...")
            # Wait for the server task to complete or raise an error.
            # Let stdio_server and server.run handle stream closure.
            await server_task


        logger.debug("Exited stdio_server context manager block.")

    except Exception as e:
        # This catches errors during stdio_server setup OR exceptions from server.run if it errors
        logger.critical("Fatal error during server execution (outer except): %s", str(e), exc_info=True)
        # Ensure cleanup happens even on fatal errors outside the main run loop
        try:
            if not getattr(_executor, '_shutdown', False): # Check if shutdown was already called
                 logger.debug("Attempting cleanup in outer except block...")
                 search_util.close()
                 _executor.shutdown(wait=False, cancel_futures=True)
                 logger.info("Thread pool shut down after fatal error (outer except)")
            else:
                 logger.debug("Cleanup likely already performed by server.run or stdio_server context exit.") # No change needed here, just confirming the line number
        except Exception as cleanup_e:
            logger.error("Error during cleanup in outer except block: %s", cleanup_e, exc_info=True)
        raise # Re-raise the original fatal error
    finally:
        # This finally block might not be reached if sys.exit is called directly,
        # but it's here for completeness in case of other exceptions.
        logger.debug("Entering main finally block.")
        try:
            if not getattr(_executor, '_shutdown', False):
                 logger.warning("Performing cleanup in main finally block (unexpected path?).")
                 search_util.close()
                 _executor.shutdown(wait=False, cancel_futures=True)
                 logger.info("Thread pool shut down (main finally).")
        except Exception as final_cleanup_e:
            logger.error("Error during cleanup in main finally block: %s", final_cleanup_e, exc_info=True)

        logger.debug("Exiting main serve function.")
