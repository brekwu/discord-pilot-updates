"""Native modules: secure settings, persistence and actual event handlers."""

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import discord
from aiohttp.test_utils import TestClient, TestServer

import app
from community_modules import (MODULES, SpamTracker, level_for_xp,
                               normalize_module, paris_slot, should_filter)
from storage import State


GID = "1567347687379050727"
RID = "123456789012345678"
CID = "223456789012345678"
VID = "323456789012345678"
CATID = "423456789012345678"


class FakeRole:
    id = int(RID)

    def is_default(self):
        return False


class FakeChannel:
    def __init__(self, channel_id, kind):
        self.id = int(channel_id)
        self.type = kind
        self.name = "tests"

    def permissions_for(self, role):
        return SimpleNamespace(view_channel=False)


class FakeGuild:
    id = int(GID)
    name = "Serveur test"
    roles = [FakeRole()]
    default_role = FakeRole()

    def __init__(self):
        self.text = FakeChannel(CID, "text")
        self.voice = FakeChannel(VID, "voice")
        self.category = FakeChannel(CATID, "category")

    def get_channel(self, cid):
        return {self.text.id: self.text, self.voice.id: self.voice,
                self.category.id: self.category}.get(cid)

    def get_role(self, rid):
        return self.roles[0] if rid == self.roles[0].id else None


