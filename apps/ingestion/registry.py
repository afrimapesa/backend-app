"""Name -> adapter class registry, so Celery beat can schedule adapters by name."""

from __future__ import annotations

from .base import Adapter

_ADAPTERS: dict[str, type[Adapter]] = {}


def register[A: type[Adapter]](cls: A) -> A:
    """Class decorator: make an adapter runnable via ``run_adapter.delay(cls.source)``."""
    existing = _ADAPTERS.get(cls.source)
    if existing is not None and existing is not cls:
        raise ValueError(f"Adapter source {cls.source!r} already registered by {existing!r}")
    _ADAPTERS[cls.source] = cls
    return cls


def get_adapter(source: str) -> type[Adapter]:
    try:
        return _ADAPTERS[source]
    except KeyError:
        raise KeyError(f"No adapter registered for source {source!r}") from None


def registered_sources() -> list[str]:
    return sorted(_ADAPTERS)
