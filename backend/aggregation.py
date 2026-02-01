def aggregate_questions(questions_by_model: dict[str, list[str]]) -> list[dict]:
    """
    Aggregate and deduplicate questions from multiple models.

    Returns: [{"text": str, "asked_by": [model_ids]}]
    """
    # Simple deduplication by lowercase normalization
    question_map = {}

    for model_id, questions in questions_by_model.items():
        for q in questions:
            # Normalize: lowercase, expand contractions, remove punctuation, collapse whitespace
            normalized = q.lower().strip().rstrip("?")
            # Basic contraction expansion
            normalized = normalized.replace("what's", "what is")
            normalized = normalized.replace("'s", " is")
            normalized = normalized.replace("'", "").replace(",", "")
            normalized = " ".join(normalized.split())

            if normalized not in question_map:
                question_map[normalized] = {
                    "text": q,  # Keep original formatting
                    "asked_by": []
                }

            if model_id not in question_map[normalized]["asked_by"]:
                question_map[normalized]["asked_by"].append(model_id)

    return list(question_map.values())
