from .research import perform_web_search


async def execute_search(query: str) -> str:
    """
    Execute web search and return results as string.

    Uses Tavily API via perform_web_search from research module.
    Returns fallback message if search fails or no API key is configured.
    """
    result = await perform_web_search(query)
    if result is None:
        return f"[No search results available for: {query}]"
    return result
