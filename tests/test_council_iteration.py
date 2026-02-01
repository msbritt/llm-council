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
