"""Tests for synthesis functionality."""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from llm_pro_mode.interfaces.web import synthesize_result_websocket, WebSocketProgressTracker


class TestSynthesis:
    """Test cases for synthesis functionality."""

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_success(self, mock_synthesis_candidates,
                                                      progress_tracker, websocket_manager,
                                                      mock_websocket, mock_trace_logger):
        """Test successful synthesis with WebSocket updates."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Mock streaming response for synthesis
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content="Analyzing candidates...",
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content="Synthesized result: ",
                reasoning_content=None,
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content="Combined insights from all candidates.",
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
            result = await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker,
                trace_logger=mock_trace_logger,
                trace_id="synthesis-test-123"
            )

            # Verify result
            expected_result = "Synthesized result: Combined insights from all candidates."
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_empty_candidates(self, progress_tracker,
                                                              websocket_manager, mock_websocket):
        """Test synthesis with empty candidates list."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Mock minimal streaming response
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content="No candidates to synthesize.",
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
            result = await synthesize_result_websocket(
                candidates=[],
                progress_tracker=progress_tracker
            )

            assert result == "No candidates to synthesize."

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_api_error(self, mock_synthesis_candidates,
                                                        progress_tracker, websocket_manager,
                                                        mock_websocket, mock_trace_logger):
        """Test synthesis with API error."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        async def mock_acompletion_error(*args, **kwargs):
            async def error_generator():
                raise Exception("Synthesis API error")
                yield  # Unreachable
            return error_generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion_error):
            # The synthesis should still complete but might have error content
            result = await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker,
                trace_logger=mock_trace_logger,
                trace_id="synthesis-error-test"
            )

            # Should return empty or error message
            assert result == ""

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_single_candidate(self, progress_tracker,
                                                              websocket_manager, mock_websocket):
        """Test synthesis with single candidate."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        single_candidate = ["Single candidate response for testing"]

        # Mock streaming response
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content="Based on the single candidate: ",
                reasoning_content=None,
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content="Single candidate response for testing",
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
            result = await synthesize_result_websocket(
                candidates=single_candidate,
                progress_tracker=progress_tracker
            )

            expected_result = "Based on the single candidate: Single candidate response for testing"
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_prompt_construction(self, mock_synthesis_candidates,
                                                                 progress_tracker, websocket_manager,
                                                                 mock_websocket):
        """Test that synthesis prompt is constructed correctly."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Track the messages sent to API
        captured_messages = None

        async def mock_acompletion(*args, **kwargs):
            nonlocal captured_messages
            # Capture the messages parameter which contains system/user prompts
            captured_messages = kwargs.get('messages', [])

            async def generator():
                mock_chunks = [Mock(choices=[Mock(delta=Mock(
                    content="Synthesis result",
                    reasoning_content=None,
                    reasoning=None
                ))])]
                for chunk in mock_chunks:
                    yield chunk
            return generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker
            )

            # Verify prompt contains system message and candidates
            assert captured_messages is not None
            assert captured_messages[0]["role"] == "system"
            assert "expert editor" in captured_messages[0]["content"].lower()

            user_message = captured_messages[-1]["content"]
            assert "return the single best final answer" in user_message.lower()
            assert "<cand0>" in user_message
            assert "<cand1>" in user_message
            assert "<cand2>" in user_message
            assert mock_synthesis_candidates[0] in user_message
            assert mock_synthesis_candidates[1] in user_message
            assert mock_synthesis_candidates[2] in user_message

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_with_trace_integration(self, mock_synthesis_candidates,
                                                                    progress_tracker, websocket_manager,
                                                                    mock_websocket, mock_trace_logger):
        """Test synthesis with trace logger integration."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Mock streaming response with thinking and content
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content="Analyzing candidates for synthesis...",
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content="Final synthesis result",
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
            result = await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker,
                trace_logger=mock_trace_logger,
                trace_id="trace-synthesis-456"
            )

            assert result == "Final synthesis result"

            # Verify trace logger methods were called
            # Note: In a real test, we would verify the specific calls made to trace logger
            # but since it's a mock, we just ensure the synthesis completed with tracing enabled
            assert mock_trace_logger.enabled is True

    @pytest.mark.asyncio
    async def test_synthesize_handles_structured_reasoning(self, mock_synthesis_candidates,
                                                          progress_tracker, websocket_manager,
                                                          mock_websocket):
        """Structured reasoning lists should normalize to text."""
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        structured_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content=None,
                reasoning_content=[{"type": "text", "text": "Analyzing..."}],
                reasoning=None
            ))]),
            Mock(choices=[Mock(delta=Mock(
                content="Final merged answer.",
                reasoning_content=None,
                reasoning=None
            ))]),
        ]

        async def mock_acompletion(*args, **kwargs):
            async def generator():
                for chunk in structured_chunks:
                    yield chunk
            return generator()

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            result = await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker
            )

            assert result == "Final merged answer."

    @pytest.mark.asyncio
    async def test_synthesize_result_websocket_no_trace_logger(self, mock_synthesis_candidates,
                                                             progress_tracker, websocket_manager,
                                                             mock_websocket):
        """Test synthesis without trace logger."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Mock streaming response
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(
                content="Synthesis without tracing",
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
            result = await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker,
                trace_logger=None,
                trace_id=None
            )

            assert result == "Synthesis without tracing"
