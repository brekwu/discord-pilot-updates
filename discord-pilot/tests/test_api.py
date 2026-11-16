import asyncio
import json
import os
import socket
import tempfile
import unittest
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
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
        self.assertEqual(home.headers.get("Cache-Control"), "no-store")
        self.assertIn("Discord Pilot", await home.text())
        js = await self.client.get("/assets/app.js")
        self.assertEqual(js.status, 200)
        self.assertEqual(js.headers.get("Cache-Control"), "no-store")
        boot = await self.client.get("/api/bootstrap")
        data = await boot.json()
        self.assertFalse(data["online"])
        bad = await self.client.post("/api/alias", json={"guild_id": "123456789012345678", "alias": "Client"})
        self.assertEqual(bad.status, 403)
        good = await self.client.post("/api/alias", json={"guild_id": "123456789012345678", "alias": "Client"},
                                      headers={"X-Pilot-CSRF": data["csrf"]})
        self.assertEqual(good.status, 200)

    async def test_microphone_transcription_endpoint_and_security(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        samples = b"\x00\x10" * 16000
        stream = BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(samples)
        payload = stream.getvalue()
        refused = await self.client.post("/api/transcribe", data=payload,
                                         headers={"Content-Type": "audio/wav"})
        self.assertEqual(refused.status, 403)
        headers = {"X-Pilot-CSRF": csrf, "Content-Type": "audio/wav"}
        expected = {"text": "crée un salon bienvenue", "seconds": 1.0, "segments": 1, "engine": "whisper-small"}
        with patch.object(app, "transcribe_voice_audio", return_value=expected) as speech:
            response = await self.client.post("/api/transcribe", data=payload, headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {**expected, "language": "fr-FR", "local": True})
            speech.assert_called_once_with(payload, app.STATE.root, "audio/wav")
        with patch.object(app, "transcribe_voice_audio", return_value=expected) as compressed:
            encoded = b"webm content placeholder"
            response = await self.client.post("/api/transcribe", data=encoded,
                                              headers={"X-Pilot-CSRF": csrf, "Content-Type": "audio/webm;codecs=opus"})
            self.assertEqual(response.status, 200)
            compressed.assert_called_once_with(encoded, app.STATE.root, "audio/webm")
        async def fragmented_audio():
            # Force HTTP chunked transfers: the server must wait for *all*
            # chunks, not decode the first bytes and truncate the speech.
            for offset in range(0, len(payload), 1013):
                yield payload[offset:offset + 1013]
                await asyncio.sleep(0)

        with patch.object(app, "transcribe_voice_audio", return_value=expected) as speech:
            fragmented = await self.client.post("/api/transcribe", data=fragmented_audio(), headers=headers)
            self.assertEqual(fragmented.status, 200)
            speech.assert_called_once_with(payload, app.STATE.root, "audio/wav")
        invalid_type = await self.client.post("/api/transcribe", data=payload,
                                              headers={"X-Pilot-CSRF": csrf, "Content-Type": "application/octet-stream"})
        self.assertEqual(invalid_type.status, 400)
        with patch.object(app, "load_voice_model") as download:
            with self.assertRaisesRegex(ValueError, "Enregistrement audio illisible"):
                app.transcribe_voice_audio(b"not-a-wav", app.STATE.root, "audio/wav")
            download.assert_not_called()
        class StubWhisper:
            def transcribe(self, wave_samples, **kwargs):
                self.sample_rate = len(wave_samples)
                self.options = kwargs
                return [SimpleNamespace(text=" crée un salon vocal général ")], None

        stub_model = StubWhisper()
        with patch.object(app, "load_voice_model", return_value=stub_model) as loading:
            self.assertEqual(app.transcribe_voice_audio(payload, app.STATE.root, "audio/wav"),
                             {"text": "crée un salon vocal général", "seconds": 1.0,
                              "segments": 1, "engine": "whisper-small"})
            loading.assert_called_once_with(str(app.STATE.root))
            self.assertEqual(stub_model.sample_rate, 16000)
            self.assertEqual(stub_model.options["language"], "fr")

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

    async def test_loopback_recovery_probe_has_no_session_data_or_external_cors(self):
        origin = "http://127.0.0.1:8765"
        response = await self.client.get("/api/health", headers={"Origin": origin})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        data = await response.json()
        self.assertEqual(data, {"discord_pilot": True, "version": app.read_version(app.BASE)})
        refused = await self.client.get("/api/health", headers={"Origin": "https://malicious.example"})
        self.assertEqual(refused.status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", refused.headers)
        self.assertNotIn("csrf", await refused.json())
        sensitive = await self.client.get("/api/bootstrap", headers={"Origin": "http://localhost:8765"})
        self.assertNotIn("Access-Control-Allow-Origin", sensitive.headers)

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
                        self.assertEqual(data["version"], app.read_version(app.BASE))
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
        self.assertEqual((await status.json())["version"], app.read_version(app.BASE))
        form = FormData()
        form.add_field("file", make_archive("0.5.14"), filename="discord-pilot-update.zip", content_type="application/zip")
        import_response = await self.client.post("/api/update/import", data=form, headers=header)
        self.assertEqual(import_response.status, 200)
        self.assertEqual((await import_response.json())["pending"]["version"], "0.5.14")
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

    async def test_windows_updater_starts_before_http_server_shuts_down(self):
        updates = app.STATE.root / "updates"
        updates.mkdir(parents=True, exist_ok=True)
        (updates / "pending.json").write_text(json.dumps({
            "version": "0.5.0", "sha256": "a" * 64, "format": "exe",
        }), encoding="utf-8")
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        old_stop, old_exit = app.STOP_EVENT, app.EXIT_FOR_UPDATE
        app.STOP_EVENT = asyncio.Event()
        app.EXIT_FOR_UPDATE = False
        try:
            with patch.object(app.sys, "frozen", True, create=True), \
                 patch.object(app, "launch_frozen_updater") as spawn:
                response = await self.client.post("/api/update/apply", json={},
                                                  headers={"X-Pilot-CSRF": csrf})
                self.assertEqual(response.status, 200)
                spawn.assert_called_once_with()
                self.assertTrue(app.EXIT_FOR_UPDATE)
                self.assertFalse(app.STOP_EVENT.is_set())
                await asyncio.wait_for(app.STOP_EVENT.wait(), timeout=3)
        finally:
            app.STOP_EVENT, app.EXIT_FOR_UPDATE = old_stop, old_exit

    async def test_failed_windows_updater_spawn_keeps_server_alive(self):
        updates = app.STATE.root / "updates"
        updates.mkdir(parents=True, exist_ok=True)
        (updates / "pending.json").write_text(json.dumps({
            "version": "0.5.1", "sha256": "a" * 64, "format": "exe",
        }), encoding="utf-8")
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        old_stop, old_exit = app.STOP_EVENT, app.EXIT_FOR_UPDATE
        app.STOP_EVENT = asyncio.Event()
        app.EXIT_FOR_UPDATE = False
        try:
            with patch.object(app.sys, "frozen", True, create=True), \
                 patch.object(app, "launch_frozen_updater", side_effect=OSError("PowerShell indisponible")):
                response = await self.client.post("/api/update/apply", json={},
                                                  headers={"X-Pilot-CSRF": csrf})
                self.assertNotEqual(response.status, 200)
                self.assertFalse(app.EXIT_FOR_UPDATE)
                self.assertFalse(app.STOP_EVENT.is_set())
                healthy = await self.client.get("/api/bootstrap")
                self.assertEqual(healthy.status, 200)
        finally:
            app.STOP_EVENT, app.EXIT_FOR_UPDATE = old_stop, old_exit


if __name__ == "__main__":
    unittest.main()
