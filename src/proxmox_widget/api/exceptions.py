"""API exceptions."""

from __future__ import annotations


class ProxmoxError(Exception):
    """Base with typed status."""

    def __init__(
        self,
        status: int | str | None = None,
        message: str | None = None,
        *args: object,
    ) -> None:
        if isinstance(status, str) and message is None and not args:
            message = status
            status_int: int | None = None
        else:
            status_int = status if isinstance(status, int) else None
            if message is None and args:
                message = ""
            if message is None and isinstance(status, str):
                message = status
                status_int = None
        if args and message is not None:
            pass
        msg = message if message is not None else ""
        super().__init__(msg)
        self.status: int | None = status_int
        self.message: str = msg
        self.msg: str = msg


class AuthError(ProxmoxError):
    pass


class ConnectionError(ProxmoxError):
    pass


class NotFoundError(ProxmoxError):
    pass


class ActionFailedError(ProxmoxError):
    pass
