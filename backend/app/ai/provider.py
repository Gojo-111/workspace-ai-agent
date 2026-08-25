# backend/app/ai/provider.py
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional


class LLMProvider(ABC):
    """Abstract interface for LLM providers (OpenAI, Ollama, etc.)."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Generate a complete (non-streaming) response.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions (name, description, parameters).
            **kwargs: Provider-specific options (temperature, max_tokens, etc.).

        Returns:
            A dict with at least:
                - "content": the text response (str), or None if tool call.
                - "tool_calls": optional list of tool call dicts.
        """
        pass

    @abstractmethod
    async def stream(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream a response incrementally.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            **kwargs: Provider-specific options.

        Yields:
            Text chunks as they become available.
        """
        pass