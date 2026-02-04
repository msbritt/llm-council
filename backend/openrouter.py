"""OpenRouter API client for making LLM requests."""

import asyncio
import random
import httpx
from typing import List, Dict, Any, Optional
from .config import (
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    RETRY_MAX_ATTEMPTS,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    RETRYABLE_STATUS_CODES,
)


def _calculate_retry_delay(attempt: int, retry_after: Optional[float] = None) -> float:
    """
    Calculate delay before next retry attempt.

    Uses exponential backoff with jitter, respecting Retry-After header if present.
    """
    if retry_after is not None:
        # Use server-specified delay for rate limits
        base = retry_after
    else:
        # Exponential backoff: 1s, 2s, 4s, ...
        base = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)

    # Add jitter (0-50% of base delay) to prevent thundering herd
    jitter = random.uniform(0, 0.5 * base)
    return base + jitter


def _is_retryable_error(exception: Exception) -> tuple[bool, Optional[float]]:
    """
    Determine if an exception is retryable and extract Retry-After if present.

    Returns:
        (is_retryable, retry_after_seconds)
    """
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code
        if status_code in RETRYABLE_STATUS_CODES:
            # Check for Retry-After header (common with 429)
            retry_after = exception.response.headers.get("Retry-After")
            if retry_after:
                try:
                    return True, float(retry_after)
                except ValueError:
                    pass
            return True, None
        return False, None

    # Network errors, timeouts are retryable
    if isinstance(exception, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
        return True, None

    # Unknown errors - don't retry
    return False, None


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API with retry logic.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    last_exception = None

    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    OPENROUTER_API_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

                data = response.json()
                message = data['choices'][0]['message']

                if attempt > 0:
                    print(f"[RETRY] Model {model} succeeded on attempt {attempt + 1}")

                return {
                    'content': message.get('content'),
                    'reasoning_details': message.get('reasoning_details')
                }

        except Exception as e:
            last_exception = e
            is_retryable, retry_after = _is_retryable_error(e)

            if not is_retryable:
                print(f"[ERROR] Model {model} failed with non-retryable error: {e}")
                return None

            # Check if we have more attempts
            if attempt < RETRY_MAX_ATTEMPTS - 1:
                delay = _calculate_retry_delay(attempt, retry_after)
                print(f"[RETRY] Model {model} attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                print(f"[ERROR] Model {model} failed after {RETRY_MAX_ATTEMPTS} attempts: {e}")

    return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # Create tasks for all models
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
