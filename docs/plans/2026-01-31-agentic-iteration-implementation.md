# Agentic Iteration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace synchronized Stage 0/1 with independent per-model agentic loops where each council model iterates autonomously.

**Architecture:** Each model runs up to N rounds (default 3), requesting searches and asking questions independently. Chairman aggregates questions per round. Models signal READY when satisfied or hit max rounds. Then proceed to existing Stage 2/3 evaluation.

**Tech Stack:** Python 3.9+, FastAPI, asyncio, React 18, Server-Sent Events (SSE)

---

## Task 1: Backend - Add Iteration Configuration

**Files:**
- Modify: `backend/config.py`

**Step 1: Add default iteration configuration**

```python
# Add after CHAIRMAN_MODEL definition
DEFAULT_MAX_ITERATIONS = 3
ITERATION_TIMEOUT_SECONDS = 60  # Per model per round
```

**Step 2: Verify configuration loads**

Run: `python -m backend.main` (Ctrl+C after startup)
Expected: No import errors

**Step 3: Commit**

```bash
git add backend/config.py
git commit -m "feat: add iteration configuration defaults"
```

---

## Task 2: Backend - Define Iteration Data Structures

**Files:**
- Create: `backend/iteration_types.py`

**Step 1: Write type definitions for iteration responses**

```python
from typing import Literal, Optional
from pydantic import BaseModel


class ModelIterationRequest(BaseModel):
    """What a model requests during an iteration."""
    status: Literal["needs_info", "ready"]
    searches: list[str] = []
    questions: list[str] = []
    response: Optional[str] = None  # Only present if status == "ready"
    reasoning: Optional[str] = None  # Optional reasoning trace


class ModelRoundState(BaseModel):
    """Tracks a model's state across rounds."""
    model_id: str
    current_round: int
    is_ready: bool
    accumulated_searches: list[dict] = []  # [{"query": str, "results": str}]
    accumulated_questions: list[dict] = []  # [{"q": str, "a": str}]
    final_response: Optional[str] = None


class RoundAggregation(BaseModel):
    """Chairman's aggregation of a round's requests."""
    search_queries: list[str]
    user_questions: list[dict]  # [{"text": str, "asked_by": [model_ids]}]
    search_results: dict[str, str]  # query -> results
```

**Step 2: Verify types import correctly**

Run: `python -c "from backend.iteration_types import ModelIterationRequest; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add backend/iteration_types.py
git commit -m "feat: add iteration data structures"
```

---

## Task 3: Backend - Search Integration (Placeholder)

**Files:**
- Create: `backend/search.py`

**Step 1: Write the failing test**

```python
# tests/test_search.py
import pytest
from backend.search import execute_search


@pytest.mark.asyncio
async def test_execute_search_returns_string():
    result = await execute_search("python async")
    assert isinstance(result, str)
    assert len(result) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_search.py::test_execute_search_returns_string -v`
Expected: FAIL with "ModuleNotFoundError" or "function not defined"

**Step 3: Write minimal implementation**

```python
# backend/search.py
async def execute_search(query: str) -> str:
    """
    Execute web search and return results as string.

    For now, returns placeholder. Future: integrate Brave/DuckDuckGo API.
    """
    return f"[Search results placeholder for: {query}]"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_search.py::test_execute_search_returns_string -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_search.py backend/search.py
git commit -m "feat: add search execution placeholder"
```

---

## Task 4: Backend - Chairman Question Aggregation

**Files:**
- Create: `backend/aggregation.py`
- Test: `tests/test_aggregation.py`

**Step 1: Write the failing test**

