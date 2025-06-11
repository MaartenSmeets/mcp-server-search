from typing import List, Dict, Any, Optional
import logging
import time
import os
import shelve
import random
import json
import portalocker

from googlesearch import search
from googlesearch import user_agents as google_user_agents
from fake_useragent import UserAgent

from .config import settings

logger = logging.getLogger("mcp-search")

class GoogleSearchUtility:
    """
    A utility class for performing Google searches with caching and retry mechanisms.
    """

    def __init__(self, cache_file_path: str, request_delay: int, max_retries: int):
        """
        Initialize the Google Search Utility.

        Args:
            cache_file_path (str): Path to cache Google search results.
            request_delay (int): Delay between requests in seconds.
            max_retries (int): Maximum number of retries for failed searches.
        """
        self.cache_file_path = cache_file_path
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.ua = UserAgent()

        os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
        self.google_cache = self._open_cache()

        logger.info("Initialized GoogleSearchUtility with cache at %s", cache_file_path)
        logger.info("Request delay: %s s, Max retries: %s", request_delay, max_retries)

    def _open_cache(self) -> Optional[shelve.Shelf]:
        """
        Open the cache file for reading and writing.

        Returns:
            Optional[shelve.Shelf]: The opened cache file or None if an error occurs.
        """
        try:
            return shelve.open(self.cache_file_path, writeback=True)
        except Exception as e:
            logger.error("Failed to open cache file: %s", e)
            return None

    def _save_cache(self) -> None:
        """
        Save the cache file.
        """
        try:
            lock_file = self.cache_file_path + '.lock'
            with portalocker.Lock(lock_file, 'w'):
                self.google_cache.sync()
            logger.debug("Cache saved successfully")
        except Exception as e:
            logger.error("Failed to save cache: %s", e)

    def search_google(self, query: str, num_results: int = 5, use_cache: bool = True, include_descriptions: bool = True) -> List[Dict[str, Any]]:
        """
        Perform a Google search and return the results.

        Args:
            query (str): The search query.
            num_results (int): The number of results to return.
            use_cache (bool): Whether to use cached results if available.
            include_descriptions (bool): Whether to include descriptions in results.

        Returns:
            List[Dict[str, Any]]: A list of search results.
        """
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
                logger.error("Attempt %d failed for query '%s': %s", attempt + 1, query, str(e))
                if hasattr(e, 'response') and e.response and e.response.status_code == 429:
                    retry_after = self.request_delay * (2 ** attempt)
                    logger.warning("Received 429 error. Retrying attempt %d after %s seconds.", attempt + 1, retry_after)
                    time.sleep(retry_after)
                elif attempt < self.max_retries - 1:
                    # For other errors, log and wait before retrying
                    logger.warning("Retrying attempt %d after %s seconds.", attempt + 1, self.request_delay)
                    google_user_agents.user_agents = [self.ua.random] # Rotate user agent on error
                    time.sleep(self.request_delay)
                else:
                    # If it's the last attempt, log the final failure
                    logger.error("Exhausted retries for query: %s", query)
                    return [] # Return empty list after all retries fail

        logger.error("Exhausted retries for query: %s", query)
        return []

    def close(self) -> None:
        """
        Close the cache file.
        """
        if self.google_cache:
            try:
                self.google_cache.close()
                logger.debug("Cache closed successfully")
            except Exception as e:
                logger.error("Error closing cache: %s", e)