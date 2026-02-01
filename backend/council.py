"""3-stage LLM Council orchestration with optional Stage 0 clarification."""

from typing import List, Dict, Any, Tuple, Optional
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL
import re


# ============================================================================
# Stage 0: Clarification Round
# ============================================================================

async def stage0_collect_questions(user_query: str) -> List[Dict[str, Any]]:
    """
    Stage 0: Ask each council model what clarifying questions it needs.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model', 'raw_response', and 'questions' keys
    """
    clarification_prompt = f"""You are part of an LLM Council that will answer the following question:

Question: {user_query}

Before the council provides a response, you have an opportunity to ask clarifying questions that would help you provide a better answer.

Your task:
1. Identify up to 3 clarifying questions that would significantly improve your response
2. For each question, determine if it requires USER input or can be answered via RESEARCH (web search)

Strategic guidelines:
- Focus on information gaps that could change your answer substantially
- Don't ask about things already clear from the question
- Prioritize questions that address ambiguity, missing context, or assumptions
- Consider: What would you need to know to give the most accurate, relevant answer?

Format your response EXACTLY as follows:

QUESTIONS:
1. [USER] What is your specific use case or context?
2. [RESEARCH] What is the current market size for X?
3. [USER] What are your constraints or requirements?

Important:
- Use [USER] for questions that need human input (preferences, context, constraints, personal situations)
- Use [RESEARCH] for questions that can be answered by searching the web (current facts, recent data, documentation, news)
- Ask only questions that would meaningfully impact your answer quality
- Avoid redundant questions that restate what's already in the original query
- If no clarifying questions are needed, respond with "QUESTIONS: None needed"
- Maximum 3 questions

Provide your questions now:"""

    messages = [{"role": "user", "content": clarification_prompt}]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results and parse questions
    stage0_results = []
    for model, response in responses.items():
        if response is not None:
            raw_response = response.get('content', '')
            questions = stage0_parse_questions(raw_response)
            stage0_results.append({
                "model": model,
                "raw_response": raw_response,
                "questions": questions
            })

    return stage0_results


def stage0_parse_questions(response_text: str) -> List[Dict[str, str]]:
    """
    Parse questions from a model's Stage 0 response.

    Args:
        response_text: The model's raw response

    Returns:
        List of dicts with 'type' (USER/RESEARCH) and 'question' keys
    """
    questions = []

    # Look for QUESTIONS: section
    if "QUESTIONS:" not in response_text:
        return questions

    # Extract everything after "QUESTIONS:"
    parts = response_text.split("QUESTIONS:")
    if len(parts) < 2:
        return questions

    questions_section = parts[1]

    # Check for "None needed" case
    if "none needed" in questions_section.lower():
        return questions

    # Parse each line looking for [USER] or [RESEARCH] tags
    lines = questions_section.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Look for [USER] or [RESEARCH] tags
        user_match = re.search(r'\[USER\]\s*(.+)', line, re.IGNORECASE)
        research_match = re.search(r'\[RESEARCH\]\s*(.+)', line, re.IGNORECASE)

        if user_match:
            question_text = user_match.group(1).strip()
            # Remove leading number and period if present
            question_text = re.sub(r'^\d+\.\s*', '', question_text)
            questions.append({
                "type": "USER",
                "question": question_text
            })
        elif research_match:
            question_text = research_match.group(1).strip()
            # Remove leading number and period if present
            question_text = re.sub(r'^\d+\.\s*', '', question_text)
            questions.append({
                "type": "RESEARCH",
                "question": question_text
            })

    return questions


