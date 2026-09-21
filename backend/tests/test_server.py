from __future__ import annotations

import asyncio
import json
import socket
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from websockets.asyncio.client import connect  # noqa: E402

from rebotd.drivers.fake_rs import FakeRSDriver  # noqa: E402
from rebotd.server import RebotdServer  # noqa: E402
from rebotd.service import RobotService  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_and_telemetry_over_websocket(self) -> None:
        driver = FakeRSDriver()
        driver.connect()
        service = RobotService(driver, product_id="b601-rs", driver_name="fake_rs")
        port = free_port()
        server = RebotdServer(service, port=port, telemetry_rate=30)
        server_task = asyncio.create_task(server.run())
        try:
            for _ in range(30):
                try:
                    websocket = await connect(f"ws://127.0.0.1:{port}")
                    break
                except OSError:
                    await asyncio.sleep(0.01)
            else:
                self.fail("server did not start")

            async with websocket:
                await websocket.send(json.dumps({"id": 1, "method": "system.hello"}))
                response = None
                telemetry = None
                for _ in range(10):
                    message = json.loads(await asyncio.wait_for(websocket.recv(), 1.0))
                    if message.get("id") == 1:
                        response = message
                    if message.get("event") == "telemetry":
                        telemetry = message
                    if response and telemetry:
                        break
                self.assertTrue(response["ok"])
                self.assertEqual(response["result"]["productId"], "b601-rs")
                self.assertEqual(len(telemetry["data"]["position"]), 6)
        finally:
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
