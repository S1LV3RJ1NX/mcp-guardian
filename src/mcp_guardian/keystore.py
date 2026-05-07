"""Pluggable key-value store for API keys.

The default InMemoryKeyStore is suitable for single-process
deployments. For shared or persistent storage, subclass KeyStore
and pass the instance to UpstreamManager (e.g. Redis, database,
encrypted file).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class KeyStore(ABC):
    """Abstract async key-value store for API keys.

    Implementations must be safe to call from async code.
    Keys are indexed by upstream server name.
    """

    @abstractmethod
    async def get(self, server_name: str) -> str | None:
        """Return the stored key, or None if not set."""

    @abstractmethod
    async def set(self, server_name: str, key: str) -> None:
        """Store a key for a server (overwrites any existing value)."""

    @abstractmethod
    async def delete(self, server_name: str) -> bool:
        """Remove a stored key. Returns True if a key was removed."""

    @abstractmethod
    async def has(self, server_name: str) -> bool:
        """Check whether a key exists for the given server."""


class InMemoryKeyStore(KeyStore):
    """Simple dict-backed store. Keys are lost on process restart."""

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    async def get(self, server_name: str) -> str | None:
        return self._keys.get(server_name)

    async def set(self, server_name: str, key: str) -> None:
        self._keys[server_name] = key

    async def delete(self, server_name: str) -> bool:
        return self._keys.pop(server_name, None) is not None

    async def has(self, server_name: str) -> bool:
        return server_name in self._keys
