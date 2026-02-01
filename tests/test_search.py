import pytest
from backend.search import execute_search


@pytest.mark.asyncio
async def test_execute_search_returns_string():
    result = await execute_search("python async")
    assert isinstance(result, str)
    assert len(result) > 0
