# Tavily Search Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable real Tavily web search in the agentic iteration phase by replacing the placeholder `execute_search()` with existing Tavily integration.

**Architecture:** Reuse the complete Tavily implementation from `backend/research.py` (used in Stage 0 clarification). The `execute_search()` function will delegate to `perform_web_search()` and return a fallback message on failure instead of `None`.

**Tech Stack:** Python asyncio, Tavily API (via existing integration), httpx, pytest

---

## Task 1: Update Search Implementation

**Files:**
- Modify: `backend/search.py:1-8`

**Step 1: Verify current test fails with real implementation**

The test currently passes with the placeholder. First, verify we understand the current behavior.

Run: `pytest tests/test_search.py::test_execute_search_returns_string -v`
Expected: PASS (placeholder returns non-empty string)

**Step 2: Replace placeholder with Tavily integration**

Edit `backend/search.py`:

```python
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
```

**Step 3: Run test to verify it still passes**

Run: `pytest tests/test_search.py::test_execute_search_returns_string -v`
Expected: PASS (returns fallback message when no API key is configured)

**Step 4: Run all tests to ensure no regressions**

Run: `pytest tests/ -v`
Expected: All 3 tests pass

**Step 5: Commit**

```bash
git add backend/search.py
git commit -m "feat: integrate Tavily search into execute_search

Replace placeholder with real Tavily API integration via perform_web_search.
Returns fallback message when search fails or no API key is configured.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Update Documentation

**Files:**
- Modify: `CLAUDE.md:96-97`

**Step 1: Update CLAUDE.md to reflect search is now functional**

Edit the Backend Structure section in `CLAUDE.md`:

Find:
```markdown
- `backend/search.py`: Web search integration (placeholder for now)
  - `execute_search()`: Returns placeholder results, future integration point for Brave/DuckDuckGo API
```

Replace with:
```markdown
- `backend/search.py`: Web search integration via Tavily
  - `execute_search()`: Delegates to `perform_web_search()` from `research.py`, returns fallback message on failure
```

**Step 2: Commit documentation update**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md to reflect Tavily search integration

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Manual Verification (Optional)

**Prerequisites:**
- `SEARCH_API_KEY` set in `.env` with valid Tavily API key

**Step 1: Test search with real API key**

If you have a Tavily API key configured in `.env`, you can manually verify:

```bash
cd /Users/msbritt/repos/llm-council
python -m backend.main &
# Wait for server to start on port 8001
# In another terminal:
cd frontend
npm run dev &
# Wait for frontend to start on port 5173
# Open browser to http://localhost:5173
# Send a message with iteration enabled
# Check browser console and backend logs for search results
```

**Step 2: Verify fallback behavior without API key**

Temporarily rename `SEARCH_API_KEY` in `.env` (or remove it), restart backend, and verify that searches return the fallback message.

**Step 3: Restore configuration**

Restore `SEARCH_API_KEY` in `.env` if you changed it.

---

## Verification Checklist

- [ ] `pytest tests/test_search.py -v` passes
- [ ] All tests pass: `pytest tests/ -v`
- [ ] `backend/search.py` imports `perform_web_search` from `research`
- [ ] `execute_search()` returns non-None string in all cases
- [ ] Documentation updated in `CLAUDE.md`
- [ ] Two commits created (implementation + docs)

---

## Notes

**Graceful Degradation:** Without `SEARCH_API_KEY` in `.env`, searches will return `"[No search results available for: {query}]"` instead of failing. This allows the iteration phase to continue even when search is unavailable.

**Existing Integration:** The `perform_web_search()` function in `backend/research.py` already handles:
- Tavily API calls via httpx
- Result summarization using Gemini Flash
- Error handling and timeouts
- Batch execution support

We're simply reusing this battle-tested code instead of reimplementing it.
