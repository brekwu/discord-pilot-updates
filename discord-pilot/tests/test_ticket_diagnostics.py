"""Live ticket diagnostic tests. All Discord I/O is mocked; never claims real-user E2E."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from aiohttp.test_utils import TestClient, TestServer

import app
from storage import State
from ticket_diagnostics import inspect_ticket_panel

GID = "1567347687379050727"
CHANNEL = "223456789012345678"
CATEGORY = "323456789012345678"
STAFF = "423456789012345678"
MESSAGE = "523456789012345678"
BOT_ID = 623456789012345678


class FakeRole:
    def __init__(self, ident):
        self.id = int(ident)

    def is_default(self):
        return False


class FakePanel:
    type = "text"

    def __init__(self):
        self.id = int(CHANNEL)
        self.can_read = True
        self.can_send = True
        self.message = self._message()
        self.fetch_message = AsyncMock(side_effect=self._fetch)

    @staticmethod
    def _message(*, games=("valorant", "fortnite")):
        ids = [f"pilot:ticket:open:{GID}"]
        ids.extend(f"pilot:ticket:open:{GID}:{g}" for g in games)
        return SimpleNamespace(
            author=SimpleNamespace(id=BOT_ID),
            components=[
                SimpleNamespace(children=[SimpleNamespace(custom_id=custom) for custom in ids])
            ],
        )

    async def _fetch(self, ident):
        if ident != int(MESSAGE):
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"), "deleted"
            )
        return self.message

    def permissions_for(self, member):
        return SimpleNamespace(
            view_channel=self.can_read,
            read_message_history=self.can_read,
            send_messages=self.can_send,
        )


class FakeCategory:
    type = "category"

    def __init__(self):
        self.id = int(CATEGORY)


class FakeGuild:
    def __init__(self):
        self.id = int(GID)
        self.default_role = object()
        self.me = SimpleNamespace(id=BOT_ID, guild_permissions=SimpleNamespace(
            manage_channels=True, administrator=False,
        ))
        self.panel = FakePanel()
        self.category = FakeCategory()
        self.staff = FakeRole(STAFF)
        self.roles = [self.staff]
        self.channels = [self.panel, self.category]
        self.categories = [self.category]

    def get_channel(self, ident):
        return {self.panel.id: self.panel, self.category.id: self.category}.get(ident)

    def get_role(self, ident):
        return self.staff if ident == self.staff.id else None


def configured_state(root: Path):
    state = State(root)
    state.set_module(GID, "tickets", {
        "enabled": True, "panel_channel_id": CHANNEL, "category_id": CATEGORY,
        "staff_role_id": STAFF, "recruitment_games": "valorant, fortnite",
    })
    state.state["ticket_panels"][GID] = {
        "channel_id": CHANNEL, "message_id": MESSAGE, "games": ["valorant", "fortnite"],
    }
    return state


class LiveTicketDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.state = configured_state(Path(self.folder.name))
        self.guild = FakeGuild()
        self.patch_channel = patch.object(discord, "TextChannel", FakePanel)
        self.patch_channel.start()

    async def asyncTearDown(self):
        self.patch_channel.stop()
        self.folder.cleanup()

    async def audit(self):
        return await inspect_ticket_panel(self.guild, self.state)

    async def test_live_server_ready_only_for_manual_test(self):
        result = await self.audit()
        self.assertEqual(result["status"], "ready_for_manual_test", result)
        self.assertEqual(result["games"], ["valorant", "fortnite"])
        self.assertTrue(result["requires_interaction_test"])
        self.assertTrue(all(x["ok"] for x in result["checks"]))
        self.guild.panel.fetch_message.assert_awaited_once_with(int(MESSAGE))

    async def test_missing_game_button_is_detected_without_mutations(self):
        self.guild.panel.message = FakePanel._message(games=("valorant",))
        report = await self.audit()
        self.assertEqual(report["status"], "attention")
        self.assertIn("buttons", [v["code"] for v in report["checks"] if not v["ok"]])
        self.assertEqual(self.guild.panel.fetch_message.await_count, 1)

    async def test_wrong_author_and_unconfigured_buttons_fail(self):
        self.guild.panel.message.author.id = 999999999999999999
        result = await self.audit()
        self.assertEqual(result["status"], "attention")
        self.assertIn("panel_author", [c["code"] for c in result["checks"] if not c["ok"]])
        self.guild.panel.message = FakePanel._message(
            games=("valorant", "fortnite", "clash-of-clans"))
        result = await self.audit()
        self.assertEqual(result["status"], "attention")
        self.assertIn("buttons", [c["code"] for c in result["checks"] if not c["ok"]])

    async def test_configured_staff_missing_is_reported(self):
        self.guild.get_role = lambda ident: None
        report = await self.audit()
        self.assertEqual(report["status"], "attention")
        self.assertIn("configuration", [v["code"] for v in report["checks"] if not v["ok"]])
        self.guild.panel.fetch_message.assert_not_awaited()

    async def test_missing_channel_creation_permission_fails(self):
        self.guild.me.guild_permissions.manage_channels = False
        report = await self.audit()
        self.assertEqual(report["status"], "attention")
        self.assertIn("create_channels", [v["code"] for v in report["checks"] if not v["ok"]])

    async def test_panel_cannot_be_read(self):
        self.guild.panel.can_read = False
        report = await self.audit()
        self.assertEqual(report["status"], "attention")
        self.assertIn("live_message", [v["code"] for v in report["checks"] if not v["ok"]])
        self.guild.panel.fetch_message.assert_not_awaited()

    async def test_discord_deleted_panel_and_forbidden_errors(self):
        for exc in (
            discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing"),
            discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "private"),
        ):
            with self.subTest(error=type(exc).__name__):
                self.guild.panel.fetch_message.side_effect = exc
                report = await self.audit()
                self.assertEqual(report["status"], "attention")
                self.assertIn("live_message",
                              [v["code"] for v in report["checks"] if not v["ok"]])

    async def test_offline_and_disabled_cannot_be_reported_as_ready(self):
        offline = await inspect_ticket_panel(None, self.state)
        self.assertEqual(offline["status"], "offline")
        self.state.set_module(GID, "tickets", {"enabled": False})
        report = await self.audit()
        self.assertEqual(report["status"], "attention")
        self.assertEqual(report["checks"][-1]["code"], "module")


class LiveTicketHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.previous_state, self.previous_port = app.STATE, app.PORT
        app.STATE = configured_state(Path(self.folder.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.previous_state, self.previous_port
        self.folder.cleanup()

    async def test_read_only_http_probes_do_not_mutate_discord_or_state(self):
        with patch.object(app.MANAGER, "get_guild", return_value=None):
            response = await self.client.get(
                f"/api/interactive/{GID}/tickets/diagnostic")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["status"], "offline")
            self.assertTrue(body["requires_interaction_test"])
        self.assertEqual(app.STATE.state["tickets"], {})

    async def test_online_http_diagnostic_reports_actual_game_buttons(self):
        guild = FakeGuild()
        with patch.object(app.MANAGER, "get_guild", return_value=guild), \
             patch.object(discord, "TextChannel", FakePanel):
            response = await self.client.get(
                f"/api/interactive/{GID}/tickets/diagnostic")
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["status"], "ready_for_manual_test")
            guild.panel.fetch_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
