# backend/tests/unit/test_ai_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.provider_factory import get_provider
from app.ai.openai_provider import OpenAIProvider
from app.ai.ollama_provider import OllamaProvider


@pytest.mark.asyncio
async def test_provider_factory_returns_openai():
    # Patch the settings in both the factory (to pass the check) and the provider (to actually use the key)
    with patch("app.ai.provider_factory.settings") as mock_factory_settings:
        mock_factory_settings.ai_provider = "openai"
        mock_factory_settings.openai_api_key = "sk-dummy"
        with patch("app.ai.openai_provider.settings") as mock_provider_settings:
            mock_provider_settings.openai_api_key = "sk-dummy"
            with patch("app.ai.openai_provider.AsyncOpenAI") as mock_openai_class:
                provider = get_provider()
                assert isinstance(provider, OpenAIProvider)
                mock_openai_class.assert_called_once_with(api_key="sk-dummy")


@pytest.mark.asyncio
async def test_provider_factory_returns_ollama():
    with patch("app.ai.provider_factory.settings") as mock_settings:
        mock_settings.ai_provider = "ollama"

        provider = get_provider()
        assert isinstance(provider, OllamaProvider)


@pytest.mark.asyncio
async def test_provider_factory_raises_on_invalid_provider():
    with patch("app.ai.provider_factory.settings") as mock_settings:
        mock_settings.ai_provider = "unknown"

        with pytest.raises(ValueError, match="Unknown AI provider: unknown"):
            get_provider()


@pytest.mark.asyncio
async def test_provider_factory_raises_when_openai_key_missing():
    with patch("app.ai.provider_factory.settings") as mock_settings:
        mock_settings.ai_provider = "openai"
        mock_settings.openai_api_key = None

        with pytest.raises(ValueError, match="OpenAI API key is required"):
            get_provider()


@pytest.mark.asyncio
async def test_openai_provider_generate_returns_content():
    with patch("app.ai.openai_provider.AsyncOpenAI") as mock_openai_class:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = AsyncMock()

        # Mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Hello, world!"
        mock_message.tool_calls = None
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]

        mock_completions.create.return_value = mock_response
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        result = await provider.generate(
            messages=[{"role": "user", "content": "Say hello"}]
        )

        assert result["content"] == "Hello, world!"
        assert "tool_calls" not in result or result["tool_calls"] is None


@pytest.mark.asyncio
async def test_openai_provider_generate_returns_tool_calls():
    with patch("app.ai.openai_provider.AsyncOpenAI") as mock_openai_class:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = AsyncMock()

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = None

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.type = "function"
        mock_tool_call.function.name = "drive_search"
        mock_tool_call.function.arguments = '{"query": "resume"}'
        mock_message.tool_calls = [mock_tool_call]

        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]

        mock_completions.create.return_value = mock_response
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        result = await provider.generate(
            messages=[{"role": "user", "content": "Search for resume"}],
            tools=[{"type": "function", "function": {"name": "drive_search"}}],
        )

        assert result["content"] is None
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["function"]["name"] == "drive_search"


@pytest.mark.asyncio
async def test_openai_provider_stream_yields_chunks():
    with patch("app.ai.openai_provider.AsyncOpenAI") as mock_openai_class:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = AsyncMock()

        # Mock an async iterator that yields chunks
        mock_chunk1 = MagicMock()
        mock_delta1 = MagicMock()
        mock_delta1.content = "Hello"
        mock_chunk1.choices = [MagicMock(delta=mock_delta1)]

        mock_chunk2 = MagicMock()
        mock_delta2 = MagicMock()
        mock_delta2.content = " world"
        mock_chunk2.choices = [MagicMock(delta=mock_delta2)]

        mock_chunk3 = MagicMock()
        mock_delta3 = MagicMock()
        mock_delta3.content = "!"
        mock_chunk3.choices = [MagicMock(delta=mock_delta3)]

        async def mock_stream():
            for chunk in [mock_chunk1, mock_chunk2, mock_chunk3]:
                yield chunk

        mock_completions.create.return_value = mock_stream()
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        chunks = []
        async for chunk in provider.stream(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

        assert chunks == ["Hello", " world", "!"]


@pytest.mark.asyncio
async def test_ollama_provider_generate_returns_content():
    with patch("app.ai.ollama_provider.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.chat = AsyncMock()
        mock_client.chat.return_value = {
            "message": {
                "content": "Hello from Ollama",
                "tool_calls": None,
            }
        }
        mock_client_class.return_value = mock_client

        provider = OllamaProvider()
        result = await provider.generate(
            messages=[{"role": "user", "content": "Say hello"}]
        )

        assert result["content"] == "Hello from Ollama"
        assert "tool_calls" not in result or result["tool_calls"] is None


@pytest.mark.asyncio
async def test_ollama_provider_generate_returns_tool_calls():
    with patch("app.ai.ollama_provider.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.chat = AsyncMock()
        mock_client.chat.return_value = {
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "function": {
                            "name": "drive_search",
                            "arguments": {"query": "resume"},
                        },
                    }
                ],
            }
        }
        mock_client_class.return_value = mock_client

        provider = OllamaProvider()
        result = await provider.generate(
            messages=[{"role": "user", "content": "Search for resume"}],
            tools=[{"type": "function", "function": {"name": "drive_search"}}],
        )

        assert result["content"] is None
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["function"]["name"] == "drive_search"


@pytest.mark.asyncio
async def test_ollama_provider_stream_yields_chunks():
    with patch("app.ai.ollama_provider.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        async def mock_stream():
            yield {"message": {"content": "Hello"}}
            yield {"message": {"content": " from"}}
            yield {"message": {"content": " Ollama"}}

        mock_client.chat = AsyncMock()
        mock_client.chat.return_value = mock_stream()
        mock_client_class.return_value = mock_client

        provider = OllamaProvider()
        chunks = []
        async for chunk in provider.stream(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

        assert chunks == ["Hello", " from", " Ollama"]