```python
# tests/test_aggregation.py
from backend.aggregation import aggregate_questions


def test_aggregate_questions_deduplicates():
    questions_by_model = {
        "gpt-5": ["What's the budget?", "Timeline?"],
        "claude": ["What is the budget?", "Any constraints?"],
        "gemini": ["Timeline?"]
    }

    result = aggregate_questions(questions_by_model)

    # Should deduplicate similar questions
    assert len(result) == 3
    assert any("budget" in q["text"].lower() for q in result)

    # Should track who asked
    budget_q = [q for q in result if "budget" in q["text"].lower()][0]
    assert set(budget_q["asked_by"]) == {"gpt-5", "claude"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_aggregation.py::test_aggregate_questions_deduplicates -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/aggregation.py
def aggregate_questions(questions_by_model: dict[str, list[str]]) -> list[dict]:
    """
    Aggregate and deduplicate questions from multiple models.

    Returns: [{"text": str, "asked_by": [model_ids]}]
    """
    # Simple deduplication by lowercase normalization
    question_map = {}

    for model_id, questions in questions_by_model.items():
        for q in questions:
            normalized = q.lower().strip().rstrip("?")

            if normalized not in question_map:
                question_map[normalized] = {
                    "text": q,  # Keep original formatting
                    "asked_by": []
                }

            if model_id not in question_map[normalized]["asked_by"]:
                question_map[normalized]["asked_by"].append(model_id)

    return list(question_map.values())
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_aggregation.py::test_aggregate_questions_deduplicates -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_aggregation.py backend/aggregation.py
git commit -m "feat: add question aggregation logic"
```

---

## Task 5: Backend - Single Round Execution Logic

**Files:**
- Modify: `backend/council.py`
- Test: `tests/test_council_iteration.py`

**Step 1: Write the failing test**

```python
# tests/test_council_iteration.py
import pytest
from backend.council import execute_single_round
from backend.iteration_types import ModelRoundState


@pytest.mark.asyncio
async def test_execute_single_round_collects_requests():
    user_query = "What's the capital of France?"
    model_states = [
        ModelRoundState(model_id="test-model-1", current_round=1, is_ready=False),
        ModelRoundState(model_id="test-model-2", current_round=1, is_ready=False)
    ]

    result = await execute_single_round(user_query, model_states, round_num=1)

    assert "model_requests" in result
    assert "aggregated_questions" in result
    assert "search_results" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_council_iteration.py::test_execute_single_round_collects_requests -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# Add to backend/council.py

from .iteration_types import ModelIterationRequest, ModelRoundState
from .aggregation import aggregate_questions
from .search import execute_search
from .openrouter import query_model
import asyncio


async def execute_single_round(
    user_query: str,
    model_states: list[ModelRoundState],
    round_num: int
) -> dict:
    """
    Execute one round of iteration for all non-ready models.

    Returns:
        {
            "model_requests": {model_id: ModelIterationRequest},
            "aggregated_questions": [{"text": str, "asked_by": [ids]}],
            "search_results": {query: results}
        }
    """
    # Filter to only non-ready models
    active_states = [s for s in model_states if not s.is_ready]

    # Build prompts for each model
    async def query_model_for_iteration(state: ModelRoundState):
        prompt = _build_iteration_prompt(user_query, state, round_num)
        response = await query_model(state.model_id, prompt)

        if response is None:
            # Graceful degradation
            return state.model_id, ModelIterationRequest(
                status="ready",
                response="[Model failed to respond]"
            )

        # Parse structured response
        request = _parse_iteration_response(response["content"])
        return state.model_id, request

    # Query all models in parallel
    results = await asyncio.gather(
        *[query_model_for_iteration(s) for s in active_states]
    )
    model_requests = dict(results)

    # Aggregate searches and execute
    all_searches = []
    for req in model_requests.values():
        all_searches.extend(req.searches)

    search_results = {}
    if all_searches:
        search_tasks = [execute_search(q) for q in all_searches]
        search_res = await asyncio.gather(*search_tasks)
        search_results = dict(zip(all_searches, search_res))

    # Aggregate questions
    questions_by_model = {
        mid: req.questions
        for mid, req in model_requests.items()
        if req.questions
    }
    aggregated_questions = aggregate_questions(questions_by_model)

    return {
        "model_requests": model_requests,
        "aggregated_questions": aggregated_questions,
        "search_results": search_results
    }


def _build_iteration_prompt(
    user_query: str,
    state: ModelRoundState,
    round_num: int
) -> str:
    """Build prompt for a model's iteration round."""
    prompt = f"""You are participating in a council to answer this question:

{user_query}

This is round {round_num}. You may request web searches or ask the user questions to gather more information.

"""

    # Add accumulated context
    if state.accumulated_searches:
        prompt += "\nPrevious search results:\n"
        for search in state.accumulated_searches:
            prompt += f"\nQ: {search['query']}\n{search['results']}\n"

    if state.accumulated_questions:
        prompt += "\nPrevious answers from user:\n"
        for qa in state.accumulated_questions:
            prompt += f"\nQ: {qa['q']}\nA: {qa['a']}\n"

    prompt += """
Respond in this JSON format:
{
  "status": "needs_info" or "ready",
  "searches": ["search query 1", "search query 2"],
  "questions": ["question for user"],
  "response": "your final answer (only if status is ready)"
}

If you have enough information, set status to "ready" and provide your response.
Otherwise, set status to "needs_info" and list searches/questions you need.
"""

    return prompt


def _parse_iteration_response(content: str) -> ModelIterationRequest:
    """Parse model's JSON response into structured request."""
    import json

    try:
        data = json.loads(content)
        return ModelIterationRequest(**data)
    except (json.JSONDecodeError, ValueError):
        # Fallback: treat as ready with content as response
        return ModelIterationRequest(
            status="ready",
            response=content
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_council_iteration.py::test_execute_single_round_collects_requests -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_council_iteration.py backend/council.py
git commit -m "feat: add single round execution logic"
```

