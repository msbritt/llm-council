# Iteration Rounds UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure the UI to display iteration rounds as separate, visible sections with timing, model status, questions, and answers - making the iterative process transparent and debuggable.

**Architecture:** Rename stages to be user-friendly (Initial Question → Iteration Rounds → Individual Responses → Peer Rankings → Final Answer). Store iteration round data in the assistant message object. Create IterationRound component similar to ClarificationRound to display Q&A history. Add timing information to each round.

**Tech Stack:** React (frontend), FastAPI + Python (backend), Server-Sent Events (SSE) for streaming

---

## Context: What Exists

### Current State

**Backend (`backend/`):**
- `council.py`: Has `run_iterative_phase()` that returns `(final_states, pending_questions)`
- `main.py`: SSE endpoint `/message-stream` that sends events
- `iteration_types.py`: Has `ModelRoundState`, `ModelIterationRequest`, `IterationState`
- Iteration pauses when questions are needed, sends `questions_needed` event

**Frontend (`frontend/src/`):**
- `App.jsx`: Event handler that stores `pendingQuestions` and `savedState`
- `ChatInterface.jsx`: Conditionally renders `RoundQuestions` component
- `RoundQuestions.jsx`: Shows questions, collects answers, submits
- Current issue: Questions/answers disappear after submission, no history visible

**Current Stage Labels (confusing):**
- Stage 0: Clarification (optional)
- Stage 1: Individual Responses (iteration results)
- Stage 2: Peer Rankings
- Stage 3: Final Synthesis

### Problems to Fix

1. **No iteration round history**: Questions/answers disappear after submission
2. **Stage names confusing**: "Stage 1" doesn't mean "iteration results"
3. **No timing information**: Can't see how long rounds take
4. **No model status visibility**: Can't tell which models are ready vs requesting info
5. **Duplicate messages bug**: Already fixed but need to ensure it stays fixed
6. **Markdown JSON parsing**: Already fixed but need to keep it

---

## New Data Structure

### Assistant Message Object

```javascript
{
  role: 'assistant',
  iterationRounds: [
    {
      roundNum: 1,
      duration: 18.5,  // seconds
      modelStatuses: {
        "openai/gpt-5.2": {status: "ready", timing: 12.3},
        "anthropic/claude-opus-4.5": {status: "needs_info", timing: 15.7}
      },
      questions: [
        {text: "What's your budget?", asked_by: ["anthropic/claude-opus-4.5"]}
      ],
      userAnswers: {
        "What's your budget?": "$50,000"
      }
    },
    // ... more rounds if needed
  ],
  individualResponses: [...],  // formerly stage1
  peerRankings: [...],          // formerly stage2
  finalAnswer: "...",           // formerly stage3
  metadata: {...}
}
```

---

## Task 1: Backend - Add Round Timing to execute_single_round

**Files:**
- Modify: `backend/council.py` (line ~352, `execute_single_round` function)

**Step 1: Import time module and add timing tracking**

Add at top of file if not already present:
```python
import time
```

Modify `execute_single_round` to track timing:

```python
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
            "search_results": {query: results},
            "timing": {
                "round_duration": float,
                "model_timings": {model_id: float}
            }
        }
    """
    round_start = time.time()

    # Filter to only non-ready models
    active_states = [s for s in model_states if not s.is_ready]

    # Build prompts for each model
    async def query_model_for_iteration(state: ModelRoundState):
        model_start = time.time()
        prompt = _build_iteration_prompt(user_query, state, round_num)
        messages = [{"role": "user", "content": prompt}]
        response = await query_model(state.model_id, messages)
        model_duration = time.time() - model_start

        if response is None:
            # Graceful degradation
            return state.model_id, ModelIterationRequest(
                status="ready",
                response="[Model failed to respond]"
            ), model_duration

        # Parse structured response
        request = _parse_iteration_response(response["content"])
        return state.model_id, request, model_duration

    # Query all models in parallel
    results = await asyncio.gather(
        *[query_model_for_iteration(s) for s in active_states]
    )

    # Separate timings from requests
    model_requests = {}
    model_timings = {}
    for model_id, request, duration in results:
        model_requests[model_id] = request
        model_timings[model_id] = duration

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

    round_duration = time.time() - round_start

    # DEBUG (keep existing debug logs)
    print(f"[DEBUG Round {round_num}] questions_by_model: {questions_by_model}")
    print(f"[DEBUG Round {round_num}] aggregated_questions: {aggregated_questions}")
    print(f"[DEBUG Round {round_num}] Round duration: {round_duration:.2f}s")
    print(f"[DEBUG Round {round_num}] Model statuses:")
    for mid, req in model_requests.items():
        print(f"  {mid}: status={req.status}, questions={len(req.questions)}, timing={model_timings[mid]:.2f}s")

    return {
        "model_requests": model_requests,
        "aggregated_questions": aggregated_questions,
        "search_results": search_results,
        "timing": {
            "round_duration": round_duration,
            "model_timings": model_timings
        }
    }
```

