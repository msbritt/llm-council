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
from .config import ENABLE_CLARIFICATION_ROUND

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
                yield f"data: {json.dumps({'type': 'stage0_start'})}\n\n"

                stage0_results = await stage0_collect_questions(request.content)
                yield f"data: {json.dumps({'type': 'stage0_questions_collected', 'data': stage0_results})}\n\n"

                aggregated = await stage0_chairman_aggregate(request.content, stage0_results)

                # Perform research automatically
                research_results = {}
                if aggregated.get('research_queries'):
                    yield f"data: {json.dumps({'type': 'stage0_research_start'})}\n\n"
                    research_results = await perform_batch_research(aggregated['research_queries'])
                    yield f"data: {json.dumps({'type': 'stage0_research_complete', 'data': research_results})}\n\n"

                # If there are user questions, pause and wait for answers
                if aggregated.get('user_questions'):
                    yield f"data: {json.dumps({'type': 'stage0_needs_user_input', 'user_questions': aggregated['user_questions'], 'research_results': research_results})}\n\n"
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
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content, enriched_context)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results)
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
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

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
