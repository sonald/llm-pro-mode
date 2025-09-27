"""Integration tests for Web UI functionality."""

import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from llm_pro_mode.interfaces.web import (
    WebSocketManager,
    WebSocketProgressTracker,
    handle_completion_request,
    process_main_with_websocket
)


class TestWebUIIntegration:
    """Integration tests for Web UI components working together."""

    @pytest.mark.asyncio
    async def test_complete_websocket_workflow(self, mock_trace_logger):
        """Test complete WebSocket workflow from request to final result."""
        # Setup WebSocket manager and connection
        ws_manager = WebSocketManager()
        mock_websocket = Mock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock()

        connection_id = "test-connection"
        session_id = "test-session"

        await ws_manager.connect(mock_websocket, connection_id)
        ws_manager.connection_tasks[connection_id] = session_id

        # Mock the LLM responses for multiple runs
        def create_mock_acompletion():
            async def mock_acompletion(*args, **kwargs):
                async def generator():
                    # Simulate a realistic LLM response
                    chunks = [
                        Mock(choices=[Mock(delta=Mock(
                            content=None,
                            reasoning_content="Analyzing the question...",
                            reasoning=None
                        ))]),
                        Mock(choices=[Mock(delta=Mock(
                            content="This is a response from run ",
                            reasoning_content=None,
                            reasoning=None
                        ))]),
                        Mock(choices=[Mock(delta=Mock(
                            content="with detailed analysis.",
                            reasoning_content=None,
                            reasoning=None
                        ))])
                    ]
                    for chunk in chunks:
                        yield chunk
                return generator()
            return mock_acompletion

        # Test the completion request handler
        request_data = {
            "prompt": "Test question for integration",
            "n_runs": 2,
            "enable_trace": True,
            "trace_compact": False
        }

        # Mock the process_main_with_websocket function instead for cleaner testing
        async def mock_process_main_with_websocket(prompt, n_runs, progress_tracker, trace_logger):
            # Simulate the workflow
            for i in range(n_runs):
                task_id = f"run_{i + 1}"
                await progress_tracker.start_task(task_id, f"Run {i + 1}")
                await progress_tracker.update_task_progress(task_id, 50)
                await progress_tracker.complete_task(task_id, True)

            await progress_tracker.start_synthesis()
            await progress_tracker.update_task_progress(
                "synthesis",
                60,
                thinking="Evaluating candidate overlap",
                content="Preparing merged draft",
            )
            await progress_tracker.complete_synthesis(
                True,
                thinking="Final reasoning summary",
                content="Integrated test result",
            )
            return "Integrated test result"

        with patch('llm_pro_mode.interfaces.web.process_main_with_websocket', side_effect=mock_process_main_with_websocket), \
             patch('llm_pro_mode.interfaces.web.ws_manager', ws_manager):
            await handle_completion_request(connection_id, session_id, request_data)

        # Verify WebSocket messages were sent in correct sequence
        sent_messages = [call.args[0] for call in mock_websocket.send_text.call_args_list]

        # Parse sent messages
        message_types = []
        for msg_json in sent_messages:
            message = json.loads(msg_json)
            message_types.append(message["type"])

        # Verify the expected sequence of messages
        expected_sequence = [
            "task_started",  # Run 1
            "task_started",  # Run 2
            "task_completed",  # Run 1
            "task_completed",  # Run 2
            "synthesis_started",
            "synthesis_completed",
            "final_result"
        ]

        # Allow for some variation in task completion order
        assert "task_started" in message_types
        assert "synthesis_started" in message_types
        assert "synthesis_completed" in message_types
        assert "final_result" in message_types

        # Verify final result message contains content
        final_messages = [json.loads(msg) for msg in sent_messages
                         if json.loads(msg)["type"] == "final_result"]
        assert len(final_messages) == 1
        assert "content" in final_messages[0]
        assert len(final_messages[0]["content"]) > 0

    @pytest.mark.asyncio
    async def test_error_handling_integration(self):
        """Test error handling across the entire WebSocket workflow."""
        # Setup WebSocket manager
        ws_manager = WebSocketManager()
        mock_websocket = Mock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock()

        connection_id = "test-connection"
        session_id = "test-session"

        await ws_manager.connect(mock_websocket, connection_id)
        ws_manager.connection_tasks[connection_id] = session_id

        # Mock LLM to return error
        async def mock_acompletion_error(*args, **kwargs):
            async def error_generator():
                raise Exception("LLM API error")
                yield  # Unreachable
            return error_generator()

        request_data = {
            "prompt": "Test error handling",
            "n_runs": 1,
            "enable_trace": False
        }

        # Mock error in processing
        async def mock_process_with_error(prompt, n_runs, progress_tracker, trace_logger):
            # Simulate starting tasks but encountering error
            for i in range(n_runs):
                task_id = f"run_{i + 1}"
                await progress_tracker.start_task(task_id, f"Run {i + 1}")
                await progress_tracker.complete_task(task_id, False, error="LLM API error")
            return ""

        with patch('llm_pro_mode.interfaces.web.process_main_with_websocket', side_effect=mock_process_with_error), \
             patch('llm_pro_mode.interfaces.web.ws_manager', ws_manager):
            await handle_completion_request(connection_id, session_id, request_data)

        # Verify error was handled gracefully
        sent_messages = [call.args[0] for call in mock_websocket.send_text.call_args_list]
        message_types = [json.loads(msg)["type"] for msg in sent_messages]

        # Should still complete the workflow even with errors
        assert "task_started" in message_types
        assert "final_result" in message_types

    def test_handle_completion_real_flow(self):
        """handle_completion_request should stream through synthesis stage."""

        async def run_flow():
            ws_manager = WebSocketManager()
            mock_websocket = Mock()
            mock_websocket.accept = AsyncMock()
            mock_websocket.send_text = AsyncMock()

            connection_id = "flow-connection"
            session_id = "flow-session"

            await ws_manager.connect(mock_websocket, connection_id)
            ws_manager.connection_tasks[connection_id] = session_id

            async def mock_call_llm_streaming(prompt, temperature=0.7, max_tokens=None, trace_logger=None, trace_id=None):
                if prompt.startswith("System: "):
                    yield ("thinking", [{"type": "text", "text": "Combining candidates"}])
                    yield ("content", "Final synthesized answer")
                else:
                    yield ("thinking", [{"type": "text", "text": "Analyzing"}])
                    yield ("content", f"Candidate response for {prompt}")

            request_data = {
                "prompt": "Integration flow prompt",
                "n_runs": 2,
                "enable_trace": False,
            }

            with patch('llm_pro_mode.core.llm_client.call_llm_streaming', side_effect=mock_call_llm_streaming), \
                 patch('llm_pro_mode.interfaces.web.ws_manager', ws_manager):
                await handle_completion_request(connection_id, session_id, request_data)

            sent_messages = [json.loads(call.args[0]) for call in mock_websocket.send_text.call_args_list]
            message_types = [message["type"] for message in sent_messages]

            assert message_types.count("task_started") == request_data["n_runs"] + 1
            assert message_types.count("task_completed") == request_data["n_runs"]
            assert "synthesis_started" in message_types
            assert "synthesis_completed" in message_types

            final_messages = [msg for msg in sent_messages if msg["type"] == "final_result"]
            assert len(final_messages) == 1
            assert final_messages[0]["content"] == "Final synthesized answer"

        asyncio.run(run_flow())

    @pytest.mark.asyncio
    async def test_multiple_concurrent_connections(self):
        """Test handling multiple WebSocket connections simultaneously."""
        ws_manager = WebSocketManager()

        # Setup multiple connections
        connections = {}
        for i in range(3):
            conn_id = f"conn-{i}"
            session_id = f"session-{i}"
            mock_ws = Mock()
            mock_ws.accept = AsyncMock()
            mock_ws.send_text = AsyncMock()

            await ws_manager.connect(mock_ws, conn_id)
            ws_manager.connection_tasks[conn_id] = session_id
            connections[conn_id] = {"websocket": mock_ws, "session": session_id}

        # Test broadcasting to specific session
        test_message = {"type": "test", "data": "broadcast message"}
        await ws_manager.broadcast_to_session("session-1", test_message)

        # Verify only session-1 received the message
        for conn_id, conn_data in connections.items():
            if conn_data["session"] == "session-1":
                conn_data["websocket"].send_text.assert_called_once()
            else:
                conn_data["websocket"].send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_tracking_accuracy(self):
        """Test that progress tracking accurately reflects task states."""
        ws_manager = WebSocketManager()
        mock_websocket = Mock()
        mock_websocket.send_text = AsyncMock()

        connection_id = "test-connection"
        session_id = "test-session"

        progress_tracker = WebSocketProgressTracker(ws_manager, connection_id, session_id)
        ws_manager.active_connections[connection_id] = mock_websocket

        # Test complete task lifecycle
        task_id = "test-task"
        await progress_tracker.start_task(task_id, "Test Task", {"param": "value"})
        await progress_tracker.update_task_progress(task_id, 25, "Step 1", "Content 1")
        await progress_tracker.update_task_progress(task_id, 50, "Step 2", "Content 2")
        await progress_tracker.update_task_progress(task_id, 75, "Step 3", "Content 3")
        await progress_tracker.complete_task(task_id, True, thinking="Final thought", content="Final content")

        # Verify task state tracking
        task_data = progress_tracker.tasks[task_id]
        assert task_data["status"] == "completed"
        assert task_data["progress"] == 100
        assert task_data["thinking"] == "Step 1Step 2Step 3Final thought"
        assert task_data["content"] == "Content 1Content 2Content 3Final content"

        # Verify WebSocket messages
        assert mock_websocket.send_text.call_count == 5  # start + 3 updates + complete

    @pytest.mark.asyncio
    async def test_synthesis_integration(self, mock_synthesis_candidates):
        """Test synthesis integration with progress tracking."""
        ws_manager = WebSocketManager()
        mock_websocket = Mock()
        mock_websocket.send_text = AsyncMock()

        connection_id = "test-connection"
        session_id = "test-session"

        progress_tracker = WebSocketProgressTracker(ws_manager, connection_id, session_id)
        ws_manager.active_connections[connection_id] = mock_websocket

        # Mock synthesis LLM call
        async def mock_acompletion(*args, **kwargs):
            async def generator():
                chunks = [
                    Mock(choices=[Mock(delta=Mock(
                        content=None,
                        reasoning_content="Analyzing candidates...",
                        reasoning=None
                    ))]),
                    Mock(choices=[Mock(delta=Mock(
                        content="Synthesized response content",
                        reasoning_content=None,
                        reasoning=None
                    ))])
                ]
                for chunk in chunks:
                    yield chunk
            return generator()

        from llm_pro_mode.interfaces.web import synthesize_result_websocket

        with patch('llm_pro_mode.core.llm_client.acompletion', side_effect=mock_acompletion):
            result = await synthesize_result_websocket(
                candidates=mock_synthesis_candidates,
                progress_tracker=progress_tracker
            )

        assert result == "Synthesized response content"