**Step 2: Verify backend still imports**

Run:
```bash
source .venv/bin/activate
python -c "from backend.council import execute_single_round; print('OK')"
```

Expected: `OK` (no import errors)

**Step 3: Commit**

```bash
git add backend/council.py
git commit -m "feat: add timing tracking to execute_single_round"
```

---

## Task 2: Backend - Include Round Data in Iteration Events

**Files:**
- Modify: `backend/main.py` (line ~365, `event_generator` function)

**Step 1: Track rounds during iteration**

Modify the iteration phase logic to collect round data:

```python
# After: # Start iteration phase

# Track iteration rounds for history
iteration_rounds = []
current_round_num = start_round

final_states, pending_questions = await run_iterative_phase(
    user_message,
    COUNCIL_MODELS,
    max_iterations,
    user_answer_callback=None,
    start_round=start_round,
    initial_states=initial_states
)
```

Wait - we need to refactor `run_iterative_phase` to return round data. Let me think...

Actually, we need to capture round data as we go. Let me revise:

**Step 1: Refactor to capture round data**

The issue is that `run_iterative_phase` doesn't currently return round-by-round data. We need to either:
- A) Make it yield round data as it goes
- B) Accumulate round data and return it at the end
- C) Have the endpoint call `execute_single_round` directly

Option C is cleanest for now. Modify the endpoint to handle iteration directly:

In `backend/main.py`, replace the iteration logic:

```python
            # Check if resuming from previous iteration
            iteration_state = request.clarifications.get("iteration_state") if request.clarifications else None

            # Track iteration rounds
            iteration_rounds = []

            if iteration_state and iteration_state.get("user_answers"):
                # Resume iteration with answers - restore previous rounds
                iteration_rounds = iteration_state.get("iteration_rounds", [])
                initial_states = deserialize_model_states(iteration_state["model_states"])
                apply_answers_to_states(
                    initial_states,
                    iteration_state["pending_questions"],
                    iteration_state["user_answers"]
                )
                start_round = iteration_state["round_num"] + 1

                # Add the completed round with user answers
                iteration_rounds.append({
                    "roundNum": iteration_state["round_num"],
                    "duration": iteration_state.get("round_duration", 0),
                    "modelStatuses": {
                        mid: {
                            "status": "needs_info" if mid in [q["text"] for q in iteration_state["pending_questions"]] else "ready",
                            "timing": 0  # Historical, not tracked
                        }
                        for mid in COUNCIL_MODELS
                    },
                    "questions": iteration_state["pending_questions"],
                    "userAnswers": iteration_state["user_answers"]
                })
            else:
                # Start new iteration
                initial_states = None
                start_round = 1

            # Start iteration phase
            yield f"event: phase_start\ndata: {json.dumps({'type': 'phase_start', 'phase': 'iteration'})}\n\n"

            final_states, pending_questions = await run_iterative_phase(
                user_message,
                COUNCIL_MODELS,
                max_iterations,
                user_answer_callback=None,
                start_round=start_round,
                initial_states=initial_states
            )
```

Hmm, this is getting complex. Let me reconsider the approach.

**Better approach: Make run_iterative_phase return round data**

Modify `run_iterative_phase` to accumulate and return round data.

In `backend/council.py`, update `run_iterative_phase`:

