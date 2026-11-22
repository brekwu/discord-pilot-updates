"""Live Vexora audit: no Discord writes, no unverified production claims."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
import app
from planner import PRESETS
from storage import State
from vexora_esport_audit import audit_vexora_esport

GID = "1567347687379050727"


def sample_guild():
    actions = PRESETS["vexora-esport"]["actions"]
    categories = {}
    channels = []
    roles = []
    next_id = 100000000000000001
    for item in actions:
        if item["type"] == "create_category":
            category = SimpleNamespace(id=next_id, name=item["name"], type="category",
                                       category_id=None)
            categories[item["name"]] = category
            channels.append(category)
            next_id += 1
    for item in actions:
        if item["type"] == "create_text_channel":
            channels.append(SimpleNamespace(
                id=next_id, name=item["name"], type="text",
                category_id=categories[item["category"]].id,
            ))
            next_id += 1
        if item["type"] == "create_role":
            roles.append(SimpleNamespace(id=next_id, name=item["name"]))
            next_id += 1
    return SimpleNamespace(
        id=int(GID),
        fetch_channels=AsyncMock(return_value=channels),
        fetch_roles=AsyncMock(return_value=roles),
        create_role=AsyncMock(side_effect=AssertionError("Forbidden write")),
        create_category=AsyncMock(side_effect=AssertionError("Forbidden write")),
        create_text_channel=AsyncMock(side_effect=AssertionError("Forbidden write")),
        channels=channels,
        roles=roles,
    )


class LiveAuditUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_live_readback_verifies_exactly_56_resources(self):
        guild = sample_guild()
        result = await audit_vexora_esport(guild)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual((result["expected"], result["passed"], result["missing"]), (56, 56, 0))
        self.assertEqual(len(result["checks"]), 56)
        guild.fetch_channels.assert_awaited_once()
        guild.fetch_roles.assert_awaited_once()
        guild.create_role.assert_not_awaited()
        guild.create_category.assert_not_awaited()
        guild.create_text_channel.assert_not_awaited()

    async def test_missing_role_and_misplaced_channel_are_detected(self):
        guild = sample_guild()
        guild.roles[:] = [r for r in guild.roles if r.name != "Manager Rocket League"]
        next(c for c in guild.channels if c.name == "resultats-valorant").category_id = 999
        report = await audit_vexora_esport(guild)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["passed"], 54)
        self.assertEqual(report["missing"], 2)
        missing = [c["name"] for c in report["checks"] if not c["ok"]]
        self.assertEqual(set(missing), {"Manager Rocket League", "resultats-valorant"})
        guild.create_text_channel.assert_not_awaited()

    async def test_duplicate_and_missing_category_fail_closed(self):
        guild = sample_guild()
        guild.channels.append(SimpleNamespace(
            id=999999999999999991, name="FORTNITE", type="category", category_id=None))
        report = await audit_vexora_esport(guild)
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("FORTNITE", {c["name"] for c in report["checks"] if not c["ok"]})
        self.assertGreater(report["missing"], 1)

    async def test_offline_and_unreadable_never_report_success(self):
        missing = await audit_vexora_esport(None)
        self.assertEqual(missing["status"], "offline")
        self.assertEqual(missing["passed"], 0)
        guild = sample_guild()
        guild.fetch_roles.side_effect = RuntimeError("Discord outage")
        result = await audit_vexora_esport(guild)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["passed"], 0)


class LiveAuditHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.old_state, self.old_port = app.STATE, app.PORT
        app.STATE = State(Path(self.folder.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.old_state, self.old_port
        self.folder.cleanup()

    async def test_read_only_endpoint_checks_server_when_online(self):
        guild = sample_guild()
        with patch.object(app.MANAGER, "get_guild", return_value=guild):
            response = await self.client.get(f"/api/audit/{GID}/vexora-esport")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["passed"], 56)
        self.assertEqual(data["status"], "verified")
        self.assertEqual(app.STATE.history(GID), [])
        guild.create_role.assert_not_awaited()
        guild.create_text_channel.assert_not_awaited()

    async def test_read_only_endpoint_refuses_unknown_disconnected_server(self):
        with patch.object(app.MANAGER, "get_guild", return_value=None):
            response = await self.client.get(f"/api/audit/{GID}/vexora-esport")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["status"], "offline")


if __name__ == "__main__":
    unittest.main()
