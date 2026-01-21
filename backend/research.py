"""Web research functionality for Stage 0 clarification round."""

import httpx
from typing import Dict, List, Any, Optional
from .config import SEARCH_API_KEY, SEARCH_API_URL, SEARCH_API_TYPE
from .openrouter import query_model


async def perform_web_search(query: str) -> Optional[str]:
    """
    Perform web search for a research query.

    Args:
        query: The search query

    Returns:
        Summarized search results, or None if search fails
    """
    if not SEARCH_API_KEY:
        print(f"Warning: No search API key configured, skipping research for: {query}")
        return None

    try:
        if SEARCH_API_TYPE == "tavily":
            return await _search_tavily(query)
        elif SEARCH_API_TYPE == "serpapi":
            return await _search_serpapi(query)
        else:
            print(f"Warning: Unknown search API type: {SEARCH_API_TYPE}")
            return None
    except Exception as e:
        print(f"Error performing web search for '{query}': {e}")
        return None


async def _search_tavily(query: str) -> Optional[str]:
    """Search using Tavily API."""
    # Use configured URL or default Tavily endpoint
    tavily_url = SEARCH_API_URL or "https://api.tavily.com/search"

    headers = {
        "Content-Type": "application/json",
    }

    payload = {
        "api_key": SEARCH_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 5
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                tavily_url,
                headers=headers,
                json=payload
            )
            response.raise_for_status()

            data = response.json()
            results = data.get('results', [])

            if not results:
                return None

            # Format results for summarization
            results_text = "\n\n".join([
                f"Source: {r.get('url', 'Unknown')}\n{r.get('content', '')}"
                for r in results[:3]  # Limit to top 3 results
            ])

            # Summarize the results
            return await _summarize_search_results(query, results_text)

    except Exception as e:
        print(f"Tavily search error: {e}")
        return None


async def _search_serpapi(query: str) -> Optional[str]:
    """Search using SerpAPI."""
    # Use configured URL or default SerpAPI endpoint
    serpapi_url = SEARCH_API_URL or "https://serpapi.com/search"

    params = {
        "api_key": SEARCH_API_KEY,
        "q": query,
        "num": 5
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                serpapi_url,
                params=params
            )
            response.raise_for_status()

            data = response.json()
            organic_results = data.get('organic_results', [])

            if not organic_results:
                return None

            # Format results for summarization
            results_text = "\n\n".join([
                f"Source: {r.get('link', 'Unknown')}\n{r.get('snippet', '')}"
                for r in organic_results[:3]  # Limit to top 3 results
            ])

            # Summarize the results
            return await _summarize_search_results(query, results_text)

    except Exception as e:
        print(f"SerpAPI search error: {e}")
        return None


async def _summarize_search_results(query: str, results_text: str) -> Optional[str]:
    """
    Use a fast model to summarize search results.

    Args:
        query: The original search query
        results_text: The raw search results

    Returns:
        Summarized text suitable for enriched context
    """
    summary_prompt = f"""Summarize the following web search results to answer this query: "{query}"

Provide a concise summary (2-3 sentences) of the key information found. Focus on facts and data relevant to the query.

Search results:
{results_text}

Summary:"""

    messages = [{"role": "user", "content": summary_prompt}]

    # Use a fast, cheap model for summarization
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback: return truncated raw results
        return results_text[:500] + "..."

    return response.get('content', '').strip()


async def perform_batch_research(research_queries: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Perform multiple research queries in parallel.

    Args:
        research_queries: List of dicts with 'id' and 'query' keys

    Returns:
        Dict mapping research IDs to summarized results
    """
    import asyncio

    # Create tasks for all research queries
    tasks = []
    query_ids = []
    for item in research_queries:
        tasks.append(perform_web_search(item['query']))
        query_ids.append(item['id'])

    # Wait for all to complete
    results = await asyncio.gather(*tasks)

    # Map IDs to results (only include successful searches)
    research_results = {}
    for query_id, result in zip(query_ids, results):
        if result is not None:
            research_results[query_id] = result

    return research_results