---

## Task 6: Backend - Multi-Round Orchestration

**Files:**
- Modify: `backend/council.py`

**Step 1: Write orchestration function**

```python
# Add to backend/council.py

async def run_iterative_phase(
    user_query: str,
    council_models: list[str],
    max_iterations: int = 3,
    user_answer_callback=None
) -> dict[str, ModelRoundState]:
    """
    Run the full iterative phase across all models.

    Args:
        user_query: The question to answer
        council_models: List of model IDs
        max_iterations: Maximum rounds per model
        user_answer_callback: Async function(questions) -> answers dict

    Returns:
        Final state for each model: {model_id: ModelRoundState}
    """
    # Initialize states
    states = {
        mid: ModelRoundState(model_id=mid, current_round=0, is_ready=False)
        for mid in council_models
    }

    for round_num in range(1, max_iterations + 1):
        # Get non-ready models
        active_models = [s for s in states.values() if not s.is_ready]
        if not active_models:
            break  # All models ready

        # Execute round
        round_result = await execute_single_round(
            user_query,
            list(states.values()),
            round_num
        )

        # Update states with results
        for model_id, request in round_result["model_requests"].items():
            state = states[model_id]
            state.current_round = round_num

            # Add search results this model requested
            for query in request.searches:
                if query in round_result["search_results"]:
                    state.accumulated_searches.append({
                        "query": query,
                        "results": round_result["search_results"][query]
                    })

            # Check if ready
            if request.status == "ready":
                state.is_ready = True
                state.final_response = request.response

        # If there are questions, get user answers
        if round_result["aggregated_questions"] and user_answer_callback:
            user_answers = await user_answer_callback(
                round_result["aggregated_questions"]
            )

            # Route answers to models that asked
            for question in round_result["aggregated_questions"]:
                answer = user_answers.get(question["text"])
                if answer:
                    for model_id in question["asked_by"]:
                        if model_id in states:
                            states[model_id].accumulated_questions.append({
                                "q": question["text"],
                                "a": answer
                            })

    # Force completion for any non-ready models
    for state in states.values():
        if not state.is_ready:
            state.is_ready = True
            state.final_response = "[No response after max iterations]"

    return states
```

