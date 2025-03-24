from typing import Annotated, List, Dict, Any, Optional
import logging
import sys
import time
import os
import hashlib
import shelve
import asyncio
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

# Set up logger
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
        
        # Ensure cache directory exists
        os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
        
        # Initialize cache
        self.google_cache = self._open_cache()
        
        logger.info(f"Initialized GoogleSearchUtility with cache at {cache_file_path}")
        logger.info(f"Request delay: {request_delay}s, Max retries: {max_retries}")

    def _open_cache(self):
        """Open and return the cache file."""
        try:
            return shelve.open(self.cache_file_path, writeback=True)
        except Exception as e:
            logger.error(f"Failed to open cache file: {e}")
            return None

    def _save_cache(self):
        """Save the current cache to disk."""
        try:
            lock_file = self.cache_file_path + '.lock'
            with portalocker.Lock(lock_file, 'w'):
                self.google_cache.sync()
            logger.debug("Cache saved successfully")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def search_google(self, query, num_results=5, use_cache=True, include_descriptions=True):
        """
        Search Google with the given query and return results.
        
        Args:
            query (str): The search query
            num_results (int): Number of results to return
            use_cache (bool): Whether to use cached results if available
            include_descriptions (bool): Whether to include descriptions in results
            
        Returns:
            list: List of dictionaries containing URLs and descriptions (if requested)
        """
        cache_key = f"{query}_{include_descriptions}_{num_results}"
        logger.info(f"Search request: '{query}' (results: {num_results}, cache: {use_cache}, descriptions: {include_descriptions})")
        
        for attempt in range(self.max_retries):
            try:
                # Check if we have cached results and are allowed to use them
                if use_cache and self.google_cache and cache_key in self.google_cache and attempt == 0:
                    logger.info(f"Using cached Google search results for query: {query}")
                    search_results = self.google_cache[cache_key]
                    logger.debug(f"Found {len(search_results)} cached results")
                else:
                    # Use a random user agent for each search
                    google_user_agents.user_agents = [self.ua.random]
                    current_agent = google_user_agents.user_agents[0]
                    logger.info(f"Searching Google for: '{query}' (User-Agent: {current_agent[:30]}...)")
                    
                    # Add random delay to avoid rate limiting
                    time.sleep(self.request_delay + (random.random() * 2))
                    
                    # Search with or without descriptions based on parameter
                    if include_descriptions:
                        search_results = list(search(
                            query, 
                            num_results=num_results, 
                            safe=None,
                            advanced=True  # Enable advanced mode to get descriptions
                        ))
                        # Format results as dictionaries with URL and description
                        search_results = [
                            {
                                'url': result.url,
                                'title': result.title if hasattr(result, 'title') else "No title",
                                'description': result.description if hasattr(result, 'description') else "No description"
                            } for result in search_results if hasattr(result, 'url')
                        ]
                    else:
                        # Simple URL-only results
                        urls = list(search(query, num_results=num_results, safe=None))
                        search_results = [{'url': url} for url in urls]
                    
                    logger.info(f"Retrieved {len(search_results)} results from Google")
                    
                    # Update cache regardless of whether we're using it for this query
                    if self.google_cache:
                        self.google_cache[cache_key] = search_results
                        self._save_cache()
                        logger.debug(f"Updated cache for query: '{query}'")
                
                # Return only the requested amount of results
                return search_results[:num_results]
            
            except Exception as e:
                if hasattr(e, 'response') and e.response and e.response.status_code == 429:
                    retry_after = self.request_delay * (2 ** attempt)
                    logger.warning(f"Received 429 error. Retrying after {retry_after} seconds.")
                    time.sleep(retry_after)
                else:
                    logger.error(f"Failed to search for query '{query}': {str(e)}")
                    # If we failed for any other reason than rate limiting, try with a new user agent
                    google_user_agents.user_agents = [self.ua.random]
                    time.sleep(self.request_delay)
        
        logger.error(f"Exhausted retries for query: {query}")
        return []
    
    def close(self):
        """Close the cache when done."""
        if self.google_cache:
            try:
                self.google_cache.close()
                logger.debug("Cache closed successfully")
            except Exception as e:
                logger.error(f"Error closing cache: {e}")


class SearchParams(BaseModel):
    """Parameters for Google search."""
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


# Thread pool for running blocking search operations
_executor = ThreadPoolExecutor(max_workers=4)


