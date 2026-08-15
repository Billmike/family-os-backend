import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionHub:
    def __init__(self) -> None:
        self._rooms: dict[UUID, dict[UUID, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def _run(self, coro: Coroutine[Any, Any, None], *, warning: str) -> None:
        """Schedule an async hub operation from the event loop or a sync worker thread."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
            if loop is None or loop.is_closed():
                logger.warning(warning)
                return
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            try:
                future.result(timeout=5)
            except Exception:
                logger.exception("WebSocket hub operation failed")
            return
        loop.create_task(coro)

    async def connect(self, family_id: UUID, user_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms[family_id][user_id].add(websocket)

    async def disconnect(self, family_id: UUID, user_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            users = self._rooms.get(family_id)
            if not users:
                return
            conns = users.get(user_id)
            if conns and websocket in conns:
                conns.remove(websocket)
            if conns is not None and not conns:
                users.pop(user_id, None)
            if not users:
                self._rooms.pop(family_id, None)

    def disconnect_user(self, family_id: UUID, user_id: UUID, *, code: int = 4403) -> None:
        """Close and unregister a user's sockets for a family. Sync-callable like broadcast."""
        self._run(
            self._disconnect_user(family_id, user_id, code),
            warning="No event loop for WebSocket disconnect",
        )

    async def _disconnect_user(self, family_id: UUID, user_id: UUID, code: int) -> None:
        async with self._lock:
            users = self._rooms.get(family_id)
            sockets = list(users.pop(user_id, set())) if users else []
            if users is not None and not users:
                self._rooms.pop(family_id, None)
        for ws in sockets:
            try:
                await ws.close(code=code)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to close WebSocket for user %s", user_id, exc_info=True)

    def broadcast(self, family_id: UUID, message: dict) -> None:
        """Schedule async broadcast from the event loop or a sync worker thread."""
        self._run(
            self._broadcast(family_id, message),
            warning="No event loop for WebSocket broadcast",
        )

    def send_to_user(self, family_id: UUID, user_id: UUID, message: dict) -> None:
        """Deliver a message only to one user's sockets in a family room."""
        self._run(
            self._send_to_user(family_id, user_id, message),
            warning="No event loop for WebSocket send_to_user",
        )

    async def _broadcast(self, family_id: UUID, message: dict) -> None:
        payload = json.dumps(message, default=str)
        async with self._lock:
            sockets: list[tuple[UUID, WebSocket]] = [
                (uid, ws)
                for uid, conns in self._rooms.get(family_id, {}).items()
                for ws in conns
            ]
        await self._deliver(family_id, payload, sockets)

    async def _send_to_user(self, family_id: UUID, user_id: UUID, message: dict) -> None:
        payload = json.dumps(message, default=str)
        async with self._lock:
            sockets: list[tuple[UUID, WebSocket]] = [
                (user_id, ws) for ws in self._rooms.get(family_id, {}).get(user_id, set())
            ]
        await self._deliver(family_id, payload, sockets)

    async def _deliver(
        self,
        family_id: UUID,
        payload: str,
        sockets: list[tuple[UUID, WebSocket]],
    ) -> None:
        stale: list[tuple[UUID, WebSocket]] = []
        for uid, ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                stale.append((uid, ws))
        for uid, ws in stale:
            await self.disconnect(family_id, uid, ws)


hub = ConnectionHub()