**Step 2: Verify function is syntactically correct**

Run: `python -c "from backend.council import run_iterative_phase; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add backend/council.py
git commit -m "feat: add multi-round orchestration logic"
```

---

## Task 7: Backend - SSE Integration for Progress Updates

**Files:**
- Modify: `backend/main.py`

**Step 1: Add SSE endpoint for iteration progress**

```python
# Add to backend/main.py

from sse_starlette.sse import EventSourceResponse
import asyncio


@app.post("/api/conversations/{conversation_id}/message-stream")
async def send_message_stream(conversation_id: str, message: dict):
    """
    Send a message with SSE progress updates during iteration phase.
    """
    from .council import run_iterative_phase
    from .config import COUNCIL_MODELS, DEFAULT_MAX_ITERATIONS

    user_message = message["content"]
    max_iterations = message.get("max_iterations", DEFAULT_MAX_ITERATIONS)

    async def event_generator():
        # Store user answers as they come in
        pending_questions = None
        user_answers = {}

        async def answer_callback(questions):
            nonlocal pending_questions, user_answers
            pending_questions = questions

            # Send questions to client
            yield {
                "event": "questions_needed",
                "data": json.dumps({"questions": questions})
            }

            # Wait for answers (client will call separate endpoint)
            # For now, use empty answers (will enhance in later task)
            return {}

        # Start iteration phase
        yield {
            "event": "phase_start",
            "data": json.dumps({"phase": "iteration"})
        }

        final_states = await run_iterative_phase(
            user_message,
            COUNCIL_MODELS,
            max_iterations,
            answer_callback
        )

        # Send completion
        yield {
            "event": "iteration_complete",
            "data": json.dumps({
                "states": {
                    mid: {
                        "rounds": s.current_round,
                        "response": s.final_response
                    }
                    for mid, s in final_states.items()
                }
            })
        }

        # Continue with Stage 2 & 3 (existing logic)
        # ... (will integrate in later task)

    return EventSourceResponse(event_generator())
```

**Step 2: Verify endpoint exists**

Run: `python -m backend.main` (Ctrl+C after startup, check logs for routes)
Expected: `/api/conversations/{conversation_id}/message-stream` appears in routes

**Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add SSE endpoint for iteration progress"
```

---

## Task 8: Frontend - Iteration State Management

**Files:**
- Modify: `frontend/src/App.jsx`

**Step 1: Add iteration state to App component**

```javascript
// In App.jsx, add to state
const [iterationPhase, setIterationPhase] = useState({
  active: false,
  maxIterations: 3,
  modelStates: {}, // {modelId: {round: N, status: 'thinking'|'ready'}}
  pendingQuestions: null
});
```

**Step 2: Add SSE handling for iteration events**

```javascript
// Add new function in App.jsx

const sendMessageWithStream = async (conversationId, content, maxIterations) => {
  setIterationPhase(prev => ({ ...prev, active: true, maxIterations }));

  const eventSource = new EventSource(
    `http://localhost:8001/api/conversations/${conversationId}/message-stream`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, max_iterations: maxIterations })
    }
  );

  eventSource.addEventListener('phase_start', (e) => {
    const data = JSON.parse(e.data);
    console.log('Phase started:', data.phase);
  });

  eventSource.addEventListener('questions_needed', (e) => {
    const data = JSON.parse(e.data);
    setIterationPhase(prev => ({
      ...prev,
      pendingQuestions: data.questions
    }));
  });

  eventSource.addEventListener('iteration_complete', (e) => {
    const data = JSON.parse(e.data);
    setIterationPhase(prev => ({
      ...prev,
      active: false,
      modelStates: data.states
    }));
    eventSource.close();
  });

  eventSource.onerror = (err) => {
    console.error('SSE error:', err);
    eventSource.close();
    setIterationPhase(prev => ({ ...prev, active: false }));
  };
};
```

**Step 3: Verify compiles without errors**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: add iteration state management to frontend"
```

