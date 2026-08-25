# backend/app/ai/provider_factory.py
from app.ai.openai_provider import OpenAIProvider
from app.ai.ollama_provider import OllamaProvider
from app.ai.provider import LLMProvider
from app.config.settings import settings


def get_provider() -> LLMProvider:
    """Return the active LLM provider based on settings.AI_PROVIDER."""
    provider_name = settings.ai_provider.lower()

    if provider_name == "openai":
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key is required when AI_PROVIDER is 'openai'")
        return OpenAIProvider()

    if provider_name == "ollama":
        return OllamaProvider()

    raise ValueError(
        f"Unknown AI provider: {settings.ai_provider}. "
        "Valid options: 'openai', 'ollama'."
    )