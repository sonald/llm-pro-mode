
"""Unit tests for core llm_client abstractions."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from litellm import token_counter

from llm_pro_mode.config import Config
from llm_pro_mode.core.llm_client import (
    LLMClient,
    LLMRequest,
    _normalize_reasoning_payload,
)


def _make_client(config: Config) -> LLMClient:
    return LLMClient(
        model_name=config.model_name,
        api_base=config.api_base,
        api_key=config.api_key,
        default_temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


@pytest.mark.asyncio
async def test_stream_chunks_normalizes_reasoning_payload(mock_trace_logger):
    """LLMClient should emit normalized thinking and content chunks."""
    async def response_stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content=[{"text": "First"}, {"text": "Second"}],
                        reasoning=None,
                    ),
                    finish_reason=None,
                )
            ]
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="Hello",
                        reasoning_content=None,
                        reasoning=None,
                    ),
                    finish_reason="stop",
                )
            ]
        )

    completion_mock = AsyncMock(return_value=response_stream())
    test_config = Config(model_name="gpt-3.5-turbo")
    client = _make_client(test_config)
    client._completion_fn = completion_mock  # Inject mock transport

    request = LLMRequest(
        prompt="Test prompt",
        trace_logger=mock_trace_logger,
        trace_id="trace-1",
    )

    chunks = []
    async for chunk in client.stream_chunks(request):
        chunks.append(chunk)

    assert [chunk.kind for chunk in chunks] == ["thinking", "content"]
    expected_model = test_config.model_name or "gpt-3.5-turbo"
    assert chunks[0].text == "FirstSecond"
    assert chunks[0].thinking_count == token_counter(
        model=expected_model, text="FirstSecond"
    )
    assert chunks[0].token_count == 0
    assert chunks[1].text == "Hello"
    assert chunks[1].token_count == token_counter(
        model=expected_model, text="Hello"
    )
    assert chunks[1].finish_reason == "stop"

    mock_trace_logger.log_thinking.assert_called_once_with("mock-trace-id", "FirstSecond")
    mock_trace_logger.log_content.assert_called_once_with("mock-trace-id", "Hello")
    mock_trace_logger.finish_task.assert_called_once()


@pytest.mark.asyncio
async def test_gather_result_accumulates_text_and_counts():
    """gather_result should compose text and counters from streamed chunks."""
    async def response_stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content="Thinking",
                        reasoning=None,
                    ),
                    finish_reason=None,
                )
            ]
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="Hello",
                        reasoning_content=None,
                        reasoning=None,
                    ),
                    finish_reason=None,
                )
            ]
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=" World",
                        reasoning_content=None,
                        reasoning=None,
                    ),
                    finish_reason="stop",
                )
            ]
        )

    completion_mock = AsyncMock(return_value=response_stream())
    test_config = Config(model_name="gpt-3.5-turbo")
    client = _make_client(test_config)
    client._completion_fn = completion_mock

    request = LLMRequest(prompt="Test prompt")
    result = await client.gather_result(request)

    expected_model = test_config.model_name or "gpt-3.5-turbo"
    assert result.content == "Hello World"
    assert result.token_count == token_counter(
        model=expected_model, text="Hello World"
    )
    assert result.thinking_count == token_counter(
        model=expected_model, text="Thinking"
    )
    assert result.finish_reason == "stop"


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("plain text", "plain text"),
        (["one", {"text": "two"}], "onetwo"),
        ({"message": "inner"}, "inner"),
        ({"unused": "value"}, '{"unused": "value"}'),
        (None, ""),
    ],
)
def test_normalize_reasoning_payload_variants(payload, expected):
    """Ensure reasoning payload normalization handles nested structures."""
    assert _normalize_reasoning_payload(payload) == expected
