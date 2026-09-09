"""API exceptions."""

from __future__ import annotations


class ProxmoxError(Exception):
    """Base."""


class AuthError(ProxmoxError):
    pass


class ConnectionError(ProxmoxError):
    pass


class NotFoundError(ProxmoxError):
    pass


class ActionFailedError(ProxmoxError):
    pass
