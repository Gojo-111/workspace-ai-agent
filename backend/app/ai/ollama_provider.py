# backend/app/ai/ollama_provider.py
import json
from typing import Any, AsyncIterator, Dict, List, Optional

from ollama import AsyncClient

from app.config.settings import settings
from app.ai.provider import LLMProvider


class OllamaProvider(LLMProvider):
    """Ollama implementation of the LLM provider interface."""

    def __init__(self) -> None:
        base_url = settings.ollama_base_url or "http://localhost:11434"
        self.client = AsyncClient(host=base_url)

    async def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a non‑streaming response from Ollama."""
        params: Dict[str, Any] = {
            "model": kwargs.get("model", "llama3.2"),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 4096),
            },
        }

        if tools:
            params["tools"] = tools

        response = await self.client.chat(**params)

        message = response["message"]

        result: Dict[str, Any] = {
            "content": message.get("content"),
        }

        if message.get("tool_calls"):
            result["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for i, tc in enumerate(message["tool_calls"])
            ]

        return result

    async def stream(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a response from Ollama, yielding content chunks as they arrive."""
        params: Dict[str, Any] = {
            "model": kwargs.get("model", "llama3.2"),
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 4096),
            },
        }

        if tools:
            params["tools"] = tools

        async for chunk in await self.client.chat(**params):
            if "message" in chunk and "content" in chunk["message"]:
                content = chunk["message"]["content"]
                if content:
                    yield content