---

## Task 9: Frontend - Progress Grid Component

**Files:**
- Create: `frontend/src/components/ProgressGrid.jsx`
- Create: `frontend/src/components/ProgressGrid.css`

**Step 1: Write the Progress Grid component**

```javascript
// frontend/src/components/ProgressGrid.jsx
import React from 'react';
import './ProgressGrid.css';

export default function ProgressGrid({ modelStates, maxIterations }) {
  if (!modelStates || Object.keys(modelStates).length === 0) {
    return null;
  }

  const models = Object.keys(modelStates);
  const readyCount = models.filter(m => modelStates[m].status === 'ready').length;

  return (
    <div className="progress-grid">
      <table>
        <thead>
          <tr>
            <th>Model</th>
            {Array.from({ length: maxIterations }, (_, i) => (
              <th key={i}>R{i + 1}</th>
            ))}
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {models.map(modelId => {
            const state = modelStates[modelId];
            const shortName = modelId.split('/').pop();

            return (
              <tr key={modelId}>
                <td className="model-name">{shortName}</td>
                {Array.from({ length: maxIterations }, (_, i) => {
                  const roundNum = i + 1;
                  let symbol = '·'; // Not started

                  if (state.status === 'ready' && state.rounds === roundNum) {
                    symbol = '●'; // Finished here
                  } else if (state.rounds > roundNum) {
                    symbol = '✓'; // Completed, continued
                  } else if (state.rounds === roundNum && state.status !== 'ready') {
                    symbol = '⏳'; // In progress
                  } else if (state.status === 'ready' && state.rounds < roundNum) {
                    symbol = '—'; // Skipped
                  }

                  return <td key={i} className="round-cell">{symbol}</td>;
                })}
                <td className="status-cell">
                  {state.status === 'ready' ? '✓ READY' : 'Thinking...'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="progress-summary">
        {readyCount}/{models.length} ready
      </div>
    </div>
  );
}
```

**Step 2: Write the CSS**

```css
/* frontend/src/components/ProgressGrid.css */
.progress-grid {
  margin: 16px 0;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 8px;
}

.progress-grid table {
  width: 100%;
  border-collapse: collapse;
  font-family: 'SF Mono', 'Monaco', 'Courier New', monospace;
  font-size: 14px;
}

.progress-grid th {
  padding: 8px;
  text-align: left;
  border-bottom: 2px solid #ddd;
  font-weight: 600;
}

.progress-grid td {
  padding: 8px;
  border-bottom: 1px solid #eee;
}

.progress-grid .model-name {
  font-weight: 500;
}

.progress-grid .round-cell {
  text-align: center;
  font-size: 16px;
}

.progress-grid .status-cell {
  color: #666;
}

.progress-summary {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ddd;
  font-size: 13px;
  color: #666;
  text-align: right;
}
```

**Step 3: Import and use in ChatInterface**

```javascript
// In frontend/src/components/ChatInterface.jsx

import ProgressGrid from './ProgressGrid';

// Add in render, before messages:
{iterationPhase.active && (
  <ProgressGrid
    modelStates={iterationPhase.modelStates}
    maxIterations={iterationPhase.maxIterations}
  />
)}
```

**Step 4: Verify compiles without errors**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add frontend/src/components/ProgressGrid.jsx frontend/src/components/ProgressGrid.css frontend/src/components/ChatInterface.jsx
git commit -m "feat: add progress grid component"
```

---

## Task 10: Frontend - Round Questions Component

**Files:**
- Create: `frontend/src/components/RoundQuestions.jsx`
- Create: `frontend/src/components/RoundQuestions.css`

**Step 1: Write the component**

```javascript
// frontend/src/components/RoundQuestions.jsx
import React, { useState } from 'react';
import './RoundQuestions.css';

