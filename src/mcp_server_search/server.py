from typing import Annotated, List, Dict, Any, Optional
import logging
import time
import os
import shelve
import random
import json

from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Google search related imports
from fake_useragent import UserAgent
from googlesearch import search
from googlesearch import user_agents as google_user_agents
import portalocker

logger = logging.getLogger("mcp-search")

# Define FastMCPError at the top of the file
class FastMCPError(Exception):
    def __init__(self, error_data):
        self.error_data = error_data
        super().__init__(str(error_data))

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

mcp = FastMCP(
    name="google_search",
    instructions="Provides a Google Search tool for LLMs and agents to retrieve up-to-date web results as structured JSON."
)

@mcp.tool(
    description="Search Google and return up-to-date web results as structured JSON.",
    tags={"search", "google", "web", "internet"},
    annotations={
        "title": "Google Search",
        "readOnlyHint": True,
        "openWorldHint": True
    }
)
def google_search_tool(
    query: Annotated[str, Field(description="The search query to execute")],
    num_results: Annotated[int, Field(default=5, description="Number of search results to return (1-20)", ge=1, le=20)] = 5,
    use_cache: Annotated[bool, Field(default=True, description="Whether to use cached results if available")] = True,
    include_descriptions: Annotated[bool, Field(default=True, description="Whether to include descriptions in results")] = True
) -> str:
    """
    Search Google and return structured JSON search results.
    
    Returns:
        str: A JSON string with the following structure:
            {
                "query": str,                # The search query
                "total_results": int,        # Number of results returned
                "results": [                 # List of result objects
                    {
                        "title": str,       # Title of the result
                        "url": str,         # URL of the result
                        "description": str  # Description (if available)
                    },
                    ...
                ]
            }
    """
    search_util = GoogleSearchUtility()
    try:
        results = search_util.search_google(
            query=query,
            num_results=num_results,
            use_cache=use_cache,
            include_descriptions=include_descriptions
        )
        response = {
            "query": query,
            "total_results": len(results),
            "results": []
        }
        for result in results:
            response["results"].append({
                "title": result.get('title') or 'No title',
                "url": result.get('url') or 'No URL',
                "description": result.get('description') or 'No description'
            })
        return json.dumps(response, ensure_ascii=False, indent=2)
    finally:
        search_util.close()

def main():
    mcp.run(transport="sse", host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