async def stage0_chairman_aggregate(
    user_query: str,
    stage0_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Stage 0: Chairman reviews all questions and creates consolidated list.

    Args:
        user_query: The original user query
        stage0_results: Questions collected from all models

    Returns:
        Dict with 'user_questions' and 'research_queries' lists
    """
    # Collect all questions from models
    all_questions = []
    for result in stage0_results:
        model = result['model']
        for q in result.get('questions', []):
            all_questions.append({
                "model": model,
                "type": q['type'],
                "question": q['question']
            })

    # If no questions were asked, return empty lists
    if not all_questions:
        return {
            "user_questions": [],
            "research_queries": []
        }

    # Format questions for chairman
    questions_text = "\n".join([
        f"- [{q['type']}] {q['question']} (from {q['model']})"
        for q in all_questions
    ])

    chairman_prompt = f"""You are the Chairman of an LLM Council. The council members have reviewed this question:

Question: {user_query}

Each council member has identified clarifying questions they need answered. Here are all their questions:

{questions_text}

Your task is to create a consolidated question list for the user that:
1. Represents every distinct information need identified by the council members
2. Combines similar or overlapping questions into single, well-crafted questions
3. Rewords questions to be clear and easy for the user to understand
4. Ensures no council member's concern is left unaddressed
5. Stays within 8 questions maximum (use fewer when possible)
6. Prioritizes questions that would most improve the council's ability to help

When consolidating:
- If 3 models ask about "budget", "cost constraints", and "price range" → merge into one question about budget parameters
- If questions differ only slightly, create one question that covers all variations
- Keep each consolidated question focused on a single topic
- Maintain the [USER] and [RESEARCH] categorization

Format your response EXACTLY as follows:

USER_QUESTIONS:
1. Question text here
2. Another question here

RESEARCH_QUERIES:
1. Query text here
2. Another query here

Important:
- Use USER_QUESTIONS for questions requiring human input
- Use RESEARCH_QUERIES for questions that can be answered via web search
- If a category has no questions, write "None"
- Maximum 8 total questions combined
- Be selective - only include questions that truly matter

Provide your consolidated questions now:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback: return empty lists if chairman fails
        return {
            "user_questions": [],
            "research_queries": []
        }

    # Parse the chairman's response
    return stage0_parse_aggregated(response.get('content', ''))


def stage0_parse_aggregated(response_text: str) -> Dict[str, Any]:
    """
    Parse the chairman's aggregated questions response.

    Args:
        response_text: The chairman's response

    Returns:
        Dict with 'user_questions' and 'research_queries' lists
    """
    result = {
        "user_questions": [],
        "research_queries": []
    }

    # Extract USER_QUESTIONS section
    if "USER_QUESTIONS:" in response_text:
        parts = response_text.split("USER_QUESTIONS:")
        if len(parts) >= 2:
            # Find where this section ends (either at RESEARCH_QUERIES or end of text)
            user_section = parts[1]
            if "RESEARCH_QUERIES:" in user_section:
                user_section = user_section.split("RESEARCH_QUERIES:")[0]

            # Parse numbered list
            lines = user_section.split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.lower() == "none":
                    continue
                # Remove leading number and period
                question = re.sub(r'^\d+\.\s*', '', line)
                if question and len(question) > 3:  # Avoid very short/invalid entries
                    result["user_questions"].append({
                        "id": f"q{len(result['user_questions']) + 1}",
                        "question": question
                    })

    # Extract RESEARCH_QUERIES section
    if "RESEARCH_QUERIES:" in response_text:
        parts = response_text.split("RESEARCH_QUERIES:")
        if len(parts) >= 2:
            research_section = parts[1]

            # Parse numbered list
            lines = research_section.split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.lower() == "none":
                    continue
                # Remove leading number and period
                query = re.sub(r'^\d+\.\s*', '', line)
                if query and len(query) > 3:  # Avoid very short/invalid entries
                    result["research_queries"].append({
                        "id": f"r{len(result['research_queries']) + 1}",
                        "query": query
                    })

    return result


def build_enriched_context(
    user_query: str,
    user_answers: Optional[Dict[str, str]] = None,
    research_results: Optional[Dict[str, str]] = None,
    user_questions: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Build enriched context from clarification responses.

    Args:
        user_query: The original query
        user_answers: Dict mapping question IDs to user's answers
        research_results: Dict mapping query IDs to research results
        user_questions: List of question dicts with 'id' and 'question'

    Returns:
        Formatted context string to prepend to the query
    """
    context_parts = []

    # Add user answers if provided
    if user_answers:
        context_parts.append("CLARIFYING INFORMATION:")

        # Build a lookup of question ID to question text
        question_lookup = {}
        if user_questions:
            for q in user_questions:
                question_lookup[q['id']] = q['question']

        for question_id, answer in user_answers.items():
            question_text = question_lookup.get(question_id, "Clarification")
            context_parts.append(f"\nQ: {question_text}\nA: {answer}")

    # Add research results if provided
    if research_results:
        if not context_parts:
            context_parts.append("BACKGROUND RESEARCH:")
        else:
            context_parts.append("\n\nBACKGROUND RESEARCH:")

        for query_id, result in research_results.items():
            context_parts.append(f"\n{result}")

    # Combine with original query
    if context_parts:
        enriched = "\n".join(context_parts)
        return f"{enriched}\n\n---\n\nOriginal Question: {user_query}"

    return user_query


# ============================================================================
# Agentic Iteration Phase
# ============================================================================

from .iteration_types import ModelIterationRequest, ModelRoundState
from .aggregation import aggregate_questions
from .search import execute_search
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
        messages = [{"role": "user", "content": prompt}]
        response = await query_model(state.model_id, messages)

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


# ============================================================================
# Stage 1: Individual Responses
# ============================================================================

async def stage1_collect_responses(user_query: str, enriched_context: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question
        enriched_context: Optional enriched context from Stage 0 clarifications

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    # Use enriched context if provided, otherwise use original query
    query_text = enriched_context if enriched_context else user_query
    messages = [{"role": "user", "content": query_text}]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', '')
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually based on these criteria:
   - ACCURACY: Is the information factually correct?
   - COMPLETENESS: Does it thoroughly address all aspects of the question?
   - CLARITY: Is it well-organized and easy to understand?
   - RELEVANCE: Does it stay focused on what was asked?
   - INSIGHT: Does it provide valuable perspective or depth?

2. For each response, explain what it does well and what it does poorly.

3. Then, at the very end of your response, provide a final ranking based on overall quality.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question.

Synthesis approach:
1. IDENTIFY CONSENSUS: Note where models agree - these points likely have strong support
2. WEIGH RANKINGS: Give more weight to insights from highly-ranked responses
3. RESOLVE DISAGREEMENTS: Where models conflict, evaluate which perspective is most accurate/complete
4. INTEGRATE STRENGTHS: Combine the best elements from each response
5. ADDRESS GAPS: If all responses missed something important, include it
6. ACKNOWLEDGE UNCERTAINTY: If there's genuine disagreement on facts or approach, note it

Your final answer should:
- Be comprehensive and accurate, drawing from the strongest insights across all responses
- Resolve contradictions by selecting the most well-supported position
- Highlight areas of consensus while addressing important dissenting views
- Be clear and well-organized for the user
- Represent the council's collective wisdom, not just repeat the top-ranked response

Provide your synthesized final answer now:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', '')
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_council(
    user_query: str,
    clarifications: Optional[Dict[str, Any]] = None
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question
        clarifications: Optional clarifications from Stage 0

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Build enriched context if clarifications provided
    enriched_context = None
    if clarifications:
        # Extract user_questions from stage0_data if available
        user_questions = None
        stage0_data = clarifications.get('stage0_data')
        if stage0_data:
            user_questions = stage0_data.get('user_questions')

        enriched_context = build_enriched_context(
            user_query,
            clarifications.get('user_answers'),
            clarifications.get('research_results'),
            user_questions
        )

    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(user_query, enriched_context)

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings
    }

    return stage1_results, stage2_results, stage3_result, metadata
