"""Opt-in real ticket smoke tests; mocked Discord, no production claims."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from aiohttp.test_utils import TestClient, TestServer
import app
from storage import State
from ticket_live_smoke import smoke_test_ticket

GID = "1567347687379050727"
CATEGORY_ID = "323456789012345678"
STAFF_ID = "423456789012345678"
PANEL_ID = "223456789012345678"


class Staff:
    id = int(STAFF_ID)

    def is_default(self):
        return False


class Category:
    type = "category"
    id = int(CATEGORY_ID)


class Text:
    type = "text"
    id = int(PANEL_ID)


class Temporary:
    id = 723456789012345678
    name = "pilot-ticket-test-fake"

    def __init__(self, guild):
        self.guild = guild
        self.public = False
        self.message = SimpleNamespace(id=823456789012345678,
                                       content="Test technique Discord Pilot : ticket temporaire, ne pas répondre.")
        self.send = AsyncMock(return_value=self.message)
        self.fetch_message = AsyncMock(return_value=self.message)
        self.edit = AsyncMock(return_value=SimpleNamespace(name="archive-pilot-ticket-test-fake"))
        self.delete = AsyncMock()

    def permissions_for(self, target):
        if target is self.guild.default_role:
            return SimpleNamespace(view_channel=self.public, send_messages=self.public)
        return SimpleNamespace(view_channel=True, send_messages=True)


class BotMember:
    def __init__(self):
        self.guild_permissions = SimpleNamespace(manage_channels=True)


class Guild:
    id = int(GID)

    def __init__(self):
        self.default_role = object()
        self.staff = Staff()
        self.roles = [self.staff]
        self.category = Category()
        self.panel = Text()
        self.channels = [self.category, self.panel]
        self.me = BotMember()
        self.temp = Temporary(self)
        self.create_text_channel = AsyncMock(return_value=self.temp)

    def get_channel(self, ident):
        return {self.category.id: self.category, self.panel.id: self.panel}.get(ident)

    def get_role(self, ident):
        return self.staff if ident == self.staff.id else None


def state_with_tickets(root):
    state = State(root)
    state.set_module(GID, "tickets", {
        "enabled": True, "category_id": CATEGORY_ID,
        "panel_channel_id": PANEL_ID, "staff_role_id": STAFF_ID,
        "recruitment_games": "valorant, fortnite",
    })
    return state


class TicketSmokeUnitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = state_with_tickets(Path(self.tmp.name))
        self.guild = Guild()
        self.category_patch = patch.object(discord, "CategoryChannel", Category)
        self.text_patch = patch.object(discord, "TextChannel", Text)
        self.category_patch.start()
        self.text_patch.start()

    async def asyncTearDown(self):
        self.text_patch.stop()
        self.category_patch.stop()
        self.tmp.cleanup()

    async def test_success_is_technical_only_and_cleans_up(self):
        report = await smoke_test_ticket(self.guild, self.state)
        self.assertEqual(report["status"], "verified_technical_only", report)
        self.assertTrue(report["requires_user_click_test"])
        self.assertEqual(len(report["checks"]), 7)
        self.assertTrue(all(x["ok"] for x in report["checks"]))
        kwargs = self.guild.create_text_channel.await_args.kwargs
        self.assertIs(kwargs["overwrites"][self.guild.default_role].view_channel, False)
        self.assertIs(kwargs["overwrites"][self.guild.staff].view_channel, True)
        self.guild.temp.send.assert_awaited_once()
        self.guild.temp.fetch_message.assert_awaited_once()
        self.guild.temp.edit.assert_awaited_once()
        self.guild.temp.delete.assert_awaited_once()
        self.assertEqual(self.state.state["tickets"], {})

    async def test_staff_missing_blocks_without_creation(self):
        self.guild.get_role = lambda ident: None
        report = await smoke_test_ticket(self.guild, self.state)
        self.assertEqual(report["status"], "blocked")
        self.guild.create_text_channel.assert_not_awaited()

    async def test_privacy_failure_prevents_send_and_cleans_up(self):
        self.guild.temp.public = True
        result = await smoke_test_ticket(self.guild, self.state)
        self.assertEqual(result["status"], "failed")
        self.guild.temp.send.assert_not_awaited()
        self.guild.temp.delete.assert_awaited_once()

    async def test_discord_send_failure_still_deletes_temporary_room(self):
        self.guild.temp.send.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "write failed")
        report = await smoke_test_ticket(self.guild, self.state)
        self.assertEqual(report["status"], "failed")
        self.guild.temp.delete.assert_awaited_once()

    async def test_cleanup_failure_reports_exact_channel_id(self):
        self.guild.temp.delete.side_effect = OSError("no cleanup")
        report = await smoke_test_ticket(self.guild, self.state)
        self.assertEqual(report["status"], "failed")
        self.assertIn(str(self.guild.temp.id), report["checks"][-1]["detail"])


class TicketSmokeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state, self.old_port = app.STATE, app.PORT
        app.STATE = state_with_tickets(Path(self.tmp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        boot = await (await self.client.get("/api/bootstrap")).json()
        self.headers = {"X-Pilot-CSRF": boot["csrf"]}

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.old_state, self.old_port
        self.tmp.cleanup()

    async def test_live_smoke_requires_csrf_and_connected_bot(self):
        path = f"/api/interactive/{GID}/tickets/smoke"
        self.assertEqual((await self.client.post(path, json={})).status, 403)
        with patch.object(app.MANAGER, "get_guild", return_value=None):
            r = await self.client.post(path, json={}, headers=self.headers)
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["status"], "blocked")
        self.assertEqual(app.STATE.state["tickets"], {})


if __name__ == "__main__":
    unittest.main()
