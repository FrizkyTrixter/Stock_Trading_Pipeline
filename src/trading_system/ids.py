"""Identifier helpers."""

from uuid import uuid4


def new_id(prefix: str) -> str:
    """Return a sortable-enough opaque identifier with a domain prefix."""
    return f"{prefix}_{uuid4().hex}"
