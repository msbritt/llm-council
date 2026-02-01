"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from .council import (
    run_full_council,
    generate_conversation_title,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
    calculate_aggregate_rankings,
    stage0_collect_questions,
    stage0_chairman_aggregate
)
from .research import perform_batch_research
from .config import ENABLE_CLARIFICATION_ROUND, COUNCIL_MODELS

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    clarifications: Optional[Dict[str, Any]] = None


class UpdateConversationRequest(BaseModel):
    """Request to update conversation metadata."""
    title: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.patch("/api/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, request: UpdateConversationRequest):
    """Update a conversation's title."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    storage.update_conversation_title(conversation_id, request.title)
    return {"id": conversation_id, "title": request.title}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str):
    """Delete a conversation."""
    deleted = storage.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"status": "deleted", "id": conversation_id}


@app.post("/api/conversations/{conversation_id}/clarify")
async def clarify_question(conversation_id: str, request: SendMessageRequest):
    """
    Run Stage 0 clarification round to collect questions from models.
    Returns user questions and automatically performed research results.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if clarification is enabled
    if not ENABLE_CLARIFICATION_ROUND:
        return {
            "user_questions": [],
            "research_results": {},
            "stage0_raw": []
        }

    # Stage 0: Collect questions from all models
    stage0_results = await stage0_collect_questions(request.content)

    # Chairman aggregates questions
    aggregated = await stage0_chairman_aggregate(request.content, stage0_results)

    # Perform research for RESEARCH_QUERIES
    research_results = {}
    if aggregated.get('research_queries'):
        research_results = await perform_batch_research(aggregated['research_queries'])

    return {
        "user_questions": aggregated.get('user_questions', []),
        "research_results": research_results,
        "stage0_raw": stage0_results  # For debugging/transparency
    }


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process (with optional clarifications)
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        request.clarifications
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        request.clarifications
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            print(f"\n{'='*60}")
            print(f"[STREAM] Starting council process for conversation {conversation_id}")
            print(f"[STREAM] Query: {request.content[:100]}...")
            print(f"{'='*60}\n")

            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Build enriched context if clarifications provided
            enriched_context = None
            if request.clarifications:
                from .council import build_enriched_context
                # Extract user_questions from stage0_data if available
                user_questions = None
                stage0_data = request.clarifications.get('stage0_data')
                if stage0_data:
                    user_questions = stage0_data.get('user_questions')

                enriched_context = build_enriched_context(
                    request.content,
                    request.clarifications.get('user_answers'),
                    request.clarifications.get('research_results'),
                    user_questions
                )

            # Stage 0 (optional): If no clarifications provided and feature enabled, collect questions
            if not request.clarifications and ENABLE_CLARIFICATION_ROUND:
                print(f"[STAGE 0] Starting - enabled={ENABLE_CLARIFICATION_ROUND}, has_clarifications={request.clarifications is not None}")
                yield f"data: {json.dumps({'type': 'stage0_start'})}\n\n"

                print(f"[STAGE 0] Collecting questions from {len(COUNCIL_MODELS)} models")
                stage0_results = await stage0_collect_questions(request.content)
                print(f"[STAGE 0] Collected {len(stage0_results)} question sets")
                yield f"data: {json.dumps({'type': 'stage0_questions_collected', 'data': stage0_results})}\n\n"

                print(f"[STAGE 0] Chairman aggregating questions")
                aggregated = await stage0_chairman_aggregate(request.content, stage0_results)
                print(f"[STAGE 0] Aggregated: {len(aggregated.get('user_questions', []))} user questions, {len(aggregated.get('research_queries', []))} research queries")

                # Perform research automatically
                research_results = {}
                if aggregated.get('research_queries'):
                    yield f"data: {json.dumps({'type': 'stage0_research_start'})}\n\n"
                    research_results = await perform_batch_research(aggregated['research_queries'])
                    yield f"data: {json.dumps({'type': 'stage0_research_complete', 'data': research_results})}\n\n"

                # If there are user questions, pause and wait for answers
                if aggregated.get('user_questions'):
                    yield f"data: {json.dumps({'type': 'stage0_needs_user_input', 'user_questions': aggregated['user_questions'], 'research_results': research_results, 'stage0_raw': stage0_results})}\n\n"
                    # Stream will pause here - frontend needs to reconnect with clarifications
                    return

                # If only research queries (no user input needed), build enriched context
                if research_results:
                    from .council import build_enriched_context
                    enriched_context = build_enriched_context(
                        request.content,
                        None,
                        research_results
                    )

                yield f"data: {json.dumps({'type': 'stage0_complete'})}\n\n"

            # Stage 1: Collect responses
            print(f"[STAGE 1] Starting - collecting individual responses from {len(COUNCIL_MODELS)} models")
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content, enriched_context)
            print(f"[STAGE 1] Complete - received {len(stage1_results)} responses")
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            print(f"[STAGE 2] Starting - collecting peer rankings")
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            print(f"[STAGE 2] Complete - received {len(stage2_results)} rankings")
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            print(f"[STAGE 3] Starting - chairman synthesizing final answer")
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results)
            print(f"[STAGE 3] Complete - synthesis finished")
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                request.clarifications
            )

            # Send completion event
            print(f"[STREAM] Council process complete\n{'='*60}\n")
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            print(f"[ERROR] Council process failed: {str(e)}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/conversations/{conversation_id}/message-stream")
async def send_message_with_iteration(conversation_id: str, request: SendMessageRequest):
    """
    Send a message with SSE progress updates during iteration phase.
    """
    from fastapi.responses import StreamingResponse
    from .council import run_iterative_phase, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings
    from .config import DEFAULT_MAX_ITERATIONS

    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_message = request.content
    max_iterations = request.clarifications.get("max_iterations", DEFAULT_MAX_ITERATIONS) if request.clarifications else DEFAULT_MAX_ITERATIONS

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        import time
        def log(msg):
            print(f"[{time.strftime('%H:%M:%S')}] {msg}")

        log(f"[SSE] Event generator started for conversation {conversation_id}")
        try:
            # Add user message
            log("[SSE] Adding user message...")
            storage.add_user_message(conversation_id, user_message)
            log("[SSE] User message added")

            # Generate title in parallel if first message
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(user_message))

            # For now, use None callback (no user interaction during iteration)
            # Future enhancement: implement proper bidirectional communication
            answer_callback = None

            # Start iteration phase
            log("[SSE] Yielding phase_start event...")
            yield f"event: phase_start\ndata: {json.dumps({'type': 'phase_start', 'phase': 'iteration'})}\n\n"

            log(f"[SSE] Starting run_iterative_phase with max_iterations={max_iterations}")
            final_states = await run_iterative_phase(
                user_message,
                COUNCIL_MODELS,
                max_iterations,
                answer_callback
            )
            log("[SSE] run_iterative_phase completed")

            # Send completion
            log("[SSE] Yielding iteration_complete event...")
            yield f"event: iteration_complete\ndata: {json.dumps({'type': 'iteration_complete', 'states': {mid: {'rounds': s.current_round, 'response': s.final_response} for mid, s in final_states.items()}})}\n\n"
            log("[SSE] iteration_complete event yielded")

            # Continue with Stage 2 & 3
            log("[SSE] Yielding phase_start for stage2...")
            yield f"event: phase_start\ndata: {json.dumps({'type': 'phase_start', 'phase': 'stage2'})}\n\n"
            log("[SSE] phase_start event yielded")

            # Prepare responses for Stage 2
            log("[SSE] Preparing responses for Stage 2...")
            stage1_responses = [
                {
                    "model": mid,
                    "response": state.final_response
                }
                for mid, state in final_states.items()
            ]
            log(f"[SSE] Prepared {len(stage1_responses)} responses for Stage 2")

            # Run Stage 2
            log("[SSE] Starting stage2_collect_rankings...")
            stage2_rankings, label_to_model = await stage2_collect_rankings(user_message, stage1_responses)
            log("[SSE] stage2_collect_rankings completed")

            log("[SSE] Yielding stage2_complete event...")
            yield f"event: stage2_complete\ndata: {json.dumps({'type': 'stage2_complete', 'rankings': stage2_rankings, 'label_to_model': label_to_model})}\n\n"
            log("[SSE] stage2_complete event yielded")

            # Run Stage 3
            log("[SSE] Yielding phase_start for stage3...")
            yield f"event: phase_start\ndata: {json.dumps({'type': 'phase_start', 'phase': 'stage3'})}\n\n"
            log("[SSE] phase_start event yielded")

            log("[SSE] Starting stage3_synthesize_final...")
            stage3_synthesis = await stage3_synthesize_final(
                user_message,
                stage1_responses,
                stage2_rankings
            )
            log("[SSE] stage3_synthesize_final completed")

            log("[SSE] Yielding complete event...")
            yield f"event: complete\ndata: {json.dumps({'type': 'complete', 'stage3': stage3_synthesis, 'aggregate_rankings': calculate_aggregate_rankings(stage2_rankings, label_to_model)})}\n\n"
            log("[SSE] complete event yielded")

            # Save complete assistant message
            log("[SSE] Saving assistant message...")
            storage.add_assistant_message(
                conversation_id,
                stage1_responses,
                stage2_rankings,
                stage3_synthesis,
                request.clarifications
            )
            log("[SSE] Assistant message saved")

            # Wait for title if needed
            if title_task:
                log("[SSE] Waiting for title generation...")
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                log("[SSE] Title updated")

            log("[SSE] Event generator completed successfully")

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
