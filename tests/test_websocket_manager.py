"""Tests for WebSocket manager functionality."""

import pytest
import json
from unittest.mock import Mock, AsyncMock

from llm_pro_mode.interfaces.web import WebSocketManager


class TestWebSocketManager:
    """Test cases for WebSocketManager class."""

    @pytest.mark.asyncio
    async def test_connect_websocket(self, websocket_manager, mock_websocket):
        """Test WebSocket connection establishment."""
        connection_id = "test-connection-123"

        await websocket_manager.connect(mock_websocket, connection_id)

        # Verify websocket.accept() was called
        mock_websocket.accept.assert_called_once()

        # Verify connection is stored
        assert connection_id in websocket_manager.active_connections
        assert websocket_manager.active_connections[connection_id] == mock_websocket

    def test_disconnect_websocket(self, websocket_manager, mock_websocket):
        """Test WebSocket disconnection cleanup."""
        connection_id = "test-connection-123"
        session_id = "test-session-456"

        # Setup connection
        websocket_manager.active_connections[connection_id] = mock_websocket
        websocket_manager.connection_tasks[connection_id] = session_id

        # Disconnect
        websocket_manager.disconnect(connection_id)

        # Verify cleanup
        assert connection_id not in websocket_manager.active_connections
        assert connection_id not in websocket_manager.connection_tasks

    def test_disconnect_nonexistent_connection(self, websocket_manager):
        """Test disconnecting a non-existent connection doesn't raise errors."""
        # Should not raise any exceptions
        websocket_manager.disconnect("nonexistent-connection")

    @pytest.mark.asyncio
    async def test_send_message_success(self, websocket_manager, mock_websocket):
        """Test successful message sending."""
        connection_id = "test-connection-123"
        websocket_manager.active_connections[connection_id] = mock_websocket

        message = {"type": "test", "data": "test message"}

        await websocket_manager.send_message(connection_id, message)

        # Verify send_text was called with JSON string
        expected_json = json.dumps(message)
        mock_websocket.send_text.assert_called_once_with(expected_json)

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self, websocket_manager, mock_websocket):
        """Test message sending with connection error."""
        connection_id = "test-connection-123"
        websocket_manager.active_connections[connection_id] = mock_websocket

        # Simulate connection error
        mock_websocket.send_text.side_effect = Exception("Connection lost")

        message = {"type": "test", "data": "test message"}

        await websocket_manager.send_message(connection_id, message)

        # Verify connection was cleaned up after error
        assert connection_id not in websocket_manager.active_connections

    @pytest.mark.asyncio
    async def test_send_message_nonexistent_connection(self, websocket_manager):
        """Test sending message to non-existent connection."""
        message = {"type": "test", "data": "test message"}

        # Should not raise any exceptions
        await websocket_manager.send_message("nonexistent-connection", message)

    @pytest.mark.asyncio
    async def test_broadcast_to_session(self, websocket_manager):
        """Test broadcasting message to all connections in a session."""
        session_id = "test-session-456"

        # Setup multiple connections in the same session
        connections = {}
        for i in range(3):
            conn_id = f"conn-{i}"
            mock_ws = Mock()
            mock_ws.send_text = AsyncMock()
            connections[conn_id] = mock_ws
            websocket_manager.active_connections[conn_id] = mock_ws
            websocket_manager.connection_tasks[conn_id] = session_id

        # Add one connection in different session
        other_conn_id = "other-conn"
        other_mock_ws = Mock()
        other_mock_ws.send_text = AsyncMock()
        websocket_manager.active_connections[other_conn_id] = other_mock_ws
        websocket_manager.connection_tasks[other_conn_id] = "other-session"

        message = {"type": "broadcast", "data": "session message"}

        await websocket_manager.broadcast_to_session(session_id, message)

        # Verify message was sent to all connections in the session
        expected_json = json.dumps(message)
        for mock_ws in connections.values():
            mock_ws.send_text.assert_called_once_with(expected_json)

        # Verify message was NOT sent to other session
        other_mock_ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_to_session_with_error(self, websocket_manager):
        """Test broadcasting with connection error during broadcast."""
        session_id = "test-session-456"

        # Setup connections with one that will fail
        good_conn_id = "good-conn"
        bad_conn_id = "bad-conn"

        good_mock_ws = Mock()
        good_mock_ws.send_text = AsyncMock()

        bad_mock_ws = Mock()
        bad_mock_ws.send_text = AsyncMock(side_effect=Exception("Connection error"))

        websocket_manager.active_connections[good_conn_id] = good_mock_ws
        websocket_manager.active_connections[bad_conn_id] = bad_mock_ws
        websocket_manager.connection_tasks[good_conn_id] = session_id
        websocket_manager.connection_tasks[bad_conn_id] = session_id

        message = {"type": "broadcast", "data": "session message"}

        await websocket_manager.broadcast_to_session(session_id, message)

        # Verify good connection received message
        expected_json = json.dumps(message)
        good_mock_ws.send_text.assert_called_once_with(expected_json)

        # Verify bad connection was cleaned up
        assert bad_conn_id not in websocket_manager.active_connections
        assert bad_conn_id not in websocket_manager.connection_tasks

        # Verify good connection is still active
        assert good_conn_id in websocket_manager.active_connections