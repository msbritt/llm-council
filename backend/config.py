"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Search API configuration for Stage 0 research
SEARCH_API_TYPE = os.getenv("SEARCH_API_TYPE", "tavily")  # Options: "tavily", "serpapi"
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")  # Optional - research will be skipped if not set
SEARCH_API_URL = os.getenv("SEARCH_API_URL")  # Optional - may be needed depending on API type

# Enable/disable Stage 0 clarification round
ENABLE_CLARIFICATION_ROUND = os.getenv("ENABLE_CLARIFICATION_ROUND", "true").lower() == "true"

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.2",
    "anthropic/claude-opus-4.5"
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# Agentic iteration configuration
DEFAULT_MAX_ITERATIONS = 3
ITERATION_TIMEOUT_SECONDS = 60  # Per model per round

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"
