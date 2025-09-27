"""Tests for WebSocketProgressTracker functionality."""

import pytest
import json
from unittest.mock import Mock, AsyncMock

from llm_pro_mode.interfaces.web import WebSocketManager, WebSocketProgressTracker


class TestWebSocketProgressTracker:
    """Test cases for WebSocketProgressTracker class."""

    @pytest.mark.asyncio
    async def test_start_task(self, progress_tracker, websocket_manager, mock_websocket):
        """Test starting a new task."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        task_id = "test-task-1"
        title = "Test Task"
        metadata = {"type": "llm_call", "temperature": 0.7}

        await progress_tracker.start_task(task_id, title, metadata)

        # Verify task is stored in tracker
        assert task_id in progress_tracker.tasks
        task_data = progress_tracker.tasks[task_id]

        assert task_data["id"] == task_id
        assert task_data["title"] == title
        assert task_data["status"] == "running"
        assert task_data["progress"] == 0
        assert task_data["thinking"] == ""
        assert task_data["content"] == ""
        assert task_data["metadata"] == metadata

        # Verify WebSocket message was sent
        expected_message = {
            "type": "task_started",
            "task_id": task_id,
            "title": title,
            "metadata": metadata
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_update_task_progress(self, progress_tracker, websocket_manager, mock_websocket):
        """Test updating task progress."""
        # Setup connection and task
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        task_id = "test-task-1"
        await progress_tracker.start_task(task_id, "Test Task")
        mock_websocket.send_text.reset_mock()  # Clear previous calls

        # Update progress
        progress = 50.0
        thinking = "Analyzing the question..."
        content = "This is partial content"

        await progress_tracker.update_task_progress(task_id, progress, thinking, content)

        # Verify task data is updated
        task_data = progress_tracker.tasks[task_id]
        assert task_data["progress"] == progress
        assert task_data["thinking"] == thinking
        assert task_data["content"] == content

        # Verify WebSocket message was sent
        expected_message = {
            "type": "task_progress",
            "task_id": task_id,
            "progress": progress,
            "thinking": thinking,
            "content": content
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_update_task_progress_accumulative(self, progress_tracker, websocket_manager, mock_websocket):
        """Test that thinking and content accumulate on updates."""
        # Setup connection and task
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        task_id = "test-task-1"
        await progress_tracker.start_task(task_id, "Test Task")
        mock_websocket.send_text.reset_mock()

        # First update
        await progress_tracker.update_task_progress(task_id, 25.0, "First thinking...", "First content")

        # Second update
        await progress_tracker.update_task_progress(task_id, 50.0, " Second thinking...", " Second content")

        # Verify content accumulates
        task_data = progress_tracker.tasks[task_id]
        assert task_data["thinking"] == "First thinking... Second thinking..."
        assert task_data["content"] == "First content Second content"
        assert task_data["progress"] == 50.0

    @pytest.mark.asyncio
    async def test_update_task_progress_structured_payload(self, progress_tracker, websocket_manager, mock_websocket):
        """Structured reasoning payloads should normalize to plain text."""
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        task_id = "structured-task"
        await progress_tracker.start_task(task_id, "Structured Task")
        mock_websocket.send_text.reset_mock()

        reasoning_chunk = [{"type": "text", "text": "Chain"}, {"type": "text", "text": " of thought"}]
        content_chunk = {"text": "Answer"}

        await progress_tracker.update_task_progress(
            task_id,
            75.0,
            thinking=reasoning_chunk,
            content=content_chunk,
        )

        task_data = progress_tracker.tasks[task_id]
        assert task_data["thinking"] == "Chain of thought"
        assert task_data["content"] == "Answer"

        sent_message = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_message["thinking"] == "Chain of thought"
        assert sent_message["content"] == "Answer"

    @pytest.mark.asyncio
    async def test_update_nonexistent_task(self, progress_tracker, websocket_manager, mock_websocket):
        """Test updating a task that doesn't exist."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Try to update non-existent task
        await progress_tracker.update_task_progress("nonexistent-task", 50.0)

        # Should not send any WebSocket messages
        mock_websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_task_success(self, progress_tracker, websocket_manager, mock_websocket):
        """Test completing a task successfully."""
        # Setup connection and task
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        task_id = "test-task-1"
        await progress_tracker.start_task(task_id, "Test Task")
        mock_websocket.send_text.reset_mock()

        # Complete task
        thinking = "Final thinking"
        content = "Final content"

        await progress_tracker.complete_task(task_id, success=True, thinking=thinking, content=content)

        # Verify task data
        task_data = progress_tracker.tasks[task_id]
        assert task_data["status"] == "completed"
        assert task_data["progress"] == 100
        assert task_data["thinking"] == thinking
        assert task_data["content"] == content

        # Verify WebSocket message
        expected_message = {
            "type": "task_completed",
            "task_id": task_id,
            "success": True,
            "error": None,
            "thinking": thinking,
            "content": content
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_complete_task_failure(self, progress_tracker, websocket_manager, mock_websocket):
        """Test completing a task with failure."""
        # Setup connection and task
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        task_id = "test-task-1"
        await progress_tracker.start_task(task_id, "Test Task")
        mock_websocket.send_text.reset_mock()

        # Complete task with error
        error_msg = "API timeout error"

        await progress_tracker.complete_task(task_id, success=False, error=error_msg)

        # Verify task data
        task_data = progress_tracker.tasks[task_id]
        assert task_data["status"] == "failed"
        assert task_data["progress"] == 100
        assert task_data["error"] == error_msg

        # Verify WebSocket message
        expected_message = {
            "type": "task_completed",
            "task_id": task_id,
            "success": False,
            "error": error_msg,
            "thinking": "",
            "content": ""
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_start_synthesis(self, progress_tracker, websocket_manager, mock_websocket):
        """Test starting synthesis phase."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        await progress_tracker.start_synthesis()

        # Verify WebSocket messages (task card + synthesis started)
        assert mock_websocket.send_text.call_count == 2
        task_started_call, synthesis_started_call = [
            json.loads(call.args[0]) for call in mock_websocket.send_text.call_args_list
        ]

        assert task_started_call == {
            "type": "task_started",
            "task_id": "synthesis",
            "title": "Synthesis",
            "metadata": {"type": "synthesis"},
        }
        assert synthesis_started_call == {"type": "synthesis_started"}

    @pytest.mark.asyncio
    async def test_complete_synthesis_success(self, progress_tracker, websocket_manager, mock_websocket):
        """Test completing synthesis successfully."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        await progress_tracker.start_synthesis()
        mock_websocket.send_text.reset_mock()

        final_thinking = "Consolidated reasoning"
        final_content = "Final synthesized answer"

        await progress_tracker.complete_synthesis(
            success=True,
            thinking=final_thinking,
            content=final_content,
        )

        # Verify WebSocket message
        expected_message = {
            "type": "synthesis_completed",
            "success": True,
            "error": None,
            "thinking": final_thinking,
            "content": final_content,
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_complete_synthesis_failure(self, progress_tracker, websocket_manager, mock_websocket):
        """Test completing synthesis with failure."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        error_msg = "Synthesis failed due to invalid candidates"
        await progress_tracker.start_synthesis()
        mock_websocket.send_text.reset_mock()

        partial_thinking = "Partial reasoning"
        partial_content = "Incomplete answer"

        await progress_tracker.complete_synthesis(
            success=False,
            error=error_msg,
            thinking=partial_thinking,
            content=partial_content,
        )

        # Verify WebSocket message
        expected_message = {
            "type": "synthesis_completed",
            "success": False,
            "error": error_msg,
            "thinking": partial_thinking,
            "content": partial_content,
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_send_final_result(self, progress_tracker, websocket_manager, mock_websocket):
        """Test sending final result."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        content = "Final synthesized result"
        stats = {
            "total_tokens": 1500,
            "total_time": 2.3,
            "success_rate": 100.0
        }

        await progress_tracker.send_final_result(content, stats)

        # Verify WebSocket message
        expected_message = {
            "type": "final_result",
            "content": content,
            "stats": stats
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))

    @pytest.mark.asyncio
    async def test_send_error(self, progress_tracker, websocket_manager, mock_websocket):
        """Test sending error message."""
        # Setup connection
        connection_id = progress_tracker.connection_id
        websocket_manager.active_connections[connection_id] = mock_websocket

        error_msg = "Critical processing error"

        await progress_tracker.send_error(error_msg)

        # Verify WebSocket message
        expected_message = {
            "type": "error",
            "message": error_msg
        }
        mock_websocket.send_text.assert_called_once_with(json.dumps(expected_message))
