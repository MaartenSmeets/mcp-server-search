import hashlib
import logging
import os
import random
import shelve
import time
from fake_useragent import UserAgent
from googlesearch import search
from googlesearch import user_agents as google_user_agents
import portalocker

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
        
        # Configure logger if not already configured
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, 
                              format='%(asctime)s - %(levelname)s - %(message)s')

    def _open_cache(self):
        """Open and return the cache file."""
        try:
            return shelve.open(self.cache_file_path, writeback=True)
        except Exception as e:
            logging.error(f"Failed to open cache file: {e}")
            return None

    def _save_cache(self):
        """Save the current cache to disk."""
        try:
            with portalocker.Lock(self.cache_file_path + '.lock', 'w'):
                self.google_cache.sync()
        except Exception as e:
            logging.error(f"Failed to save cache: {e}")

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
        cache_key = f"{query}_{include_descriptions}"
        
        for attempt in range(self.max_retries):
            try:
                # Check if we have cached results and are allowed to use them
                if use_cache and cache_key in self.google_cache and attempt == 0:
                    logging.info(f"Using cached Google search results for query: {query}")
                    search_results = self.google_cache[cache_key]
                else:
                    # Use a random user agent for each search
                    google_user_agents.user_agents = [self.ua.random]
                    logging.info(f"Searching Google for: {query}")
                    
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
                                'title': result.title,
                                'description': result.description
                            } for result in search_results
                        ]
                    else:
                        # Simple URL-only results
                        urls = list(search(query, num_results=num_results, safe=None))
                        search_results = [{'url': url} for url in urls]
                    
                    # Update cache regardless of whether we're using it for this query
                    self.google_cache[cache_key] = search_results
                    self._save_cache()
                
                # Return only the requested amount of results
                return search_results[:num_results]
            
            except Exception as e:
                if hasattr(e, 'response') and e.response and e.response.status_code == 429:
                    retry_after = self.request_delay * (2 ** attempt)
                    logging.info(f"Received 429 error. Retrying after {retry_after} seconds.")
                    time.sleep(retry_after)
                else:
                    logging.error(f"Failed to search for query '{query}': {e}")
                    # If we failed for any other reason than rate limiting, try with a new user agent
                    google_user_agents.user_agents = [self.ua.random]
                    time.sleep(self.request_delay)
        
        logging.error(f"Exhausted retries for query: {query}")
        return []
    
    def close(self):
        """Close the cache when done."""
        if self.google_cache:
            self.google_cache.close()

# Example usage
if __name__ == "__main__":
    search_util = GoogleSearchUtility()
    try:
        # Example with descriptions and using cache
        results = search_util.search_google(
            "Python programming tutorials", 
            num_results=3, 
            use_cache=True,
            include_descriptions=True
        )
        
        print("Search results with descriptions:")
        for result in results:
            print(f"Title: {result.get('title', 'N/A')}")
            print(f"URL: {result.get('url', 'N/A')}")
            print(f"Description: {result.get('description', 'N/A')}")
            print("-" * 50)
        
        # Example without using cache but still updating it
        results_no_cache = search_util.search_google(
            "Machine learning basics", 
            num_results=2, 
            use_cache=False,
            include_descriptions=True
        )
        
        print("\nForced fresh search results:")
        for result in results_no_cache:
            print(f"Title: {result.get('title', 'N/A')}")
            print(f"URL: {result.get('url', 'N/A')}")
            print(f"Description: {result.get('description', 'N/A')}")
            print("-" * 50)
    finally:
        search_util.close()
