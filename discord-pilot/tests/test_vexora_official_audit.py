"""The real official Vexora Discord already contains the 2026-11-20 layout.

Verify the canonical 32+13 roles, 11 categories and 73 rooms WITHOUT creating
a second 56-action layout. No mocked API proof is called a live production test.
"""
from __future__ import annotations

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
from vexora_official_layout import (OFFICIAL_GUILD_ID, BASE_ROLES, EXTRA_ROLES,
                                    CATEGORIES, CHANNELS)

OTHER_GUILD = "1567347687379050727"


class Resource:
    def __init__(self, ident, name, kind, parent=None, private=False):
        self.id, self.name, self.type = ident, name, kind
        self.category_id = parent
        self.private = private

    def overwrites_for(self, _role):
        return SimpleNamespace(view_channel=False if self.private else None)


def guild_snapshot():
    assert len(BASE_ROLES) == 32
    assert len(EXTRA_ROLES) == 13
    assert len(CATEGORIES) == 11
    assert len(CHANNELS) == 73
    category_map = {
        name: Resource(100000000000000001 + i, name, "category",
                       private=name.startswith("🔒"))
        for i, name in enumerate(CATEGORIES)
    }
    channels = list(category_map.values())
    for i, (category, name, kind, private) in enumerate(CHANNELS):
        channels.append(Resource(200000000000000001 + i, name, kind,
                                 category_map[category].id, bool(private)))
    roles = [Resource(300000000000000001 + i, name, "role")
             for i, name in enumerate(BASE_ROLES + EXTRA_ROLES)]
    return SimpleNamespace(
        id=int(OFFICIAL_GUILD_ID), name="VexoraKey", default_role=object(),
        fetch_channels=AsyncMock(return_value=channels),
        fetch_roles=AsyncMock(return_value=roles),
        create_role=AsyncMock(side_effect=AssertionError("read only")),
        create_category=AsyncMock(side_effect=AssertionError("read only")),
        create_text_channel=AsyncMock(side_effect=AssertionError("read only")),
        roles=roles, channels=channels,
    )


class OfficialVexoraUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_deployed_layout_with_acl_is_129_not_56(self):
        guild = guild_snapshot()
        result = await audit_vexora_esport(guild)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["expected"], 129)
        self.assertEqual(result["passed"], 129)
        self.assertTrue(result["canonical_guild"])
        self.assertTrue(all(row["ok"] for row in result["checks"]))
        guild.create_role.assert_not_awaited()
        guild.create_category.assert_not_awaited()
        guild.create_text_channel.assert_not_awaited()
        guild.fetch_channels.assert_awaited_once()
        guild.fetch_roles.assert_awaited_once()

    async def test_missing_13th_role_fails_closed(self):
        guild = guild_snapshot()
        guild.roles[:] = [r for r in guild.roles if r.name != "🧭 Manager Esport"]
        result = await audit_vexora_esport(guild)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing"], 1)
        self.assertEqual(
            [c["name"] for c in result["checks"] if not c["ok"]], ["🧭 Manager Esport"])

    async def test_private_room_and_category_must_deny_everyone(self):
        guild = guild_snapshot()
        next(r for r in guild.channels if r.name == "🔒・strategies-rl").private = False
        next(r for r in guild.channels if r.name == "🔒 STAFF ESPORT").private = False
        result = await audit_vexora_esport(guild)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing"], 2)
        failures = {r["name"] for r in result["checks"] if not r["ok"]}
        self.assertEqual(failures, {"🔒・strategies-rl", "🔒 STAFF ESPORT"})

    async def test_duplicate_room_within_same_category_fails(self):
        guild = guild_snapshot()
        base = next(c for c in guild.channels if c.name == "💬・discussion-rl")
        guild.channels.append(Resource(900000000000000001, base.name, base.type, base.category_id))
        result = await audit_vexora_esport(guild)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing"], 1)

    async def test_offline_official_expected_count_is_129(self):
        result = await audit_vexora_esport(None, guild_id=OFFICIAL_GUILD_ID)
        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["expected"], 129)


class OfficialVexoraHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state, self.old_port = app.STATE, app.PORT
        app.STATE = State(Path(self.tmp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.old_state, self.old_port
        self.tmp.cleanup()

    async def test_real_existing_layout_audit_is_read_only(self):
        guild = guild_snapshot()
        with patch.object(app.MANAGER, "get_guild", return_value=guild):
            response = await self.client.get(
                f"/api/audit/{OFFICIAL_GUILD_ID}/vexora-esport")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual((data["expected"], data["passed"]), (129, 129))
        self.assertEqual(app.STATE.history(OFFICIAL_GUILD_ID), [])
        guild.create_role.assert_not_awaited()

    async def test_cannot_prepare_duplicate_template_for_official_guild(self):
        response = await self.client.post("/api/preset", json={
            "guild_id": OFFICIAL_GUILD_ID, "preset_id": "vexora-esport",
        }, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 400)
        self.assertIn("doublons", (await response.json())["error"])
        self.assertEqual(app.STATE.history(OFFICIAL_GUILD_ID), [])

    async def test_stale_draft_from_prior_version_cannot_execute(self):
        plan = app.STATE.add(OFFICIAL_GUILD_ID, "Modèle : Vexora",
                             PRESETS["vexora-esport"]["actions"],
                             "preset:vexora-esport")
        response = await self.client.post(f"/api/execute/{plan['id']}",
                                          json={}, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 400)
        self.assertEqual(app.STATE.get(plan["id"])["status"], "draft")
        self.assertIn("doublons", (await response.json())["error"])

    async def test_same_56_action_plan_without_preset_tag_is_blocked(self):
        plan = app.STATE.add(OFFICIAL_GUILD_ID, "Crée une structure Vexora Esport",
                             PRESETS["vexora-esport"]["actions"], "local")
        response = await self.client.post(f"/api/execute/{plan['id']}",
                                          json={}, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 400)
        self.assertEqual(app.STATE.get(plan["id"])["status"], "draft")

    async def test_non_official_guild_keeps_generic_preset(self):
        response = await self.client.post("/api/preset", json={
            "guild_id": OTHER_GUILD, "preset_id": "vexora-esport",
        }, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["plan"]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
