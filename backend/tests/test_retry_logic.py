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

            # Mock post to fail first, then succeed
            call_count = 0
            async def mock_post_fn(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise error
                return success_response

            mock_client.return_value.__aenter__.return_value.post = mock_post_fn

            with patch('backend.openrouter.asyncio.sleep', new_callable=AsyncMock):
                result = await query_model("test/model", [{"role": "user", "content": "Hi"}])

            assert result is not None
            assert result['content'] == 'Success'
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self):
        """Should not retry on 400 error."""
        with patch('backend.openrouter.httpx.AsyncClient') as mock_client:
            error_response = MagicMock()
            error_response.status_code = 400
            error_response.headers = {}
            error = httpx.HTTPStatusError("", request=MagicMock(), response=error_response)

            call_count = 0
            async def mock_post_fn(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                raise error

            mock_client.return_value.__aenter__.return_value.post = mock_post_fn

            result = await query_model("test/model", [{"role": "user", "content": "Hi"}])

            assert result is None
            assert call_count == 1  # No retry