export default function RoundQuestions({ questions, onSubmit, searchCount }) {
  const [answers, setAnswers] = useState({});

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(answers);
  };

  return (
    <div className="round-questions">
      <h3>Questions for you:</h3>

      <form onSubmit={handleSubmit}>
        {questions.map((q, idx) => (
          <div key={idx} className="question-item">
            <label>
              {idx + 1}. {q.text}
              <span className="asked-by">
                ({q.asked_by.map(m => m.split('/').pop()).join(', ')})
              </span>
            </label>
            <input
              type="text"
              value={answers[q.text] || ''}
              onChange={(e) => setAnswers(prev => ({
                ...prev,
                [q.text]: e.target.value
              }))}
              placeholder="Your answer..."
            />
          </div>
        ))}

        {searchCount > 0 && (
          <div className="search-info">
            Searches completed: {searchCount}
          </div>
        )}

        <div className="question-actions">
          <button type="submit" className="submit-btn">
            Submit Answers
          </button>
          <button
            type="button"
            className="skip-btn"
            onClick={() => onSubmit({})}
          >
            Skip Round
          </button>
        </div>
      </form>
    </div>
  );
}
```

**Step 2: Write the CSS**

```css
/* frontend/src/components/RoundQuestions.css */
.round-questions {
  margin: 16px 0;
  padding: 20px;
  background: #fff3cd;
  border: 1px solid #ffc107;
  border-radius: 8px;
}

.round-questions h3 {
  margin-top: 0;
  color: #856404;
}

.question-item {
  margin: 16px 0;
}

.question-item label {
  display: block;
  font-weight: 500;
  margin-bottom: 6px;
}

.asked-by {
  font-size: 12px;
  color: #666;
  font-weight: normal;
  margin-left: 8px;
}