```python
async def run_iterative_phase(
    user_query: str,
    council_models: list[str],
    max_iterations: int = 3,
    user_answer_callback=None,
    start_round: int = 1,
    initial_states: dict[str, ModelRoundState] | None = None,
) -> tuple[dict[str, ModelRoundState], list[dict] | None, list[dict]]:
    """
    Run the iterative phase, pausing if questions need user answers.

    Args:
        user_query: The question to answer
        council_models: List of model IDs
        max_iterations: Maximum rounds per model
        user_answer_callback: Async function(questions) -> answers dict (legacy, not used with pause-resume)
        start_round: Which round to start from (1 for new, >1 for resume)
        initial_states: Previous states when resuming (None for new iteration)

    Returns:
        (final_states, None, round_history) if complete
        (partial_states, aggregated_questions, round_history) if paused for questions

        round_history: [
            {
                "roundNum": int,
                "duration": float,
                "modelStatuses": {model_id: {"status": str, "timing": float}},
                "questions": [...],
                "userAnswers": {...}  # Empty if paused, filled if resumed
            }
        ]
    """
    # Initialize or restore states
    if initial_states:
        states = initial_states
    else:
        states = {
            mid: ModelRoundState(model_id=mid, current_round=0, is_ready=False)
            for mid in council_models
        }

    round_history = []

    for round_num in range(start_round, max_iterations + 1):
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

        # Build model statuses for this round (include ALL models, not just active)
        model_statuses = {}
        for model_id, state in states.items():
            if model_id in round_result["model_requests"]:
                # Model participated in this round
                request = round_result["model_requests"][model_id]
                model_statuses[model_id] = {
                    "status": request.status,
                    "timing": round_result["timing"]["model_timings"].get(model_id, 0)
                }
            elif state.is_ready:
                # Model was already ready from previous round
                model_statuses[model_id] = {
                    "status": "ready",
                    "timing": 0,
                    "note": "completed_earlier"
                }
            else:
                # Model should have participated but didn't (edge case)
                model_statuses[model_id] = {
                    "status": "unknown",
                    "timing": 0
                }

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

        # If there are questions and no callback, pause for user input
        if round_result["aggregated_questions"]:
            print(f"[DEBUG] Found {len(round_result['aggregated_questions'])} aggregated questions in round {round_num}")
            if user_answer_callback:
                # Legacy path: use callback
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

                # Record round with answers
                round_history.append({
                    "roundNum": round_num,
                    "duration": round_result["timing"]["round_duration"],
                    "modelStatuses": model_statuses,
                    "questions": round_result["aggregated_questions"],
                    "userAnswers": user_answers
                })
            else:
                # New path: pause and return questions for frontend to handle
                print(f"[DEBUG] PAUSING iteration - returning {len(round_result['aggregated_questions'])} questions to frontend")

                # Record round without answers yet
                round_history.append({
                    "roundNum": round_num,
                    "duration": round_result["timing"]["round_duration"],
                    "modelStatuses": model_statuses,
                    "questions": round_result["aggregated_questions"],
                    "userAnswers": {}  # Will be filled when resumed
                })

                return (states, round_result["aggregated_questions"], round_history)
        else:
            # No questions, record round as complete
            round_history.append({
                "roundNum": round_num,
                "duration": round_result["timing"]["round_duration"],
                "modelStatuses": model_statuses,
                "questions": [],
                "userAnswers": {}
            })

    # Force completion for any non-ready models
    for state in states.values():
        if not state.is_ready:
            state.is_ready = True
            state.final_response = "[No response after max iterations]"

    return (states, None, round_history)
```

**Step 2: Update caller in main.py**

```python
final_states, pending_questions, round_history = await run_iterative_phase(
    user_message,
    COUNCIL_MODELS,
    max_iterations,
    user_answer_callback=None,
    start_round=start_round,
    initial_states=initial_states
)
```

**Step 3: Include round_history in questions_needed event**

```python
if pending_questions:
    print(f"[DEBUG] Sending questions_needed event with {len(pending_questions)} questions")
    # Send questions_needed event with full state for resume
    event_data = {
        'type': 'questions_needed',
        'questions': pending_questions,
        'round_history': round_history,  # ADD THIS
        'iteration_state': {
            'user_query': user_message,
            'round_num': round_history[-1]["roundNum"] if round_history else start_round,  # FIX: Use actual round from history
            'max_iterations': max_iterations,
            'model_states': serialize_model_states(final_states),
            'pending_questions': pending_questions,
            'round_history': round_history,  # ADD THIS TOO
        }
    }
    print(f"[DEBUG] Event data keys: {event_data.keys()}")
    yield f"event: questions_needed\ndata: {json.dumps(event_data)}\n\n"
    print(f"[DEBUG] Returned from event_generator - stream should end here")
    return  # End stream, wait for resubmit with answers
```

**Step 4: Include round_history in stage1_complete event**

```python
# After iteration completes, send round_history with stage1_complete

# Prepare responses for Stage 1 (iteration results)
stage1_responses = [
    {
        "model": mid,
        "response": state.final_response
    }
    for mid, state in final_states.items()
]

# DEBUG: Log what we're sending
print(f"[DEBUG] final_states has {len(final_states)} models")
print(f"[DEBUG] stage1_responses has {len(stage1_responses)} entries")
print(f"[DEBUG] round_history has {len(round_history)} rounds")
for resp in stage1_responses:
    print(f"[DEBUG] Model: {resp['model']}, Response preview: {resp['response'][:100] if resp['response'] else 'None'}...")

# Send Stage 1 completion with round history
yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_responses, 'round_history': round_history})}\n\n"
```

**Step 5: Verify backend still runs**

Run:
```bash
source .venv/bin/activate
python -c "from backend.main import app; print('OK')"
```

Expected: `OK`

**Step 6: Commit**

```bash
git add backend/council.py backend/main.py
git commit -m "feat: capture and return iteration round history with timing"
```

---

## Task 3: Frontend - Create IterationRound Component

**Files:**
- Create: `frontend/src/components/IterationRound.jsx`
- Create: `frontend/src/components/IterationRound.css`

**Step 1: Create IterationRound component**