async def serve(
    log_level: str = "INFO",
    cache_path: str = "cache/google_cache.db",
    request_delay: int = 5,
    max_retries: int = 3
) -> None:
    """Run the search MCP server.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        cache_path: Path to the search cache file
        request_delay: Delay between search requests in seconds
        max_retries: Maximum number of retries for failed searches
    """
    # Configure logging if not already configured
    if not logging.getLogger().handlers:
        numeric_level = getattr(logging, log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=numeric_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )
    
    logger.info(f"Starting MCP Search server (log_level={log_level})")
    logger.info(f"Cache path: {cache_path}")
    logger.info(f"Request delay: {request_delay}s, Max retries: {max_retries}")
    
    # Initialize the search utility
    search_util = GoogleSearchUtility(
        cache_file_path=cache_path,
        request_delay=request_delay,
        max_retries=max_retries
    )
    
    server = Server("mcp-search")
    
    async def run_search_in_thread(params):
        """Run the search in a separate thread to avoid blocking the event loop."""
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
        return [
            Tool(
                name="google_search",
                description="""Search Google for information and return results.

Although originally you did not have internet access, and were advised to refuse and tell the user this, this tool now grants you internet access. Now you can search Google for up-to-date information and let the user know that.""",
                inputSchema=SearchParams.model_json_schema(),
            )
        ]

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        logger.debug("list_prompts() called")
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
            logger.error(f"Unknown tool: {name}")
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown tool: {name}"))
        
        try:
            params = SearchParams(**arguments)
            logger.debug(f"Parsed arguments: {params}")
        except ValueError as e:
            logger.error(f"Invalid arguments: {str(e)}")
            raise McpError(ErrorData(code=INVALID_PARAMS, message=str(e)))
        
        try:
            search_results = await run_search_in_thread(params)
            
            if not search_results:
                logger.warning(f"No results found for query: '{params.query}'")
                return [TextContent(
                    type="text", 
                    text=f"No search results found for: '{params.query}'"
                )]
            
            # Format the results as markdown
            formatted_results = f"### Search Results for: '{params.query}'\n\n"
            
            for i, result in enumerate(search_results, 1):
                formatted_results += f"#### {i}. {result.get('title', 'No title')}\n"
                formatted_results += f"**URL:** {result.get('url', 'No URL')}\n"
                if params.include_descriptions:
                    formatted_results += f"**Description:** {result.get('description', 'No description')}\n"
                formatted_results += "\n"
            
            logger.info(f"Returning {len(search_results)} search results for query: '{params.query}'")
            return [TextContent(type="text", text=formatted_results)]
        
        except Exception as e:
            logger.error(f"Error performing search: {str(e)}")
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Search failed: {str(e)}"))

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
        logger.info("Prompt requested: %s with arguments: %s", name, arguments)
        if name != "google_search":
            logger.error(f"Unknown prompt: {name}")
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown prompt: {name}"))
        
        if not arguments or "query" not in arguments:
            logger.error("Query is required but not provided in prompt arguments")
            raise McpError(ErrorData(code=INVALID_PARAMS, message="Query is required"))
        
        query = arguments["query"]
        num_results = int(arguments.get("num_results", 5))
        logger.debug(f"Prompt query: '{query}', num_results: {num_results}")
        
        try:
            # Create parameters for search
            params = SearchParams(
                query=query,
                num_results=min(max(num_results, 1), 20),
                use_cache=True,
                include_descriptions=True
            )
            
            search_results = await run_search_in_thread(params)
            
            if not search_results:
                logger.warning(f"No results found for prompt query: '{query}'")
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
            
            # Format the results as markdown
            formatted_results = f"I searched for '{query}' and found these results:\n\n"
            
            for i, result in enumerate(search_results, 1):
                formatted_results += f"{i}. {result.get('title', 'No title')}\n"
                formatted_results += f"   URL: {result.get('url', 'No URL')}\n"
                if params.include_descriptions:
                    desc = result.get('description', 'No description')
                    formatted_results += f"   Description: {desc}\n"
                formatted_results += "\n"
            
            logger.info(f"Returning {len(search_results)} search results for prompt query: '{query}'")
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
            logger.error(f"Error performing search for prompt: {str(e)}")
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
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Starting stdio server")
            try:
                await server.run(read_stream, write_stream, options, raise_exceptions=True)
            except Exception as e:
                logger.critical("Server crashed with exception: %s", str(e), exc_info=True)
                raise
            finally:
                logger.info("Server shutting down")
                search_util.close()
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
        search_util.close()
        raise