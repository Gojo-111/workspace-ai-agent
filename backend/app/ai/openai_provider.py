# backend/app/ai/openai_provider.py
import json
from typing import Any, AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI

from app.config.settings import settings
from app.ai.provider import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI implementation of the LLM provider interface."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a non-streaming response from OpenAI."""
        params: Dict[str, Any] = {
            "model": kwargs.get("model", "gpt-4o-mini"),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**params)

        choice = response.choices[0]
        message = choice.message

        result: Dict[str, Any] = {
            "content": message.content,
        }

        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    },
                }
                for tc in message.tool_calls
            ]

        return result

    async def stream(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a response from OpenAI, yielding content chunks as they arrive."""
        params: Dict[str, Any] = {
            "model": kwargs.get("model", "gpt-4o-mini"),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        stream = await self.client.chat.completions.create(**params)

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content