```jsx
import React from 'react';
import './IterationRound.css';

export default function IterationRound({ round }) {
  const { roundNum, duration, modelStatuses, questions, userAnswers } = round;

  // Format duration
  const formatDuration = (seconds) => {
    if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  // Extract model name from full ID
  const getModelName = (modelId) => {
    return modelId.split('/').pop();
  };

  // Check if all models are ready
  const allReady = Object.values(modelStatuses).every(s => s.status === 'ready');

  return (
    <div className="iteration-round">
      <div className="round-header">
        <h3>ITERATION ROUND {roundNum} ({formatDuration(duration)})</h3>
        {allReady && <span className="all-ready-badge">✓ All models ready</span>}
      </div>

      <div className="model-statuses">
        <h4>Model Status:</h4>
        {Object.entries(modelStatuses).map(([modelId, status]) => (
          <div key={modelId} className="model-status">
            <span className={`status-icon ${status.status}`}>
              {status.status === 'ready' ? '✓' : '⏳'}
            </span>
            <span className="model-name">{getModelName(modelId)}</span>
            <span className="model-timing">({formatDuration(status.timing)})</span>
            <span className="model-state">
              {status.status === 'ready' ? 'Ready' : 'Requesting information'}
            </span>
          </div>
        ))}
      </div>

      {questions && questions.length > 0 && (
        <div className="round-questions-display">
          <h4>Questions Asked:</h4>
          {questions.map((q, idx) => (
            <div key={idx} className="question-display">
              <div className="question-text">
                <strong>{idx + 1}.</strong> {q.text}
              </div>
              <div className="asked-by">
                Asked by: {q.asked_by.map(getModelName).join(', ')}
              </div>
              {userAnswers[q.text] && (
                <div className="user-answer">
                  <strong>Your answer:</strong> {userAnswers[q.text]}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {questions.length === 0 && (
        <div className="no-questions">
          <p>✓ No questions needed - all models had sufficient information</p>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Create CSS styling**

```css
.iteration-round {
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  padding: 20px;
  margin: 20px 0;
}

.round-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #4a90e2;
}

.round-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #333;
}

.all-ready-badge {
  background: #28a745;
  color: white;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 500;
}

.model-statuses {
  margin-bottom: 20px;
}

.model-statuses h4 {
  margin: 0 0 12px 0;
  font-size: 0.95rem;
  color: #666;
}

.model-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: white;
  border-radius: 6px;
  margin-bottom: 8px;
}

.status-icon {
  font-size: 1.1rem;
  width: 24px;
  text-align: center;
}

.status-icon.ready {
  color: #28a745;
}

.status-icon.needs_info {
  color: #ffc107;
}

.model-name {
  font-weight: 600;
  color: #333;
  min-width: 120px;
}

.model-timing {
  color: #666;
  font-size: 0.9rem;
}

.model-state {
  color: #666;
  font-size: 0.9rem;
  margin-left: auto;
}

.round-questions-display {
  margin-top: 20px;
}

.round-questions-display h4 {
  margin: 0 0 12px 0;
  font-size: 0.95rem;
  color: #666;
}

.question-display {
  background: white;
  border-left: 3px solid #4a90e2;
  padding: 12px;
  margin-bottom: 12px;
  border-radius: 4px;
}

.question-text {
  color: #333;
  margin-bottom: 6px;
  font-size: 0.95rem;
}

.asked-by {
  color: #666;
  font-size: 0.85rem;
  font-style: italic;
  margin-bottom: 8px;
}

.user-answer {
  background: #e7f3ff;
  padding: 8px 12px;
  border-radius: 4px;
  margin-top: 8px;
  font-size: 0.9rem;
}

.user-answer strong {
  color: #4a90e2;
}

.no-questions {
  background: white;
  padding: 16px;
  border-radius: 6px;
  text-align: center;
}

.no-questions p {
  margin: 0;
  color: #28a745;
  font-weight: 500;
}
```

**Step 3: Verify component renders**

Create a test file (temporary):

```bash
# We'll test this after integrating into the app
echo "Component created, will test after integration"
```

**Step 4: Commit**

```bash
git add frontend/src/components/IterationRound.jsx frontend/src/components/IterationRound.css
git commit -m "feat: create IterationRound component for displaying round history"
```

---

## Task 4: Frontend - Update App.jsx to Store Round History

**Files:**
- Modify: `frontend/src/App.jsx` (event handlers)

**Step 1: Store round history in state**

Update the assistant message structure and event handlers:

```javascript
// In handleSendMessage, around line 116-129:

