import asyncio
import json
import logging
from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionHub:
    def __init__(self) -> None:
        self._rooms: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    async def connect(self, family_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms[family_id].add(websocket)

    async def disconnect(self, family_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._rooms.get(family_id)
            if conns and websocket in conns:
                conns.remove(websocket)
            if conns is not None and not conns:
                self._rooms.pop(family_id, None)

    def broadcast(self, family_id: UUID, message: dict) -> None:
        """Schedule async broadcast from the event loop or a sync worker thread."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
            if loop is None or loop.is_closed():
                logger.warning("No event loop for WebSocket broadcast")
                return
            future = asyncio.run_coroutine_threadsafe(self._broadcast(family_id, message), loop)
            try:
                future.result(timeout=5)
            except Exception:
                logger.exception("WebSocket broadcast failed")
            return
        loop.create_task(self._broadcast(family_id, message))

    async def _broadcast(self, family_id: UUID, message: dict) -> None:
        payload = json.dumps(message, default=str)
        async with self._lock:
            sockets = list(self._rooms.get(family_id, set()))
        stale: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                stale.append(ws)
        for ws in stale:
            await self.disconnect(family_id, ws)


hub = ConnectionHub()
