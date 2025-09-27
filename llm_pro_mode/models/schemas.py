"""Pydantic models and data schemas."""

from typing import Optional, Dict, Any, Union, List
from pydantic import BaseModel


class Request(BaseModel):
    """Request model for API endpoints."""

    prompt: str
    n_runs: int = 3
    enable_trace: bool = False
    trace_compact: bool = False


class CompletionRequest(BaseModel):
    """Request model for completion processing."""

    prompt: str
    n_runs: int = 3
    enable_trace: bool = False
    trace_compact: bool = True


class TaskUpdate(BaseModel):
    """Task progress update model."""

    task_id: str
    title: Optional[str] = None
    status: str  # 'running', 'completed', 'failed'
    progress: float = 0.0
    thinking: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WebSocketMessage(BaseModel):
    """WebSocket message model."""

    type: str
    data: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[float] = None
    thinking: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    success: Optional[bool] = None
    stats: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class TaskStartedMessage(WebSocketMessage):
    """Task started message."""
    type: str = "task_started"
    task_id: str
    title: str
    metadata: Optional[Dict[str, Any]] = None


class TaskProgressMessage(WebSocketMessage):
    """Task progress update message."""
    type: str = "task_progress"
    task_id: str
    progress: float
    thinking: Optional[str] = None
    content: Optional[str] = None


class TaskCompletedMessage(WebSocketMessage):
    """Task completed message."""
    type: str = "task_completed"
    task_id: str
    success: bool
    error: Optional[str] = None
    thinking: Optional[str] = None
    content: Optional[str] = None


class SynthesisStartedMessage(WebSocketMessage):
    """Synthesis started message."""
    type: str = "synthesis_started"


class SynthesisCompletedMessage(WebSocketMessage):
    """Synthesis completed message."""
    type: str = "synthesis_completed"
    success: bool
    error: Optional[str] = None


class FinalResultMessage(WebSocketMessage):
    """Final result message."""
    type: str = "final_result"
    content: str
    stats: Optional[Dict[str, Any]] = None


class ProfileSummary(BaseModel):
    """Profile metadata for UI consumption."""

    name: str
    description: Optional[str] = None
    model_name: str
    api_base: str
    api_key_preview: Optional[str] = None


class ProfileListResponse(BaseModel):
    """Response payload for available profiles."""

    profiles: List[ProfileSummary]
    active_profile: Optional[str]
    default_profile: Optional[str]


class ProfileSelectRequest(BaseModel):
    """Request body for selecting a profile."""

    name: str
    make_default: bool = False


class ErrorMessage(WebSocketMessage):
    """Error message."""
    type: str = "error"
    message: str


class ConnectionStatusMessage(WebSocketMessage):
    """Connection status message."""
    type: str = "connection_status"
    status: str  # 'connected', 'disconnected', 'error'
    message: Optional[str] = None
