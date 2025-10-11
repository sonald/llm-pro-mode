"""Shared helpers for token counting."""

from __future__ import annotations

from typing import Optional

from litellm import token_counter


def count_tokens(text: str, *, model_name: Optional[str]) -> int:
    """Count tokens with graceful fallbacks across the codebase."""
    if not text:
        return 0

    model = model_name or "gpt-3.5-turbo"
    try:
        return int(token_counter(model=model, text=text))
    except Exception:
        return max(1, len(text) // 4)

