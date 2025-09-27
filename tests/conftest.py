"""Test configuration and fixtures for LLM Pro Mode tests."""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock
from pathlib import Path
from typing import AsyncGenerator, Tuple

import anyio
from fastapi.testclient import TestClient
from fastapi import WebSocket

from llm_pro_mode.interfaces.web import WebSocketManager, WebSocketProgressTracker
from llm_pro_mode.tracing.logger import TraceLogger


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def websocket_manager():
    """Create a WebSocketManager instance for testing."""
    return WebSocketManager()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket for testing."""
    websocket = Mock(spec=WebSocket)
    websocket.accept = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.receive_text = AsyncMock()
    return websocket


@pytest.fixture
def progress_tracker(websocket_manager, mock_websocket):
    """Create a WebSocketProgressTracker instance for testing."""
    connection_id = "test-connection-123"
    session_id = "test-session-456"
    return WebSocketProgressTracker(websocket_manager, connection_id, session_id)


@pytest.fixture
def mock_trace_logger():
    """Create a mock TraceLogger for testing."""
    logger = Mock(spec=TraceLogger)
    logger.enabled = True
    logger.traces = []
    logger.start_task = Mock(return_value="mock-trace-id")
    logger.log_thinking = Mock()
    logger.log_content = Mock()
    logger.finish_task = Mock()
    logger.get_stats = Mock(return_value={
        "total_tokens": 1500,
        "total_time": 2.3,
        "success_rate": 100.0
    })
    return logger


@pytest.fixture
def mock_llm_streaming_response():
    """Create a mock streaming LLM response for testing."""
    async def mock_stream():
        # Simulate thinking phase
        yield ("thinking", "Let me analyze this question...")
        yield ("thinking", " I need to consider multiple aspects...")
        yield ("thinking", " Based on the context...")

        # Simulate content generation
        yield ("content", "This is the beginning of the response")
        yield ("content", " and here is more content")
        yield ("content", " with the final conclusion.")

    return mock_stream


@pytest.fixture
def mock_synthesis_candidates():
    """Create mock synthesis candidates for testing."""
    return [
        "First candidate response with detailed analysis of the topic.",
        "Second candidate response approaching from a different angle.",
        "Third candidate response with comprehensive coverage."
    ]


@pytest.fixture
def sample_websocket_messages():
    """Sample WebSocket messages for testing."""
    return {
        "completion_request": {
            "type": "completion_request",
            "data": {
                "prompt": "Test prompt",
                "n_runs": 2,
                "enable_trace": True,
                "trace_compact": False
            }
        },
        "task_started": {
            "type": "task_started",
            "task_id": "run_1",
            "title": "Run 1",
            "metadata": {}
        },
        "task_progress": {
            "type": "task_progress",
            "task_id": "run_1",
            "progress": 50,
            "thinking": "Analyzing the question...",
            "content": ""
        },
        "task_completed": {
            "type": "task_completed",
            "task_id": "run_1",
            "success": True,
            "error": None,
            "thinking": "",
            "content": "Final response content"
        },
        "synthesis_started": {
            "type": "synthesis_started"
        },
        "synthesis_completed": {
            "type": "synthesis_completed",
            "success": True,
            "error": None
        },
        "final_result": {
            "type": "final_result",
            "content": "Synthesized final result",
            "stats": {
                "total_tokens": 1500,
                "total_time": 2.3,
                "success_rate": 100.0
            }
        }
    }


@pytest.fixture
def mock_memory_stream():
    """Create a mock anyio memory stream for testing."""
    async def create_mock_stream():
        (tx, rx) = anyio.create_memory_object_stream(3)
        return tx, rx

    return create_mock_stream


@pytest.fixture
def temp_trace_dir(tmp_path):
    """Create a temporary directory for trace files."""
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    return trace_dir


# Async test utilities
def async_test(func):
    """Decorator to run async test functions."""
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper


# Mock patches for external dependencies
@pytest.fixture
def mock_litellm_completion():
    """Mock litellm completion calls."""
    async def mock_completion(*args, **kwargs):
        return Mock(
            choices=[Mock(
                delta=Mock(content="Mocked response content"),
                message=Mock(content="Complete mocked response")
            )]
        )
    return mock_completion