// Create a partial assistant message that will be updated progressively
const assistantMessage = {
  role: 'assistant',
  stage0: clarifications?.stage0_data || null,
  iterationRounds: [],  // ADD THIS
  stage1: null,
  stage2: null,
  stage3: null,
  metadata: null,
  clarifications: clarifications,
  loading: {
    stage1: false,
    stage2: false,
    stage3: false,
  },
};
```

**Step 2: Update questions_needed handler to include round history**

```javascript
case 'questions_needed':
  // Models need answers during iteration - pause for user input
  setIterationPhase(prev => ({
    ...prev,
    active: false,  // Pause visual indicator
    pendingQuestions: event.questions,
    savedState: event.iteration_state,  // Store full state for resubmit
    roundHistory: event.round_history || []  // ADD THIS
  }));
  setIsLoading(false);  // Show UI
  // Store the query for resubmission (it's in the iteration_state)
  setCurrentQuery(event.iteration_state?.user_query || content);

  // Update the last assistant message with round history
  setCurrentConversation((prev) => {
    const messages = [...prev.messages];
    const lastMsg = messages[messages.length - 1];
    if (lastMsg.role === 'assistant') {
      lastMsg.iterationRounds = event.round_history || [];
    }
    return { ...prev, messages };
  });
  break;
```

**Step 3: Update stage1_complete handler to include round history**

```javascript
case 'stage1_complete':
  setCurrentConversation((prev) => {
    const messages = [...prev.messages];
    const lastMsg = messages[messages.length - 1];
    lastMsg.stage1 = event.data;
    lastMsg.iterationRounds = event.round_history || lastMsg.iterationRounds || [];  // ADD THIS
    lastMsg.loading.stage1 = false;
    return { ...prev, messages };
  });
  break;
```

**Step 4: Update iterationPhase initial state**

```javascript
const [iterationPhase, setIterationPhase] = useState({
  active: false,
  maxIterations: 3,
  modelStates: {},
  pendingQuestions: null,
  savedState: null,
  roundHistory: []  // ADD THIS
});
```

**Step 5: Rebuild frontend to check for errors**

```bash
cd frontend
npm run build
```

Expected: Build succeeds

**Step 6: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: store iteration round history in message state"
```

---

## Task 5: Frontend - Display IterationRound Components in ChatInterface

**Files:**
- Modify: `frontend/src/components/ChatInterface.jsx`

**Step 1: Import IterationRound component**

```javascript
import IterationRound from './IterationRound';
```

**Step 2: Display iteration rounds in message rendering**

Find where assistant messages are rendered (around line 80-120), and add iteration rounds display:

```jsx
{message.role === 'assistant' && (
  <div className="assistant-message">
    {/* Show iteration rounds if they exist */}
    {message.iterationRounds && message.iterationRounds.length > 0 && (
      <div className="iteration-rounds-section">
        <h3 className="section-header">Iteration Rounds</h3>
        {message.iterationRounds.map((round) => (
          <IterationRound key={round.roundNum} round={round} />
        ))}
      </div>
    )}

    {/* Existing Stage 1, 2, 3 rendering... */}
    {message.stage1 && <Stage1 responses={message.stage1} />}
    {message.stage2 && (
      <Stage2
        rankings={message.stage2}
        labelToModel={message.metadata?.label_to_model}
        aggregateRankings={message.metadata?.aggregate_rankings}
      />
    )}
    {message.stage3 && <Stage3 synthesis={message.stage3} />}
  </div>
)}
```

**Step 3: Add CSS for section styling**

In `ChatInterface.css`, add:

```css
.iteration-rounds-section {
  margin-bottom: 30px;
}

.section-header {
  font-size: 1.2rem;
  color: #333;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid #4a90e2;
}
```

**Step 4: Rebuild and verify**

```bash
cd frontend
npm run build
```

Expected: Build succeeds

**Step 5: Commit**

```bash
git add frontend/src/components/ChatInterface.jsx frontend/src/components/ChatInterface.css
git commit -m "feat: display iteration rounds in chat interface"
```

---

## Task 6: Frontend - Rename Stage Labels

**Files:**
- Modify: `frontend/src/components/Stage1.jsx`
- Modify: `frontend/src/components/Stage2.jsx`
- Modify: `frontend/src/components/Stage3.jsx`

**Step 1: Update Stage1 header**

In `Stage1.jsx`:

```javascript
// Change the header from "Stage 1: Individual Responses" to:
<h3>Individual Responses</h3>
```

**Step 2: Update Stage2 header**

In `Stage2.jsx`:

```javascript
// Change from "Stage 2: Peer Rankings" to:
<h3>Peer Rankings</h3>
```

**Step 3: Update Stage3 header**

In `Stage3.jsx`:

```javascript
// Change from "Stage 3: Final Answer" to:
<h3>Final Council Answer</h3>
```

And update the container class to make it more prominent:

```javascript
<div className="stage3 final-answer">
  <h3>Final Council Answer</h3>
  {/* ... existing content */}
</div>
```

In `Stage3.css`, add:

