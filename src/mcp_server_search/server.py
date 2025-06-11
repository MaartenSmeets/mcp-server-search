from typing import Annotated, List, Dict, Any
import logging
import json

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .config import settings
from .search_utility import GoogleSearchUtility

logger = logging.getLogger("mcp-search")

class FastMCPError(Exception):
    def __init__(self, error_data):
        self.error_data = error_data
        super().__init__(str(error_data))

class SearchParams(BaseModel):
    """
    Parameters for the Google Search tool.
    """
    query: Annotated[str, Field(description="The search query to execute")]
    num_results: Annotated[int, Field(
        default=settings.num_results,
        description="Number of search results to return (1-20)",
        ge=1,
        le=20
    )]
    use_cache: Annotated[bool, Field(
        default=settings.use_cache,
        description="Whether to use cached results if available"
    )]
    include_descriptions: Annotated[bool, Field(
        default=settings.include_descriptions,
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
    num_results: Annotated[int, Field(default=settings.num_results, description="Number of search results to return (1-20)", ge=1, le=20)] = settings.num_results,
    use_cache: Annotated[bool, Field(default=settings.use_cache, description="Whether to use cached results if available")] = settings.use_cache,
    include_descriptions: Annotated[bool, Field(default=settings.include_descriptions, description="Whether to include descriptions in results")] = settings.include_descriptions
) -> str:
    """
    Search Google and return structured JSON search results.

    Args:
        query (str): The search query to execute.
        num_results (int): Number of search results to return (1-20).
        use_cache (bool): Whether to use cached results if available.
        include_descriptions (bool): Whether to include descriptions in results.

    Returns:
        str: A JSON string with the following structure:
            {
                "query": str,
                "total_results": int,
                "results": [
                    {
                        "title": str,
                        "url": str,
                        "description": str
                    },
                    ...
                ]
            }
    """
    search_util = GoogleSearchUtility(
        cache_file_path=settings.cache_file_path,
        request_delay=settings.request_delay,
        max_retries=settings.max_retries
    )
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

from fastapi import APIRouter, FastAPI

health_router = APIRouter()

@health_router.get("/health")
async def health():
    """
    Health check endpoint.

    Returns:
        Dict[str, str]: A dictionary with the status of the application.
    """
    return {"status": "ok"}

# Create FastAPI app and mount MCP as ASGI app
app = FastAPI()
app.include_router(health_router)
app.mount("/", mcp.sse_app())

# Alias for Uvicorn entrypoint
api = app
