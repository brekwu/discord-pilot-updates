import asyncio
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import discord
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import ClientSession, FormData, web

import app
from storage import State
from test_updater import make_archive


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_state, self.old_port = app.STATE, app.PORT
        app.STATE = State(Path(self.tempdir.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.old_state, self.old_port
        self.tempdir.cleanup()

    async def test_dashboard_and_csrf(self):
        home = await self.client.get("/")
        self.assertEqual(home.status, 200)
        self.assertIn("Discord Pilot", await home.text())
        boot = await self.client.get("/api/bootstrap")
        data = await boot.json()
        self.assertFalse(data["online"])
        bad = await self.client.post("/api/alias", json={"guild_id": "123456789012345678", "alias": "Client"})
        self.assertEqual(bad.status, 403)
        good = await self.client.post("/api/alias", json={"guild_id": "123456789012345678", "alias": "Client"},
                                      headers={"X-Pilot-CSRF": data["csrf"]})
        self.assertEqual(good.status, 200)

    async def test_discord_login_failure_is_reported_without_exposing_token(self):
        manager = app.BotManager()
        fake_bot = type("FakeBot", (), {})()
        fake_bot.start = AsyncMock(side_effect=discord.LoginFailure("Unauthorized"))
        secret = "not-a-real-token-keep-private"
        await manager._start(fake_bot, secret)
        self.assertFalse(manager.ready)
        self.assertIsNone(manager.current_token)
        self.assertIn("Discord a refusé le token", manager.error)
        self.assertNotIn(secret, manager.error)

    async def test_connect_does_not_reject_token_based_on_arbitrary_length(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        header = {"X-Pilot-CSRF": csrf}
        with patch.object(app.MANAGER, "connect", new_callable=AsyncMock) as connect:
            response = await self.client.post("/api/connect", json={"token": "  new-token  ", "remember": True}, headers=header)
            self.assertEqual(response.status, 200)
            connect.assert_awaited_once_with("new-token", True)
            missing = await self.client.post("/api/connect", json={"token": "  "}, headers=header)
            self.assertEqual(missing.status, 400)
            too_long = await self.client.post("/api/connect", json={"token": "x" * 513}, headers=header)
            self.assertEqual(too_long.status, 400)

    async def test_offline_preset_and_execution_denied(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        header = {"X-Pilot-CSRF": csrf}
        resp = await self.client.post("/api/preset", json={"guild_id": "123456789012345678", "preset_id": "support"}, headers=header)
        self.assertEqual(resp.status, 200)
        plan = (await resp.json())["plan"]
        self.assertEqual(plan["status"], "draft")
        execute = await self.client.post("/api/execute/" + plan["id"], json={}, headers=header)
        self.assertEqual(execute.status, 400)
        history = await self.client.get("/api/history/123456789012345678")
        self.assertEqual(len((await history.json())["plans"]), 1)
        self.assertEqual(app.STATE.get(plan["id"])["status"], "draft")

    async def test_local_request_is_saved_to_selected_guild(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        res = await self.client.post("/api/plan", json={
            "guild_id": "123456789012345678", "mode": "local",
            "prompt": "Crée une catégorie ACCUEIL avec les salons bienvenue et annonces",
        }, headers={"X-Pilot-CSRF": csrf})
        self.assertEqual(res.status, 200)
        plan = (await res.json())["plan"]
        self.assertEqual(plan["guild_id"], "123456789012345678")
        self.assertEqual(len(plan["actions"]), 3)
        self.assertEqual(len(app.STATE.history("234567890123456789")), 0)

    async def test_host_and_origin_protection(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        resp = await self.client.post("/api/alias", json={"guild_id": "123456789012345678", "alias": "X"},
                                      headers={"X-Pilot-CSRF": csrf, "Origin": "https://example.org"})
        self.assertEqual(resp.status, 403)

    async def test_busy_port_uses_another_port_without_disabling_security(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            preferred = occupied.getsockname()[1]
            runner = web.AppRunner(app.build_app(), access_log=None)
            await runner.setup()
            old_port = app.PORT
            try:
                _, selected = await app.start_local_site(runner, preferred)
                self.assertNotEqual(selected, preferred)
                app.PORT = selected
                async with ClientSession() as client:
                    async with client.get(f"http://127.0.0.1:{selected}/api/bootstrap") as response:
                        self.assertEqual(response.status, 200)
                        data = await response.json()
                        self.assertEqual(data["version"], "0.4.2")
                    async with client.get(f"http://127.0.0.1:{selected}/api/bootstrap",
                                          headers={"Host": "example.com"}) as response:
                        self.assertEqual(response.status, 403)
            finally:
                app.PORT = old_port
                await runner.cleanup()

    async def test_update_button_server_routes(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        header = {"X-Pilot-CSRF": csrf}
        invalid = await self.client.post("/api/update/source", json={"url": "http://127.0.0.1/admin"}, headers=header)
        self.assertEqual(invalid.status, 400)
        status = await self.client.get("/api/update/status")
        self.assertEqual((await status.json())["version"], "0.4.2")
        form = FormData()
        form.add_field("file", make_archive("0.4.3"), filename="discord-pilot-update.zip", content_type="application/zip")
        import_response = await self.client.post("/api/update/import", data=form, headers=header)
        self.assertEqual(import_response.status, 200)
        self.assertEqual((await import_response.json())["pending"]["version"], "0.4.3")
        previous_stop, previous_exit = app.STOP_EVENT, app.EXIT_FOR_UPDATE
        old_launcher = os.environ.get("DISCORD_PILOT_LAUNCHER")
        try:
            app.STOP_EVENT = asyncio.Event()
            os.environ["DISCORD_PILOT_LAUNCHER"] = "1"
            apply_response = await self.client.post("/api/update/apply", json={}, headers=header)
            self.assertEqual(apply_response.status, 200)
            await asyncio.wait_for(app.STOP_EVENT.wait(), timeout=3)
            self.assertTrue(app.EXIT_FOR_UPDATE)
        finally:
            app.STOP_EVENT, app.EXIT_FOR_UPDATE = previous_stop, previous_exit
            if old_launcher is None:
                os.environ.pop("DISCORD_PILOT_LAUNCHER", None)
            else:
                os.environ["DISCORD_PILOT_LAUNCHER"] = old_launcher


if __name__ == "__main__":
    unittest.main()
