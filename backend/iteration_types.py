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


class IterationState(BaseModel):
    """Serializable state for pausing/resuming iteration."""
    user_query: str
    round_num: int
    max_iterations: int
    model_states: dict[str, dict]  # Serialized ModelRoundState
    pending_questions: list[dict]  # [{"text": str, "asked_by": [model_ids]}]
