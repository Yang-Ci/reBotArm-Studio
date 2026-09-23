from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

from .service import RobotService

LOGGER = logging.getLogger("rebotd")


@dataclass(eq=False)
class ClientSession:
    websocket: ServerConnection
    last_seen: float = field(default_factory=time.monotonic)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: set[asyncio.Task] = field(default_factory=set)

    async def send(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send(json.dumps(payload, separators=(",", ":")))


class RebotdServer:
    def __init__(
        self,
        service: RobotService,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str = "",
        telemetry_rate: float = 20.0,
        lease_timeout: float = 2.5,
    ) -> None:
        self.service = service
        self.host = host
        self.port = port
        self.token = token
        self.telemetry_rate = max(float(telemetry_rate), 1.0)
        self.lease_timeout = max(float(lease_timeout), 1.0)
        self.clients: set[ClientSession] = set()
        self._watchdog_held = False
        self._started_at = time.monotonic()

    async def run(self) -> None:
        stop_requested = asyncio.Event()
        loop = asyncio.get_running_loop()
        installed_signals: list[signal.Signals] = []
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop_requested.set)
                installed_signals.append(signum)
            except (NotImplementedError, RuntimeError):
                pass
        try:
            async with serve(
                self._handle_connection,
                self.host,
                self.port,
                max_size=1_048_576,
                ping_interval=10,
                ping_timeout=10,
            ):
                LOGGER.info("listening on ws://%s:%s", self.host, self.port)
                telemetry = asyncio.create_task(self._telemetry_loop())
                watchdog = asyncio.create_task(self._watchdog_loop())
                try:
                    await stop_requested.wait()
                finally:
                    telemetry.cancel()
                    watchdog.cancel()
                    await asyncio.gather(telemetry, watchdog, return_exceptions=True)
        finally:
            for signum in installed_signals:
                loop.remove_signal_handler(signum)

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        if self.token:
            supplied = websocket.request.headers.get("Authorization", "")
            if supplied != f"Bearer {self.token}":
                await websocket.close(code=4401, reason="unauthorized")
                return
        session = ClientSession(websocket)
        self.clients.add(session)
        self._watchdog_held = False
        LOGGER.info("client connected (%d total)", len(self.clients))
        try:
            async for raw in websocket:
                session.last_seen = time.monotonic()
                task = asyncio.create_task(self._handle_message(session, raw))
                session.tasks.add(task)
                task.add_done_callback(session.tasks.discard)
        finally:
            self.clients.discard(session)
            for task in tuple(session.tasks):
                task.cancel()
            LOGGER.info("client disconnected (%d total)", len(self.clients))

    async def _handle_message(self, session: ClientSession, raw: str | bytes) -> None:
        request_id = None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("request must be a JSON object")
            request_id = message.get("id")
            method = str(message.get("method", ""))
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params must be a JSON object")
            result = await self.service.dispatch(method, params)
            if request_id is not None:
                await session.send({"id": request_id, "ok": True, "result": result})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("request failed: %s", exc)
            if request_id is not None:
                await session.send({
                    "id": request_id,
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                })
            else:
                await session.send({
                    "event": "error",
                    "data": {"type": type(exc).__name__, "message": str(exc)},
                })

    async def _telemetry_loop(self) -> None:
        interval = 1.0 / self.telemetry_rate
        while True:
            await asyncio.sleep(interval)
            if not self.clients:
                continue
            try:
                snapshot = await self.service.snapshot(request_feedback=True)
                await self._broadcast({"event": "telemetry", "data": snapshot})
            except Exception as exc:
                LOGGER.error("telemetry failed: %s", exc)
                await self._broadcast({
                    "event": "error",
                    "data": {"type": type(exc).__name__, "message": str(exc)},
                })

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        clients = tuple(self.clients)
        results = await asyncio.gather(
            *(client.send(payload) for client in clients),
            return_exceptions=True,
        )
        for client, result in zip(clients, results):
            if isinstance(result, Exception):
                self.clients.discard(client)

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            if time.monotonic() - self._started_at < self.lease_timeout:
                continue
            live = [
                client for client in self.clients
                if time.monotonic() - client.last_seen <= self.lease_timeout
            ]
            if live or self._watchdog_held or not self.service.driver_enabled:
                continue
            self._watchdog_held = True
            LOGGER.warning("control lease expired; holding current position")
            try:
                await asyncio.to_thread(self.service.driver.hold_current_position)
            except Exception as exc:
                LOGGER.error("watchdog hold failed: %s", exc)