class ModuleLogicTests(unittest.TestCase):
    def test_voice_commands_only_enable_precise_module(self):
        self.assertEqual(app.native_module_plan("Active l'XP"),
                         [{"type": "set_module", "module": "xp", "enabled": "true"}])
        self.assertEqual(app.native_module_plan("Désactive l'antispam"),
                         [{"type": "set_module", "module": "antispam", "enabled": "false"}])
        self.assertEqual(app.native_module_plan("Active l'XP et la musique"), [])
        self.assertEqual(app.native_module_plan("Configure des salons avec les XP"), [])

    def test_every_module_opt_in_and_strict_config(self):
        guild = FakeGuild()
        self.assertEqual(len(MODULES), 17)
        self.assertEqual(normalize_module("autorole", {"enabled": True, "role_id": RID}, guild),
                         {"enabled": True, "role_id": RID})
        self.assertEqual(normalize_module("audit", {"enabled": True, "channel_id": CID}, guild)["channel_id"], CID)
        self.assertEqual(normalize_module("voice_rooms", {"enabled": True, "lobby_id": VID}, guild)["lobby_id"], VID)
        self.assertEqual(normalize_module("xp", {"enabled": True}, guild), {"enabled": True, "channel_id": ""})
        self.assertEqual(normalize_module("tickets", {"enabled": True, "panel_channel_id": CID,
                                                      "category_id": CATID}, guild),
                         {"enabled": True, "panel_channel_id": CID, "category_id": CATID,
                          "staff_role_id": ""})
        self.assertEqual(normalize_module("modmail", {"enabled": True, "staff_channel_id": CID}, guild),
                         {"enabled": True, "staff_channel_id": CID, "staff_role_id": ""})
        self.assertEqual(normalize_module("applications", {"enabled": True, "panel_channel_id": CID,
                                                           "staff_channel_id": CID}, guild)["staff_channel_id"], CID)
        self.assertEqual(normalize_module("level_rewards", {"enabled": True, "role_id": RID,
                                                           "level": "5"}, guild)["level"], "5")
        self.assertEqual(normalize_module("invite_rewards", {"enabled": True, "role_id": RID,
                                                            "invites": "11"}, guild)["invites"], "11")
        self.assertEqual(normalize_module("activity_stats", {"enabled": True}, guild), {"enabled": True})
        self.assertEqual(normalize_module("warnings", {"enabled": True, "channel_id": CID}, guild)["channel_id"], CID)
        for name, config in [
            ("fake_module", {"enabled": True}),
            ("xp", {"enabled": "yes"}),
            ("xp", {"enabled": True, "shell": "powershell"}),
            ("autorole", {"enabled": True, "role_id": "not-an-id"}),
            ("autorole", {"enabled": True, "role_id": CID}),
            ("audit", {"enabled": True, "channel_id": VID}),
            ("voice_rooms", {"enabled": True, "lobby_id": CID}),
            ("tickets", {"enabled": True, "panel_channel_id": CID, "category_id": CID}),
            ("daily_post", {"enabled": True, "channel_id": CID, "hour": "25:99", "message": "bonjour"}),
            ("wordfilter", {"enabled": True, "words": ""}),
            ("level_rewards", {"enabled": True, "role_id": RID, "level": "0"}),
            ("level_rewards", {"enabled": True, "role_id": RID, "level": "1.5"}),
            ("invite_rewards", {"enabled": True, "role_id": RID, "invites": "1001"}),
            ("invite_rewards", {"enabled": True, "role_id": CID, "invites": "5"}),
            ("warnings", {"enabled": True, "channel_id": VID}),
        ]:
            with self.subTest(name=name, config=config), self.assertRaises(ValueError):
                normalize_module(name, config, guild)

    def test_no_guessing_links_word_boundaries_and_spam_window(self):
        self.assertTrue(should_filter("Visite https://example.fr", {"enabled": True}, links=True))
        self.assertFalse(should_filter("Bonjour", {"enabled": True}, links=True))
        self.assertFalse(should_filter("https://example.fr", {"enabled": False}, links=True))
        self.assertTrue(should_filter("C'est MECHANT!", {"enabled": True, "words": "méchant, mechant"}))
        self.assertFalse(should_filter("mechante", {"enabled": True, "words": "mechant"}))
        counter = SpamTracker()
        for number in range(5):
            self.assertFalse(counter.flag(10, 20, now=100 + number))
        self.assertTrue(counter.flag(10, 20, now=105))
        for number in range(6):
            self.assertFalse(counter.flag(10, 20, now=106 + number / 10))
        self.assertFalse(counter.flag(10, 21, now=107))
        for number in range(5):
            self.assertFalse(counter.flag(10, 20, now=180 + number))
        self.assertTrue(counter.flag(10, 20, now=185))

    def test_xp_cooldown_level_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory))
            state.set_module(GID, "xp", {"enabled": True, "channel_id": ""})
            self.assertEqual(state.record_xp(GID, RID, 100), (10, 0, False))
            self.assertEqual(state.record_xp(GID, RID, 120), (10, 0, False))
            for number in range(1, 6):
                latest = state.record_xp(GID, RID, 100 + 60 * number)
            self.assertEqual(latest, (60, 1, True))
            self.assertEqual(level_for_xp(54), 0)
            self.assertEqual(level_for_xp(60), 1)
            loaded = State(Path(directory))
            self.assertEqual(loaded.leaderboard(GID)[0], {"member_id": RID, "xp": 60, "level": 1})
            self.assertTrue(loaded.module(GID, "xp")["enabled"])

    def test_daily_schedule_timezone(self):
        self.assertEqual(paris_slot(datetime.fromisoformat("2026-03-29T01:30:00+00:00")),
                         ("2026-03-29", "03:30"))
        self.assertEqual(paris_slot(datetime.fromisoformat("2026-11-14T08:15:00+00:00")),
                         ("2026-11-14", "09:15"))

    def test_activity_invites_warning_counts_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory))
            self.assertEqual(state.record_message_stat(GID, RID), 1)
            self.assertEqual(state.record_message_stat(GID, RID), 2)
            self.assertEqual(state.increment_invites(GID, RID), 1)
            self.assertEqual(state.increment_invites(GID, RID), 2)
            self.assertEqual(state.add_warning(GID, RID, "Respecter le règlement")["count"], 1)
            self.assertEqual(state.add_warning(GID, RID, "Deuxième rappel")["count"], 2)
            loaded = State(Path(directory))
            self.assertEqual(loaded.activity_leaderboard(GID), [{"member_id": RID, "messages": 2}])
            self.assertEqual(loaded.invite_leaderboard(GID), [{"member_id": RID, "invites": 2}])
            self.assertEqual(loaded.state["warning_totals"][GID][RID], 2)
            self.assertNotIn("content", loaded.state["message_stats"][GID])


class ModuleHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous, self.previous_port = app.STATE, app.PORT
        app.STATE = State(Path(self.tmp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        boot = await (await self.client.get("/api/bootstrap")).json()
        self.headers = {"X-Pilot-CSRF": boot["csrf"]}

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.previous, self.previous_port
        self.tmp.cleanup()

    async def test_get_modules_safe_and_offline_write_refused(self):
        result = await self.client.get(f"/api/modules/{GID}")
        self.assertEqual(result.status, 200)
        data = await result.json()
        self.assertEqual(len(data["modules"]), 17)
        self.assertEqual(data["invite_leaderboard"], [])
        self.assertEqual(data["activity_leaderboard"], [])
        self.assertEqual(data["warnings"], [])
        self.assertFalse(data["online"])
        self.assertEqual(data["settings"], {})
        self.assertEqual((await self.client.post(f"/api/modules/{GID}/xp", json={"enabled": True})).status, 403)
        refused = await self.client.post(f"/api/modules/{GID}/xp", json={"enabled": True}, headers=self.headers)
        self.assertEqual(refused.status, 400)
        self.assertEqual(app.STATE.state["modules"], {})

    async def test_authorized_save_checks_guild_and_csrf(self):
        fake = FakeGuild()
        with patch.object(app.MANAGER, "get_guild", return_value=fake), \
             patch.object(app.MANAGER, "activate_automations", new_callable=AsyncMock):
            resp = await self.client.post(f"/api/modules/{GID}/xp", json={"enabled": True}, headers=self.headers)
            self.assertEqual(resp.status, 200)
            self.assertTrue(app.STATE.module(GID, "xp")["enabled"])
            bad = await self.client.post(f"/api/modules/{GID}/autorole",
                                         json={"enabled": True, "role_id": VID}, headers=self.headers)
            self.assertEqual(bad.status, 400)
            self.assertEqual(app.STATE.module(GID, "autorole"), {})

    async def test_warn_requires_opt_in_real_member_private_channel_and_csrf(self):
        guild = FakeGuild()
        member = SimpleNamespace(display_name="Utilisateur")
        guild.get_member = lambda member_id: member if member_id == int(RID) else None
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Absent"))
        guild.text.send = AsyncMock()
        endpoint = f"/api/community/{GID}/warn"
        data = {"member_id": RID, "reason": "Rappel du règlement"}
        self.assertEqual((await self.client.post(endpoint, json=data)).status, 403)
        with patch.object(app.MANAGER, "get_guild", return_value=guild), \
             patch.object(app.discord, "TextChannel", FakeChannel):
            self.assertEqual((await self.client.post(endpoint, json=data, headers=self.headers)).status, 400)
            app.STATE.set_module(GID, "warnings", {"enabled": True, "channel_id": CID})
            bad = await self.client.post(endpoint, json={"member_id": RID, "reason": "x"}, headers=self.headers)
            self.assertEqual(bad.status, 400)
            self.assertEqual(app.STATE.state["warnings"], {})
            guild.text.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Non")
            self.assertEqual((await self.client.post(endpoint, json=data, headers=self.headers)).status, 400)
            self.assertEqual(app.STATE.state["warnings"], {})
            guild.text.send.side_effect = None
            result = await self.client.post(endpoint, json=data, headers=self.headers)
            self.assertEqual(result.status, 200)
            self.assertEqual((await result.json())["warning"]["count"], 1)
            self.assertEqual(app.STATE.state["warning_totals"][GID][RID], 1)
            guild.text.send.assert_awaited()


class ModuleEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = app.STATE
        app.STATE = State(Path(self.tmp.name))
        self.manager = SimpleNamespace(error=None, automation_warning=None, remember=False,
                                       current_token=None, ready=False)
        self.bot = app.PilotBot(self.manager)

    async def asyncTearDown(self):
        await self.bot.close()
        app.STATE = self.previous
        self.tmp.cleanup()

    async def test_message_event_records_xp_and_anti_spam_deletes(self):
        app.STATE.set_module(GID, "xp", {"enabled": True, "channel_id": ""})
        app.STATE.set_module(GID, "antispam", {"enabled": True})
        author = SimpleNamespace(id=int(RID), bot=False,
                                 guild_permissions=SimpleNamespace(manage_messages=False, administrator=False),
                                 timeout=AsyncMock())
        fake = SimpleNamespace(guild=SimpleNamespace(id=int(GID)), author=author,
                               channel=SimpleNamespace(id=int(CID)), content="Bonjour", delete=AsyncMock())
        for _ in range(5):
            await self.bot.on_message(fake)
        self.assertEqual(app.STATE.leaderboard(GID)[0]["xp"], 10)
        fake.delete.assert_not_awaited()
        await self.bot.on_message(fake)
        fake.delete.assert_awaited_once()
        author.timeout.assert_awaited_once()
        self.assertEqual(app.STATE.leaderboard(GID)[0]["xp"], 10)

    async def test_moderator_exempt_and_suggestion_reactions(self):
        app.STATE.set_module(GID, "antispam", {"enabled": True})
        app.STATE.set_module(GID, "suggestions", {"enabled": True, "channel_id": CID})
        author = SimpleNamespace(id=int(RID), bot=False,
                                 guild_permissions=SimpleNamespace(manage_messages=True))
        message = SimpleNamespace(guild=SimpleNamespace(id=int(GID)), author=author,
                                  channel=SimpleNamespace(id=int(CID)), content="Hello",
                                  add_reaction=AsyncMock(), delete=AsyncMock())
        for _ in range(10):
            await self.bot.on_message(message)
        message.delete.assert_not_awaited()
        self.assertEqual(message.add_reaction.await_count, 20)

    async def test_reaction_role_add_and_remove(self):
        app.STATE.set_module(GID, "reaction_role", {"enabled": True, "role_id": RID,
                                                    "message_id": "423456789012345678", "emoji": "✅"})
        role = FakeRole()
        member = SimpleNamespace(add_roles=AsyncMock(), remove_roles=AsyncMock())
        guild = SimpleNamespace(get_role=lambda rid: role if rid == int(RID) else None,
                                get_member=lambda uid: member)
        payload = SimpleNamespace(guild_id=int(GID), user_id=int(RID),
                                  message_id=423456789012345678, emoji="✅", member=member)
        with patch.object(self.bot, "get_guild", return_value=guild):
            await self.bot.on_raw_reaction_add(payload)
            await self.bot.on_raw_reaction_remove(payload)
            member.add_roles.assert_awaited_once_with(role, reason="Discord Pilot : rôle par réaction")
            member.remove_roles.assert_awaited_once_with(role, reason="Discord Pilot : retrait du rôle par réaction")
            payload.emoji = "❌"
            await self.bot.on_raw_reaction_add(payload)
            self.assertEqual(member.add_roles.await_count, 1)

    async def test_level_reward_after_threshold_without_duplicate_role(self):
        app.STATE.set_module(GID, "xp", {"enabled": True, "channel_id": ""})
        app.STATE.set_module(GID, "level_rewards", {"enabled": True, "role_id": RID, "level": "1"})
        role = FakeRole()
        guild = SimpleNamespace(id=int(GID), get_role=lambda rid: role if rid == int(RID) else None)
        member = SimpleNamespace(id=int(RID), bot=False, roles=[], add_roles=AsyncMock(),
                                 guild_permissions=SimpleNamespace(manage_messages=False))
        message = SimpleNamespace(guild=guild, author=member, content="bonjour", channel=SimpleNamespace(id=int(CID)))
        app.STATE.state["xp_stats"][GID] = {RID: {"xp": 50, "last_at": 100}}
        with patch.object(app.time, "time", return_value=500):
            await self.bot.on_message(message)
        member.add_roles.assert_awaited_once_with(role, reason="Discord Pilot : récompense niveau XP")
        member.roles.append(role)
        with patch.object(app.time, "time", return_value=600):
            await self.bot.on_message(message)
        self.assertEqual(member.add_roles.await_count, 1)

    async def test_invite_reward_when_inviter_is_identifiable(self):
        app.STATE.set_module(GID, "invite_rewards", {"enabled": True, "role_id": RID, "invites": "1"})
        inviter = SimpleNamespace(id=int(RID), roles=[], add_roles=AsyncMock())
        role = FakeRole()
        guild = SimpleNamespace(id=int(GID), get_member=lambda uid: inviter if uid == int(RID) else None,
                                get_role=lambda uid: role if uid == int(RID) else None)
        joined = SimpleNamespace(guild=guild, id=987654321012345678)
        self.bot.invite_snapshots[int(GID)] = {"abc": (0, int(RID))}
        with patch.object(self.bot, "refresh_invites", new_callable=AsyncMock, return_value={"abc": (1, int(RID))}):
            await self.bot.on_member_join(joined)
        inviter.add_roles.assert_awaited_once_with(role, reason="Discord Pilot : récompense d'invitations")
        self.assertEqual(app.STATE.invite_leaderboard(GID)[0]["invites"], 1)


if __name__ == "__main__":
    unittest.main()