```css
.stage3.final-answer {
  background: #f0fff0;  /* Keep green tint */
  border: 2px solid #28a745;
  border-radius: 8px;
  padding: 24px;
  margin-top: 30px;
}

.stage3.final-answer h3 {
  font-size: 1.3rem;
  color: #28a745;
  margin-bottom: 20px;
}
```

**Step 4: Rebuild**

```bash
cd frontend
npm run build
```

**Step 5: Commit**

```bash
git add frontend/src/components/Stage1.jsx frontend/src/components/Stage2.jsx frontend/src/components/Stage3.jsx frontend/src/components/Stage3.css
git commit -m "feat: rename stage labels for clarity"
```

---

## Task 7: Fix Round History When Resuming Iteration

**Files:**
- Modify: `backend/council.py` (run_iterative_phase function)

**Problem:** When resuming iteration after user answers, we need to update the last round with the user's answers.

**Step 1: Accept previous round history when resuming**

Update function signature:

```python
async def run_iterative_phase(
    user_query: str,
    council_models: list[str],
    max_iterations: int = 3,
    user_answer_callback=None,
    start_round: int = 1,
    initial_states: dict[str, ModelRoundState] | None = None,
    previous_round_history: list[dict] | None = None,  # ADD THIS
) -> tuple[dict[str, ModelRoundState], list[dict] | None, list[dict]]:
```

**Step 2: Initialize with previous round history**

```python
# Initialize or restore states
if initial_states:
    states = initial_states
else:
    states = {
        mid: ModelRoundState(model_id=mid, current_round=0, is_ready=False)
        for mid in council_models
    }

round_history = previous_round_history or []  # Start with previous history
```

**Step 3: Update main.py to pass previous round history when resuming**

In `backend/main.py`:

```python
if iteration_state and iteration_state.get("user_answers"):
    # Resume iteration with answers
    initial_states = deserialize_model_states(iteration_state["model_states"])
    previous_round_history = iteration_state.get("round_history", [])

    # Update the last round with user answers
    if previous_round_history:
        previous_round_history[-1]["userAnswers"] = iteration_state["user_answers"]

    # Derive start_round from round_history (more reliable than round_num field)
    start_round = (previous_round_history[-1]["roundNum"] + 1) if previous_round_history else 1

    # Apply answers to model states
    apply_answers_to_states(
        initial_states,
        iteration_state["pending_questions"],
        iteration_state["user_answers"]
    )
else:
    # Start new iteration
    initial_states = None
    start_round = 1
    previous_round_history = None

# ... later ...

final_states, pending_questions, round_history = await run_iterative_phase(
    user_message,
    COUNCIL_MODELS,
    max_iterations,
    user_answer_callback=None,
    start_round=start_round,
    initial_states=initial_states,
    previous_round_history=previous_round_history  # ADD THIS
)
```

**Step 4: Verify backend runs**

```bash
source .venv/bin/activate
python -c "from backend.main import app; print('OK')"
```

**Step 5: Commit**

```bash
git add backend/council.py backend/main.py
git commit -m "fix: preserve round history when resuming iteration"
```

---

## Task 8: Manual Testing

**Files:**
- None (testing only)

**Step 1: Rebuild frontend**

```bash
cd frontend
npm run build
cd ..
```

**Step 2: Start servers**

```bash
./start.sh
```

**Step 3: Test basic iteration (no questions)**

1. Open http://localhost:5173
2. Create new conversation
3. Ask: "What is 2+2?"
4. Verify:
   - Round 1 appears with timing
   - Both models show "Ready" status
   - No questions section
   - Individual Responses appear
   - Peer Rankings appear
   - Final Council Answer appears

**Step 4: Test iteration with questions**

1. New conversation
2. Ask: "What laptop should I buy?"
3. Verify:
   - Round 1 appears with questions
   - RoundQuestions component shows up
   - Model status shows who asked
4. Answer questions and submit
5. Verify:
   - Round 1 now shows your answers
   - Round 2 begins (if needed) or completes
   - Full flow continues to Final Answer

**Step 5: Test multi-round iteration**

1. New conversation
2. Set max iterations to 3
3. Ask a complex question
4. Verify multiple rounds display correctly

**Step 6: Check console for errors**

- No JavaScript errors
- No backend tracebacks
- Debug logs look correct

**Step 7: Document any issues found**

Create a file `TESTING_NOTES.md` with findings.

---

## Task 9: Automated Testing

**Files:**
- Create: `backend/tests/test_iteration_rounds.py`
- Create: `frontend/src/components/__tests__/IterationRound.test.jsx`

**Step 1: Create backend test file**

Create `backend/tests/test_iteration_rounds.py`:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from backend.council import (
    execute_single_round,
    run_iterative_phase,
    ModelRoundState,
)
from backend.iteration_types import ModelIterationRequest


