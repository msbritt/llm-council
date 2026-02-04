# OpenRouter Retry Logic Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add retry logic with exponential backoff to handle transient OpenRouter API failures (500 errors, rate limits, timeouts) gracefully, improving reliability without significantly impacting latency.

**Architecture:** Implement retry logic directly in `query_model()` so all callers (iteration phase, stage 1, stage 2, stage 3) automatically benefit. Use exponential backoff with jitter to prevent thundering herd problems.

**Tech Stack:** Python asyncio, httpx (existing)

---

## Context: What Exists

### Current State

**Backend (`backend/openrouter.py`):**
- `query_model()`: Makes single API call, returns `None` on any failure
- `query_models_parallel()`: Calls `query_model()` for multiple models via `asyncio.gather()`
- Generic exception handling - no distinction between retryable vs non-retryable errors
- No retry logic

**Current Error Handling:**
```python
except Exception as e:
    print(f"Error querying model {model}: {e}")
    return None
```

### Problems to Fix

1. **Transient failures cause total model loss**: A single 500 error means the model's response is lost
2. **No rate limit handling**: 429 errors should respect Retry-After header
3. **No distinction between error types**: 500 (retry) vs 401 (don't retry) treated the same
4. **Poor observability**: Can't tell if failures were retried or how many attempts were made

---

## Design Decisions

### Retry Strategy

| Error Type | Retry? | Delay Strategy | Max Attempts |
|------------|--------|----------------|--------------|
| 429 (Rate Limit) | Yes | Use Retry-After header, fallback to 2s, 5s | 3 |
| 500, 502, 503, 504 | Yes | Exponential backoff: 1s, 2s, 4s | 3 |
| Timeout/Connection | Yes | Exponential backoff: 1s, 2s, 4s | 3 |
| 400, 401, 403, 404 | No | N/A | 1 |
| Other client errors | No | N/A | 1 |

### Exponential Backoff Formula

```python
delay = min(base_delay * (2 ** attempt), max_delay) + jitter
# where jitter = random(0, 0.5 * delay)
```

**Parameters:**
- `base_delay`: 1.0 seconds
- `max_delay`: 8.0 seconds (cap)
- `max_attempts`: 3 (includes initial attempt, so 2 retries max)
- `jitter`: 0-50% of calculated delay (prevents thundering herd)

### Configuration

Add to `config.py`:
```python
# Retry configuration for OpenRouter API calls
RETRY_MAX_ATTEMPTS = 3        # Total attempts (1 initial + 2 retries)
RETRY_BASE_DELAY = 1.0        # Base delay in seconds
RETRY_MAX_DELAY = 8.0         # Maximum delay cap in seconds
RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]
```

---

## Task 1: Add Retry Configuration

**Files:**
- Modify: `backend/config.py`

**Step 1: Add retry constants**

Add after existing configuration:

```python
# Retry configuration for OpenRouter API calls
RETRY_MAX_ATTEMPTS = 3        # Total attempts (1 initial + 2 retries)
RETRY_BASE_DELAY = 1.0        # Base delay in seconds
RETRY_MAX_DELAY = 8.0         # Maximum delay cap in seconds
RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]
```

**Step 2: Verify config imports**

```bash
uv run python -c "from backend.config import RETRY_MAX_ATTEMPTS; print('OK')"
```

**Step 3: Commit**

```bash
git add backend/config.py
git commit -m "feat: add retry configuration for OpenRouter API calls"
```

---

## Task 2: Implement Retry Logic in query_model()

**Files:**
- Modify: `backend/openrouter.py`

**Step 1: Add imports and helper function**

```python
import asyncio
import random
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
```

**Step 2: Rewrite query_model() with retry logic**

```python
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
```

**Step 3: Verify module imports**

```bash
uv run python -c "from backend.openrouter import query_model; print('OK')"
```

**Step 4: Commit**

```bash
git add backend/openrouter.py
git commit -m "feat: add retry logic with exponential backoff to query_model"
```

---

## Task 3: Add Logging for Retry Observability

**Files:**
- Modify: `backend/openrouter.py`

**Step 1: Enhance logging with structured format**

The retry logs should be easily grepable:
- `[RETRY]` prefix for retry attempts
- `[ERROR]` prefix for final failures
- Include model name, attempt number, delay

This is already included in Task 2 code above. Verify the logging works:

```python
# Expected log output for a retry scenario:
# [RETRY] Model anthropic/claude-opus-4.5 attempt 1 failed: 500 Internal Server Error. Retrying in 1.3s...
# [RETRY] Model anthropic/claude-opus-4.5 succeeded on attempt 2
```

**Step 2: Add summary logging for parallel queries (optional enhancement)**

In `query_models_parallel()`, add summary:

```python
async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.
    """
    import asyncio

    tasks = [query_model(model, messages) for model in models]
    responses = await asyncio.gather(*tasks)

    result = {model: response for model, response in zip(models, responses)}

    # Log summary
    succeeded = sum(1 for r in responses if r is not None)
    failed = len(responses) - succeeded
    if failed > 0:
        print(f"[SUMMARY] Parallel query: {succeeded}/{len(models)} models succeeded, {failed} failed")

    return result
```

**Step 3: Commit**

```bash
git add backend/openrouter.py
git commit -m "feat: add structured logging for retry observability"
```

---

## Task 4: Test Retry Logic

**Files:**
- Create: `backend/tests/test_retry_logic.py`

**Step 1: Create test file**

```python
"""Tests for OpenRouter retry logic."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from backend.openrouter import query_model, _calculate_retry_delay, _is_retryable_error


class TestCalculateRetryDelay:
    """Test delay calculation."""

    def test_exponential_backoff(self):
        """Delay should increase exponentially."""
        delay_0 = _calculate_retry_delay(0)
        delay_1 = _calculate_retry_delay(1)
        delay_2 = _calculate_retry_delay(2)

        # Base delays: 1s, 2s, 4s (plus jitter)
        assert 1.0 <= delay_0 <= 1.5  # 1s + up to 50% jitter
        assert 2.0 <= delay_1 <= 3.0  # 2s + up to 50% jitter
        assert 4.0 <= delay_2 <= 6.0  # 4s + up to 50% jitter

    def test_respects_retry_after(self):
        """Should use Retry-After header when provided."""
        delay = _calculate_retry_delay(0, retry_after=10.0)
        assert 10.0 <= delay <= 15.0  # 10s + up to 50% jitter

    def test_max_delay_cap(self):
        """Delay should be capped at max."""
        delay = _calculate_retry_delay(10)  # Would be 1024s without cap
        assert delay <= 12.0  # 8s max + 50% jitter


class TestIsRetryableError:
    """Test error classification."""

    def test_500_is_retryable(self):
        """500 errors should be retryable."""
        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        error = httpx.HTTPStatusError("", request=MagicMock(), response=response)

        is_retryable, retry_after = _is_retryable_error(error)
        assert is_retryable is True
        assert retry_after is None

    def test_429_extracts_retry_after(self):
        """429 should extract Retry-After header."""
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "5"}
        error = httpx.HTTPStatusError("", request=MagicMock(), response=response)

        is_retryable, retry_after = _is_retryable_error(error)
        assert is_retryable is True
        assert retry_after == 5.0

    def test_400_not_retryable(self):
        """400 errors should not be retryable."""
        response = MagicMock()
        response.status_code = 400
        response.headers = {}
        error = httpx.HTTPStatusError("", request=MagicMock(), response=response)

        is_retryable, _ = _is_retryable_error(error)
        assert is_retryable is False

    def test_timeout_is_retryable(self):
        """Timeout errors should be retryable."""
        error = httpx.ReadTimeout("")
        is_retryable, _ = _is_retryable_error(error)
        assert is_retryable is True


class TestQueryModelRetry:
    """Test retry behavior in query_model."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Should return immediately on success."""
        with patch('backend.openrouter.httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'choices': [{'message': {'content': 'Hello'}}]
            }
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await query_model("test/model", [{"role": "user", "content": "Hi"}])

            assert result is not None
            assert result['content'] == 'Hello'

    @pytest.mark.asyncio
    async def test_retries_on_500(self):
        """Should retry on 500 error and succeed on second attempt."""
        with patch('backend.openrouter.httpx.AsyncClient') as mock_client:
            # First call fails with 500
            error_response = MagicMock()
            error_response.status_code = 500
            error_response.headers = {}
            error = httpx.HTTPStatusError("", request=MagicMock(), response=error_response)

            # Second call succeeds
            success_response = MagicMock()
            success_response.json.return_value = {
                'choices': [{'message': {'content': 'Success'}}]
            }
            success_response.raise_for_status = MagicMock()

            mock_post = AsyncMock(side_effect=[error, success_response])
            mock_client.return_value.__aenter__.return_value.post = mock_post

            with patch('backend.openrouter.asyncio.sleep', new_callable=AsyncMock):
                result = await query_model("test/model", [{"role": "user", "content": "Hi"}])

            assert result is not None
            assert result['content'] == 'Success'
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self):
        """Should not retry on 400 error."""
        with patch('backend.openrouter.httpx.AsyncClient') as mock_client:
            error_response = MagicMock()
            error_response.status_code = 400
            error_response.headers = {}
            error = httpx.HTTPStatusError("", request=MagicMock(), response=error_response)

            mock_post = AsyncMock(side_effect=error)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await query_model("test/model", [{"role": "user", "content": "Hi"}])

            assert result is None
            assert mock_post.call_count == 1  # No retry
```

**Step 2: Run tests**

```bash
uv run python -m pytest backend/tests/test_retry_logic.py -v
```

**Step 3: Commit**

```bash
git add backend/tests/test_retry_logic.py
git commit -m "test: add unit tests for retry logic"
```

---

## Task 5: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add retry behavior section**

Add under "Backend Structure" section:

```markdown
**Retry Logic (`openrouter.py`)**

The `query_model()` function includes retry logic for transient failures:

- **Retryable errors:** 429 (rate limit), 500, 502, 503, 504 (server errors), timeouts
- **Not retried:** 400, 401, 403, 404 (client errors)
- **Strategy:** Exponential backoff (1s, 2s, 4s) with 50% jitter
- **Max attempts:** 3 (1 initial + 2 retries)
- **Rate limits:** Respects Retry-After header when present

Configuration in `config.py`:
- `RETRY_MAX_ATTEMPTS`: Total attempts including initial
- `RETRY_BASE_DELAY`: Starting delay (1.0s)
- `RETRY_MAX_DELAY`: Maximum delay cap (8.0s)
- `RETRYABLE_STATUS_CODES`: List of HTTP codes to retry
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add retry logic documentation to CLAUDE.md"
```

---

## Verification Checklist

- [ ] Retry config added to config.py
- [ ] _calculate_retry_delay() returns correct delays
- [ ] _is_retryable_error() classifies errors correctly
- [ ] query_model() retries on 500 errors
- [ ] query_model() respects Retry-After header on 429
- [ ] query_model() does NOT retry on 400 errors
- [ ] Retry logs are visible with [RETRY] prefix
- [ ] All tests pass
- [ ] Documentation updated

---

## Rollback Plan

If issues arise:

```bash
# Revert retry changes
git log --oneline  # Find commit before retry changes
git revert <commit-hash>

# Or disable retries temporarily by setting:
RETRY_MAX_ATTEMPTS = 1  # in config.py
```

---

## Future Enhancements

1. **Circuit breaker:** Stop retrying if failure rate exceeds threshold
2. **Metrics:** Track retry rates per model for monitoring
3. **Per-model retry config:** Some models may need different settings
4. **Retry budget:** Limit total retry time across all models in parallel