.question-item input {
  width: 100%;
  padding: 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.search-info {
  margin: 16px 0;
  padding: 12px;
  background: #e7f3ff;
  border-radius: 4px;
  font-size: 13px;
  color: #004085;
}

.question-actions {
  margin-top: 20px;
  display: flex;
  gap: 12px;
}

.submit-btn, .skip-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.submit-btn {
  background: #4a90e2;
  color: white;
}

.submit-btn:hover {
  background: #357abd;
}

.skip-btn {
  background: #f0f0f0;
  color: #333;
}

.skip-btn:hover {
  background: #e0e0e0;
}
```

**Step 3: Verify compiles without errors**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add frontend/src/components/RoundQuestions.jsx frontend/src/components/RoundQuestions.css
git commit -m "feat: add round questions component"
```

---

## Task 11: Integration - Connect Backend Iteration to Existing Stages

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/council.py`

**Step 1: Update SSE endpoint to call Stage 2 & 3 after iteration**

```python
# In backend/main.py, update the event_generator function

async def event_generator():
    # ... existing iteration code ...

    # After iteration_complete event:
    yield {
        "event": "phase_start",
        "data": json.dumps({"phase": "stage2"})
    }

    # Prepare responses for Stage 2
    stage1_responses = {
        mid: {"content": state.final_response}
        for mid, state in final_states.items()
    }

    # Run Stage 2 (existing function)
    stage2_rankings, label_to_model = await stage2_collect_rankings(stage1_responses)

    yield {
        "event": "stage2_complete",
        "data": json.dumps({
            "rankings": stage2_rankings,
            "label_to_model": label_to_model
        })
    }

    # Run Stage 3
    yield {
        "event": "phase_start",
        "data": json.dumps({"phase": "stage3"})
    }

    stage3_synthesis = await stage3_synthesize_final(
        user_message,
        stage1_responses,
        stage2_rankings
    )

    yield {
        "event": "complete",
        "data": json.dumps({
            "stage3": stage3_synthesis,
            "aggregate_rankings": calculate_aggregate_rankings(stage2_rankings)
        })
    }
```

**Step 2: Verify backend starts without errors**

Run: `python -m backend.main` (Ctrl+C after startup)
Expected: No errors

**Step 3: Commit**

```bash
git add backend/main.py backend/council.py
git commit -m "feat: integrate iteration phase with existing stages"
```

---

## Task 12: Frontend - Max Iterations Selector

**Files:**
- Modify: `frontend/src/components/ChatInterface.jsx`

**Step 1: Add dropdown for iteration selection**

```javascript
// In ChatInterface.jsx, add state:
const [maxIterations, setMaxIterations] = useState(3);

// Add UI element above textarea:
<div className="iteration-selector">
  <label>
    Max Iterations:
    <select
      value={maxIterations}
      onChange={(e) => setMaxIterations(Number(e.target.value))}
    >
      <option value={1}>1</option>
      <option value={2}>2</option>
      <option value={3}>3</option>
    </select>
  </label>
</div>

// Pass to sendMessage:
onSendMessage(message, maxIterations);
```

**Step 2: Add CSS for selector**

```css
/* In ChatInterface.css */
.iteration-selector {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.iteration-selector select {
  padding: 4px 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}
```

**Step 3: Verify compiles**

Run: `cd frontend && npm run build`
Expected: Success

**Step 4: Commit**

```bash
git add frontend/src/components/ChatInterface.jsx frontend/src/components/ChatInterface.css
git commit -m "feat: add max iterations selector to chat interface"
```

---

## Task 13: Testing - End-to-End Manual Test

**Files:**
- None (manual testing)

**Step 1: Start backend**

Run: `python -m backend.main`
Expected: Server starts on port 8001

**Step 2: Start frontend**

Run: `cd frontend && npm run dev`
Expected: Dev server starts on port 5173

**Step 3: Test basic flow**

1. Open `http://localhost:5173`
2. Create new conversation
3. Set max iterations to 2
4. Send message: "What's the capital of France?"
5. Observe:
   - Progress grid appears
   - Models progress through rounds
   - Final responses display in tabs

Expected: No crashes, responses appear

**Step 4: Document any issues found**

Create: `docs/testing-notes.md` with findings

---

## Task 14: Documentation - Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add Iteration Phase section**

Add after "## Architecture" section:

```markdown
## Iteration Phase Architecture

The agentic iteration system replaces the old synchronized Stage 0/1 with per-model loops:

**Key Components:**

- `backend/iteration_types.py`: Pydantic models for iteration state
- `backend/aggregation.py`: Question deduplication logic
- `backend/search.py`: Web search integration (placeholder for now)
- `backend/council.py`:
  - `run_iterative_phase()`: Main orchestrator
  - `execute_single_round()`: Per-round execution
  - `_build_iteration_prompt()`: Constructs prompts with accumulated context
  - `_parse_iteration_response()`: Parses JSON from model responses

**Frontend Components:**

- `ProgressGrid.jsx`: Visual round-by-round progress tracking
- `RoundQuestions.jsx`: User question interface per round

**SSE Events:**

- `phase_start`: Signals phase transition
- `questions_needed`: Requests user input
- `iteration_complete`: All models ready
- `stage2_complete`: Ranking phase done
- `complete`: Full response ready

**Configuration:**

- Default max iterations: 3 (configurable in UI per message)
- Iteration timeout: 60s per model per round
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add iteration phase architecture to CLAUDE.md"
```

---

## Completion Checklist

- [ ] All 14 tasks completed
- [ ] Backend starts without errors
- [ ] Frontend builds and runs
- [ ] Manual test passes
- [ ] Documentation updated
- [ ] All commits pushed to branch

## Next Steps (Future Enhancements)

1. Replace search placeholder with real API (Brave/DuckDuckGo)
2. Add proper user answer flow (SSE bidirectional or polling)
3. Add compare mode for response display
4. Add iteration analytics/metrics
5. Add timeout handling per model
6. Add ability to disable iteration (fallback to legacy)