class TestExecuteSingleRoundTiming:
    """Test timing data in execute_single_round"""

    @pytest.mark.asyncio
    async def test_returns_timing_data(self):
        """Verify execute_single_round returns timing structure"""
        states = [
            ModelRoundState(model_id="test/model-1", current_round=0, is_ready=False),
        ]

        with patch('backend.council.query_model') as mock_query:
            mock_query.return_value = {
                "content": '{"status": "ready", "response": "Test response"}'
            }

            result = await execute_single_round("Test query", states, 1)

            assert "timing" in result
            assert "round_duration" in result["timing"]
            assert "model_timings" in result["timing"]
            assert result["timing"]["round_duration"] > 0
            assert "test/model-1" in result["timing"]["model_timings"]

    @pytest.mark.asyncio
    async def test_timing_graceful_on_model_failure(self):
        """Timing should still be captured even if model fails"""
        states = [
            ModelRoundState(model_id="test/model-1", current_round=0, is_ready=False),
        ]

        with patch('backend.council.query_model') as mock_query:
            mock_query.return_value = None  # Model failure

            result = await execute_single_round("Test query", states, 1)

            assert "timing" in result
            assert result["timing"]["round_duration"] >= 0


class TestRunIterativePhaseRoundHistory:
    """Test round history tracking in run_iterative_phase"""

    @pytest.mark.asyncio
    async def test_returns_round_history(self):
        """Verify run_iterative_phase returns round_history as 3rd element"""
        with patch('backend.council.execute_single_round') as mock_round:
            mock_round.return_value = {
                "model_requests": {
                    "test/model": ModelIterationRequest(status="ready", response="Done")
                },
                "aggregated_questions": [],
                "search_results": {},
                "timing": {"round_duration": 1.5, "model_timings": {"test/model": 1.2}}
            }

            states, questions, round_history = await run_iterative_phase(
                "Test query",
                ["test/model"],
                max_iterations=3
            )

            assert isinstance(round_history, list)
            assert len(round_history) == 1
            assert round_history[0]["roundNum"] == 1
            assert "duration" in round_history[0]
            assert "modelStatuses" in round_history[0]

    @pytest.mark.asyncio
    async def test_round_history_on_pause(self):
        """When pausing for questions, round_history should have empty userAnswers"""
        with patch('backend.council.execute_single_round') as mock_round:
            mock_round.return_value = {
                "model_requests": {
                    "test/model": ModelIterationRequest(
                        status="needs_info",
                        questions=["What's your budget?"]
                    )
                },
                "aggregated_questions": [
                    {"text": "What's your budget?", "asked_by": ["test/model"]}
                ],
                "search_results": {},
                "timing": {"round_duration": 2.0, "model_timings": {"test/model": 1.8}}
            }

            states, questions, round_history = await run_iterative_phase(
                "Test query",
                ["test/model"],
                max_iterations=3
            )

            assert questions is not None
            assert len(round_history) == 1
            assert round_history[0]["userAnswers"] == {}
            assert len(round_history[0]["questions"]) == 1

    @pytest.mark.asyncio
    async def test_resume_preserves_previous_history(self):
        """Resuming should preserve previous round history"""
        previous_history = [
            {
                "roundNum": 1,
                "duration": 1.5,
                "modelStatuses": {"test/model": {"status": "needs_info", "timing": 1.2}},
                "questions": [{"text": "Q1", "asked_by": ["test/model"]}],
                "userAnswers": {"Q1": "Answer 1"}  # Already filled
            }
        ]

        with patch('backend.council.execute_single_round') as mock_round:
            mock_round.return_value = {
                "model_requests": {
                    "test/model": ModelIterationRequest(status="ready", response="Done")
                },
                "aggregated_questions": [],
                "search_results": {},
                "timing": {"round_duration": 1.0, "model_timings": {"test/model": 0.9}}
            }

            initial_states = {
                "test/model": ModelRoundState(
                    model_id="test/model",
                    current_round=1,
                    is_ready=False,
                    accumulated_questions=[{"q": "Q1", "a": "Answer 1"}]
                )
            }

            states, questions, round_history = await run_iterative_phase(
                "Test query",
                ["test/model"],
                max_iterations=3,
                start_round=2,
                initial_states=initial_states,
                previous_round_history=previous_history
            )

            assert len(round_history) == 2
            assert round_history[0]["roundNum"] == 1
            assert round_history[0]["userAnswers"] == {"Q1": "Answer 1"}
            assert round_history[1]["roundNum"] == 2


class TestRoundHistoryStructure:
    """Test the structure of round history entries"""

    def test_round_entry_has_required_fields(self):
        """Each round entry should have all required fields"""
        required_fields = ["roundNum", "duration", "modelStatuses", "questions", "userAnswers"]

        sample_round = {
            "roundNum": 1,
            "duration": 1.5,
            "modelStatuses": {
                "test/model": {"status": "ready", "timing": 1.2}
            },
            "questions": [],
            "userAnswers": {}
        }

        for field in required_fields:
            assert field in sample_round, f"Missing required field: {field}"
