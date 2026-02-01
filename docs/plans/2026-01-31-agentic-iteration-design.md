# Agentic Iteration Design

## Overview

Replace the synchronized Stage 0/1 pipeline with independent per-model agentic loops. Each council model iterates autonomously—requesting searches, asking user questions, and deciding when it has enough information—before proceeding to peer ranking and synthesis.

## Goals

1. **Reduce uncertainty** - Show real-time progress as each model works through its iterations
2. **Debugging transparency** - See what each model is asking for and researching
3. **Model autonomy** - Let models work at their own pace, finishing early if they have enough info

## Architecture

### Current Flow (Being Replaced)

```
Stage 0 (sync) → Stage 1 (sync) → Stage 2 → Stage 3
```

### New Flow

```
┌─────────────────────────────────────────────────────────┐
│  ITERATIVE PHASE (per-model agentic loops)              │
│                                                         │
│  Each model independently (up to N rounds, default 3):  │
│    1. Analyze what info it needs                        │
│    2. Request web searches and/or user questions        │
│    3. Receive results (searches auto-run)               │
│    4. Decide: need more info → next round               │
│               OR ready → declare READY                  │
│                                                         │
│  Per round (batched):                                   │
│    - All model requests collected                       │
│    - Chairman aggregates/deduplicates questions         │
│    - Searches execute automatically                     │
│    - User answers aggregated questions                  │
│    - Answers routed only to models that asked           │
│                                                         │
│  Exit when: all models READY or max rounds reached      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  EVALUATION PHASE (unchanged)                           │
│                                                         │
│  Stage 2: Peer ranking (anonymized)                     │
│  Stage 3: Chairman synthesis                            │
└─────────────────────────────────────────────────────────┘
```

## Round Lifecycle

Each round follows this sequence:

### 1. THINK

All models receive: user query + their accumulated context.

Each model outputs structured response:
```json
{
  "status": "needs_info" | "ready",
  "searches": ["query1", "query2"],
  "questions": ["question for user"],
  "response": "final answer (if ready)"
}
```

Models run in parallel, results collected.

### 2. AGGREGATE (Chairman)

- Collect all search requests → execute automatically
- Collect all user questions → deduplicate/rephrase
- Track which model asked which question
- Output: search results + curated question list

### 3. USER INPUT

If any questions exist:
- Display search results (for transparency)
- Display aggregated questions
- User provides answers

If no questions, skip to step 4.

### 4. DISTRIBUTE

- Route answers only to models that asked
- Route search results to models that requested them
- Models marked "ready" are done (skip future rounds)
- Remaining models proceed to next round

### 5. REPEAT or EXIT

- If all models ready → proceed to Stage 2
- If max rounds reached → force completion
- Otherwise → next round

## Per-Model Context

Each model maintains its own context across rounds:

- Original user query
- Its own questions + answers received
- Its own search requests + results received
- Previous round outputs (its own only)

This ensures true agent independence—models build different knowledge bases based on what they chose to ask.

## Frontend UI

### Progress Grid

```
             R1      R2      R3      Status
GPT-5        ✓       ⏳      ·       Searching...
Claude       ●       —       —       READY
Gemini       ✓       ✓       ⏳      Thinking...
                                     ───────
                                     1/3 ready
```

**Legend:**
- `✓` = Round complete, continuing to next
- `●` = Final round (model declared READY here)
- `⏳` = Currently in progress
- `·` = Not yet started
- `—` = Skipped (model finished early)

### Question Form (Per Round)

```
ROUND 2 - Questions for you:

1. What's your expected scale? (GPT, Gemini)
   [___________________________________]

2. Any existing infrastructure? (GPT)
   [___________________________________]

Searches completed: 3  [▼ View results]

[Submit Answers]  [Skip Round]
```

Shows which models asked each question for transparency.

### Response Display

**Tabs (default):**

```
┌──────────┬──────────┬──────────┐
│ GPT-5 ✓  │ Claude ✓ │ Gemini ✓ │
└──────────┴──────────┴──────────┘
┌────────────────────────────────┐
│ [Response content...]          │
│                                │
│ Completed in 2 rounds          │
│ Asked 2 questions, 1 search    │
└────────────────────────────────┘
```

**Compare mode (toggle):**

Side-by-side view with model selection checkboxes. Optimized for 2 models (typical usage).

## Configuration

| Setting | Location | Default | Options |
|---------|----------|---------|---------|
| Max iterations | Per-conversation UI | 3 | 1, 2, 3 |
| Council models | `backend/config.py` | Current list | Model identifiers |
| Chairman model | `backend/config.py` | Current | Model identifier |

### Iteration Selector

Dropdown in conversation UI, next to send button. Default 3, can be reduced for simpler questions.

### Future Configuration Options

- Timeout per model per round
- Enable/disable iteration feature (fallback to legacy behavior)

## Stage 2 & 3

**Unchanged from current implementation:**

- Stage 2: Peer ranking with anonymized responses
- Stage 3: Chairman synthesis with rankings context

## Key Design Decisions

1. **Independent loops** - Models work autonomously, not synchronized per round
2. **Batched user interaction** - Questions collected and deduplicated per round to reduce user interruption
3. **Targeted routing** - Answers only go to models that asked, preserving independence
4. **Chairman aggregation** - Questions curated for clarity, not just mechanically deduplicated
5. **Hybrid iteration control** - Models can finish early (READY) or run to max rounds
6. **Hybrid search visibility** - Searches auto-execute, but results shown to user for transparency

## Files Affected

### Backend

- `backend/council.py` - New iterative phase logic, structured model output parsing
- `backend/main.py` - New SSE events for round progress, integration with iterative phase
- `backend/config.py` - Default iteration count setting

### Frontend

- `frontend/src/App.jsx` - Round state management, progress tracking
- `frontend/src/components/ProgressGrid.jsx` - NEW: Round/model progress display
- `frontend/src/components/RoundQuestions.jsx` - NEW: Per-round question form
- `frontend/src/components/ResponseDisplay.jsx` - NEW: Tabs + compare view for responses
- `frontend/src/components/ChatInterface.jsx` - Integration of new components
