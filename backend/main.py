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
    from .council import run_iterative_phase, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings, serialize_model_states, deserialize_model_states, apply_answers_to_states
    from .config import DEFAULT_MAX_ITERATIONS

    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_message = request.content

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, user_message)

            # Generate title in parallel if first message
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(user_message))

            # Check if resuming from previous iteration
            iteration_state = request.clarifications.get("iteration_state") if request.clarifications else None

            # Extract max_iterations - check iteration_state first (for resume), then top-level clarifications
            if iteration_state:
                max_iterations = iteration_state.get("max_iterations", DEFAULT_MAX_ITERATIONS)
            else:
                max_iterations = request.clarifications.get("max_iterations", DEFAULT_MAX_ITERATIONS) if request.clarifications else DEFAULT_MAX_ITERATIONS

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

            # Start iteration phase
            yield f"event: phase_start\ndata: {json.dumps({'type': 'phase_start', 'phase': 'iteration'})}\n\n"

            final_states, pending_questions, round_history = await run_iterative_phase(
                user_message,
                COUNCIL_MODELS,
                max_iterations,
                user_answer_callback=None,
                start_round=start_round,
                initial_states=initial_states,
                previous_round_history=previous_round_history
            )

            # If there are pending questions, pause for user input
            if pending_questions:
                print(f"[DEBUG] Sending questions_needed event with {len(pending_questions)} questions")
                # Send questions_needed event with full state for resume
                event_data = {
                    'type': 'questions_needed',
                    'questions': pending_questions,
                    'round_history': round_history,
                    'iteration_state': {
                        'user_query': user_message,
                        'round_num': round_history[-1]["roundNum"] if round_history else start_round,
                        'max_iterations': max_iterations,
                        'model_states': serialize_model_states(final_states),
                        'pending_questions': pending_questions,
                        'round_history': round_history,
                    }
                }
                print(f"[DEBUG] Event data keys: {event_data.keys()}")
                yield f"event: questions_needed\ndata: {json.dumps(event_data)}\n\n"
                print(f"[DEBUG] Returned from event_generator - stream should end here")
                return  # End stream, wait for resubmit with answers

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

            # Validate that we have at least one valid response
            valid_responses = [
                r for r in stage1_responses
                if r['response'] not in ["[Model failed to respond]", "[No response after max iterations]"]
            ]

            if len(valid_responses) == 0:
                # All models failed - cannot continue
                error_message = "All models failed to provide valid responses. Please try again."
                print(f"[ERROR] All models failed during iteration")

                # Send Stage 1 completion with error indicator
                yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_responses, 'round_history': round_history, 'all_failed': True})}\n\n"

                # Send error and complete
                yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            # Send Stage 1 completion with round history
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_responses, 'round_history': round_history})}\n\n"

            # Start Stage 2
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"

            # Run Stage 2 with only valid responses
            stage2_rankings, label_to_model = await stage2_collect_rankings(user_message, valid_responses)

            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_rankings, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': calculate_aggregate_rankings(stage2_rankings, label_to_model)}})}\n\n"

            # Start Stage 3
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"

            # Use valid responses for synthesis (Stage 3 chairman shouldn't see failures)
            stage3_synthesis = await stage3_synthesize_final(
                user_message,
                valid_responses,
                stage2_rankings
            )

            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_synthesis})}\n\n"

            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_responses,
                stage2_rankings,
                stage3_synthesis,
                request.clarifications
            )

            # Wait for title if needed
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)

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