```

**Step 2: Create frontend test file**

Create `frontend/src/components/__tests__/IterationRound.test.jsx`:

```jsx
import { render, screen } from '@testing-library/react';
import IterationRound from '../IterationRound';

describe('IterationRound', () => {
  const mockRound = {
    roundNum: 1,
    duration: 12.5,
    modelStatuses: {
      "openai/gpt-5.2": { status: "ready", timing: 10.2 },
      "anthropic/claude-opus-4.5": { status: "needs_info", timing: 11.8 }
    },
    questions: [
      { text: "What's your budget?", asked_by: ["anthropic/claude-opus-4.5"] }
    ],
    userAnswers: { "What's your budget?": "$50,000" }
  };

  test('renders round header with number and duration', () => {
    render(<IterationRound round={mockRound} />);

    expect(screen.getByText(/ITERATION ROUND 1/)).toBeInTheDocument();
    expect(screen.getByText(/13s/)).toBeInTheDocument(); // 12.5 rounds to 13
  });

  test('shows model statuses with correct icons', () => {
    render(<IterationRound round={mockRound} />);

    expect(screen.getByText('gpt-5.2')).toBeInTheDocument();
    expect(screen.getByText('claude-opus-4.5')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('Requesting information')).toBeInTheDocument();
  });

  test('displays questions and answers', () => {
    render(<IterationRound round={mockRound} />);

    expect(screen.getByText(/What's your budget\?/)).toBeInTheDocument();
    expect(screen.getByText(/\$50,000/)).toBeInTheDocument();
    expect(screen.getByText(/claude-opus-4.5/)).toBeInTheDocument();
  });

  test('handles empty questions array', () => {
    const roundNoQuestions = {
      ...mockRound,
      questions: [],
      userAnswers: {}
    };

    render(<IterationRound round={roundNoQuestions} />);

    expect(screen.getByText(/No questions needed/)).toBeInTheDocument();
  });

  test('handles round without answers yet (paused state)', () => {
    const pausedRound = {
      ...mockRound,
      userAnswers: {}
    };

    render(<IterationRound round={pausedRound} />);

    expect(screen.getByText(/What's your budget\?/)).toBeInTheDocument();
    expect(screen.queryByText(/Your answer:/)).not.toBeInTheDocument();
  });

  test('shows all-ready badge when all models ready', () => {
    const allReadyRound = {
      ...mockRound,
      modelStatuses: {
        "openai/gpt-5.2": { status: "ready", timing: 10.2 },
        "anthropic/claude-opus-4.5": { status: "ready", timing: 11.8 }
      },
      questions: []
    };

    render(<IterationRound round={allReadyRound} />);

    expect(screen.getByText(/All models ready/)).toBeInTheDocument();
  });
});
```

**Step 3: Run backend tests**

```bash
source .venv/bin/activate
python -m pytest backend/tests/test_iteration_rounds.py -v
```

Expected: All tests pass (or skip if not implemented yet)

**Step 4: Run frontend tests**

```bash
cd frontend
npm test -- IterationRound.test.jsx
```

Expected: All tests pass (or skip if component not created yet)

**Step 5: Commit**

```bash
git add backend/tests/test_iteration_rounds.py frontend/src/components/__tests__/IterationRound.test.jsx
git commit -m "test: add automated tests for iteration rounds feature"
```

---

## Verification Checklist

- [ ] Backend timing data captured correctly
- [ ] Round history passed through SSE events
- [ ] IterationRound component displays properly
- [ ] Model status shows correctly (ready vs needs_info)
- [ ] Model status includes ALL models (not just active ones)
- [ ] Questions and answers preserved and visible
- [ ] Stage labels renamed appropriately
- [ ] Final Answer visually prominent
- [ ] No duplicate messages
- [ ] Resuming iteration works correctly
- [ ] Multi-round iteration displays all rounds
- [ ] Console shows no errors
- [ ] Backend tests pass
- [ ] Frontend tests pass

---

## Known Issues / Future Enhancements

1. **Collapsible sections**: Not implemented yet (all expanded for debugging)
2. **Search results display**: Not shown in UI yet (only timing)
3. **Model reasoning traces**: Not captured or displayed
4. **Progress indicators**: No visual progress bar between rounds
5. **Markdown parsing**: Fixed but could add more robust handling
6. **Empty state styling**: Could improve "no questions" display
7. **Mobile responsiveness**: Not tested on mobile devices

---

## Rollback Plan

If issues arise:

```bash
# Revert all changes
git log --oneline  # Find the commit before these changes
git reset --hard <commit-hash>

# Rebuild frontend
cd frontend
npm run build
cd ..

# Restart servers
./start.sh
```
