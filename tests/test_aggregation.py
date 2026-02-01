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
