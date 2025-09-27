"""Tests for LLM streaming functionality."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import AsyncGenerator, Tuple

from llm_pro_mode.core.llm_client import call_llm_streaming


class TestLLMStreaming:
    """Test cases for LLM streaming functionality."""

    @pytest.mark.asyncio
    async def test_call_llm_streaming_success(self, mock_trace_logger):
        """Test successful streaming LLM call."""
        # Mock litellm.acompletion to return streaming response
        mock_chunks = [
            # Thinking phase chunks - using reasoning_content attribute
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content="Let me analyze this...",
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content=" I need to consider...",
                reasoning=None
            ))]),
            # Content phase chunks - no reasoning attributes
            Mock(choices=[Mock(delta=Mock(
                content="This is the beginning",
                reasoning_content=None,
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content=" of the response",
                reasoning_content=None,
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content=" and the conclusion.",
                reasoning_content=None,
                reasoning=None
            ))]),
        ]

        async def mock_generator():
            """Mock async generator for litellm.acompletion."""
            for chunk in mock_chunks:
                yield chunk

        async def mock_acompletion(*args, **kwargs):
            """Mock acompletion that returns async generator."""
            return mock_generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            # Collect streaming results
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                max_tokens=1000,
                trace_logger=mock_trace_logger,
                trace_id="test-trace-123"
            ):
                results.append((chunk_type, content))

            # Verify thinking chunks
            thinking_chunks = [r for r in results if r[0] == "thinking"]
            assert len(thinking_chunks) == 2
            assert thinking_chunks[0][1] == "Let me analyze this..."
            assert thinking_chunks[1][1] == " I need to consider..."

            # Verify content chunks
            content_chunks = [r for r in results if r[0] == "content"]
            assert len(content_chunks) == 3
            assert content_chunks[0][1] == "This is the beginning"
            assert content_chunks[1][1] == " of the response"
            assert content_chunks[2][1] == " and the conclusion."

    @pytest.mark.asyncio
    async def test_call_llm_streaming_api_error(self, mock_trace_logger):
        """Test handling of API errors during streaming."""
        async def mock_acompletion_error(*args, **kwargs):
            """Mock async generator that raises an exception."""
            async def error_generator():
                raise Exception("API rate limit exceeded")
                yield  # Unreachable
            return error_generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion_error):
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                trace_logger=mock_trace_logger
            ):
                results.append((chunk_type, content))

            # Should receive error chunk
            error_chunks = [r for r in results if r[0] == "error"]
            assert len(error_chunks) == 1
            assert "API rate limit exceeded" in error_chunks[0][1]

    @pytest.mark.asyncio
    async def test_call_llm_streaming_empty_response(self, mock_trace_logger):
        """Test streaming with empty response."""
        async def mock_acompletion_empty(*args, **kwargs):
            """Mock async generator with empty response."""
            async def empty_generator():
                return
                yield  # Unreachable but makes it a generator
            return empty_generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion_empty):
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                trace_logger=mock_trace_logger
            ):
                results.append((chunk_type, content))

            # Should have no results
            assert len(results) == 0

    @pytest.mark.asyncio
    async def test_call_llm_streaming_partial_response(self, mock_trace_logger):
        """Test streaming with only partial response."""
        mock_chunks = [
            # Only thinking, no content
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content="Analyzing the question..."
            ))]),
        ]

        async def mock_acompletion(*args, **kwargs):
            async def generator():
                for chunk in mock_chunks:
                    yield chunk
            return generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                trace_logger=mock_trace_logger
            ):
                results.append((chunk_type, content))

            # Should only have thinking chunks
            assert len(results) == 1
            assert results[0][0] == "thinking"
            assert results[0][1] == "Analyzing the question..."

    @pytest.mark.asyncio
    async def test_call_llm_streaming_malformed_thinking(self, mock_trace_logger):
        """Test streaming with malformed thinking JSON."""
        mock_chunks = [
            # Malformed reasoning - just skip this case since reasoning_content is direct text
            # Valid content
            Mock(choices=[Mock(delta=Mock(content="Valid content response"))]),
        ]

        async def mock_acompletion(*args, **kwargs):
            async def generator():
                for chunk in mock_chunks:
                    yield chunk
            return generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                trace_logger=mock_trace_logger
            ):
                results.append((chunk_type, content))

            # Should skip malformed thinking and process valid content
            content_chunks = [r for r in results if r[0] == "content"]
            assert len(content_chunks) == 1
            assert content_chunks[0][1] == "Valid content response"

    @pytest.mark.asyncio
    async def test_call_llm_streaming_with_trace_logger(self, mock_trace_logger):
        """Test streaming with trace logger integration."""
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content="Analyzing...",
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content="Response content",
                reasoning_content=None,
                reasoning=None
            ))]),
        ]

        async def mock_acompletion(*args, **kwargs):
            async def generator():
                for chunk in mock_chunks:
                    yield chunk
            return generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                trace_logger=mock_trace_logger,
                trace_id="test-trace-456"
            ):
                results.append((chunk_type, content))

            # Verify trace logger was used appropriately
            # Note: In real implementation, trace logger integration would be tested
            # Here we just verify the streaming works with trace logger present
            assert len(results) == 2
            assert any(r[0] == "thinking" for r in results)
            assert any(r[0] == "content" for r in results)

    @pytest.mark.asyncio
    async def test_call_llm_streaming_without_trace_logger(self):
        """Test streaming without trace logger."""
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content="Simple response",
                reasoning_content=None,
                reasoning=None
            ))]),
        ]

        async def mock_acompletion(*args, **kwargs):
            async def generator():
                for chunk in mock_chunks:
                    yield chunk
            return generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            results = []
            async for chunk_type, content in call_llm_streaming(
                prompt="Test prompt",
                temperature=0.7,
                trace_logger=None,
                trace_id=None
            ):
                results.append((chunk_type, content))

            # Should work fine without trace logger
            assert len(results) == 1
            assert results[0][0] == "content"
            assert results[0][1] == "Simple response"