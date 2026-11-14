"""Isolated ticket, poll, giveaway and HTTP tests; no real Discord writes."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import discord
from aiohttp.test_utils import TestClient, TestServer

import app
from community_interactions import poll_summary, validate_event
from storage import State


GID = "1567347687379050727"
TEXT = "223456789012345678"
CATEGORY = "323456789012345678"
OWNER = "423456789012345678"
BOT = "523456789012345678"


class FakeMessage:
    def __init__(self, message_id=713456789012345678, reactions=None):
        self.id = message_id
        self.reactions = reactions or []
        self.add_reaction = AsyncMock()


class FakeText:
    type = "text"

    def __init__(self, channel_id=TEXT):
        self.id = int(channel_id)
        self.name = "sondages"
        self.mention = f"<#{channel_id}>"
        self.sent = []
        self.last_message = FakeMessage()
        self.edit = AsyncMock()
        self.set_permissions = AsyncMock()

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))
        return self.last_message

    async def fetch_message(self, message_id):
        if message_id != self.last_message.id:
            raise ValueError("Message absent")
        return self.last_message


class FakeCategory:
    type = "category"

    def __init__(self):
        self.id = int(CATEGORY)


class FakeMember:
    def __init__(self, user_id=OWNER, administrator=False):
        self.id = int(user_id)
        self.mention = f"<@{user_id}>"
        self.roles = []
        self.guild_permissions = SimpleNamespace(manage_channels=administrator)


class FakeGuild:
    id = int(GID)

    def __init__(self):
        self.channel = FakeText()
        self.category = FakeCategory()
        self.created = FakeText("623456789012345678")
        self.default_role = object()
        self.me = FakeMember(BOT)
        self.opener = FakeMember()
        self.last_overwrites = None

    def get_channel(self, channel_id):
        return {self.channel.id: self.channel, self.category.id: self.category,
                self.created.id: self.created}.get(channel_id)

    def get_role(self, role_id):
        return None

    def get_member(self, user_id):
        return self.opener if user_id == self.opener.id else None

    async def create_text_channel(self, name, **kwargs):
        self.last_overwrites = kwargs["overwrites"]
        return self.created


class InteractionValidationTests(unittest.TestCase):
    def test_poll_and_giveaway_input_must_match_guild_and_schema(self):
        guild = FakeGuild()
        self.assertEqual(validate_event("poll", {
            "channel_id": TEXT, "minutes": 10, "question": "Ta map préférée ?",
            "options": ["Ascent", "Haven"]}, guild)["options"], ["Ascent", "Haven"])
        self.assertEqual(validate_event("giveaway", {
            "channel_id": TEXT, "minutes": 1, "prize": "Un skin"}, guild)["prize"], "Un skin")
        bad = [
            ("poll", {"channel_id": CATEGORY, "minutes": 10, "question": "Map ?", "options": ["A", "B"]}),
            ("poll", {"channel_id": TEXT, "minutes": 10, "question": "Map ?", "options": ["A", "a"]}),
            ("poll", {"channel_id": TEXT, "minutes": 0, "question": "Map ?", "options": ["A", "B"]}),
            ("poll", {"channel_id": TEXT, "minutes": True, "question": "Map ?", "options": ["A", "B"]}),
            ("giveaway", {"channel_id": TEXT, "minutes": 10081, "prize": "Lot"}),
            ("giveaway", {"channel_id": TEXT, "minutes": 1, "prize": "Lot", "script": "extra"}),
        ]
        for kind, value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_event(kind, value, guild)

    def test_poll_summary_with_and_without_votes(self):
        self.assertIn("Gagnant : **Haven**", poll_summary("Map ?", ["Ascent", "Haven"], [2, 3]))
        self.assertIn("Égalité", poll_summary("Map ?", ["Ascent", "Haven"], [2, 2]))
        self.assertIn("Aucun vote", poll_summary("Map ?", ["Ascent", "Haven"], [0, 0]))
        with self.assertRaises(ValueError):
            poll_summary("Map ?", ["A", "B"], [1])


class InteractionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = app.STATE
        app.STATE = State(Path(self.tmp.name))
        self.guild = FakeGuild()
        self.manager = SimpleNamespace(automation_warning=None)
        self.bot = app.PilotBot(self.manager)
        self.channel_patch = patch.object(app.discord, "TextChannel", FakeText)
        self.category_patch = patch.object(app.discord, "CategoryChannel", FakeCategory)
        self.channel_patch.start()
        self.category_patch.start()

    async def asyncTearDown(self):
        self.category_patch.stop()
        self.channel_patch.stop()
        await self.bot.close()
        app.STATE = self.original
        self.tmp.cleanup()

    def interaction(self, mode, guild_id=GID):
        channel = self.guild.created if mode == "close" else self.guild.channel
        custom_id = (f"pilot:ticket:close:{guild_id}:{channel.id}" if mode == "close"
                     else f"pilot:ticket:open:{guild_id}")
        return SimpleNamespace(type=discord.InteractionType.component,
                               guild=self.guild, channel=channel, channel_id=channel.id,
                               user=self.guild.opener, data={"custom_id": custom_id},
                               response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def test_persistent_button_opens_private_ticket_and_archives_without_deletion(self):
        app.STATE.set_module(GID, "tickets", {
            "enabled": True, "panel_channel_id": TEXT, "category_id": CATEGORY,
            "staff_role_id": ""})
        interaction = self.interaction("open")
        await self.bot.on_interaction(interaction)
        row = app.STATE.state["tickets"][GID][str(self.guild.created.id)]
        self.assertEqual(row["status"], "open")
        self.assertFalse(self.guild.last_overwrites[self.guild.default_role].view_channel)
        self.assertTrue(self.guild.last_overwrites[self.guild.opener].view_channel)
        self.assertTrue(self.guild.last_overwrites[self.guild.me].view_channel)
        self.assertEqual(len(self.guild.created.sent), 1)
        self.assertIn("close", self.guild.created.sent[0][1]["view"].children[0].custom_id)
        self.assertEqual(interaction.followup.send.await_count, 1)
        await self.bot.on_interaction(interaction)
        self.assertEqual(len(self.guild.created.sent), 1)
        close = self.interaction("close")
        await self.bot.on_interaction(close)
        self.assertEqual(row["status"], "closed")
        self.assertEqual(self.guild.created.set_permissions.await_count, 1)
        self.assertEqual(self.guild.created.edit.await_count, 1)
        self.assertEqual(len(app.STATE.state["tickets"][GID]), 1)

    async def test_only_owner_or_staff_can_close(self):
        app.STATE.state["tickets"].setdefault(GID, {})[str(self.guild.created.id)] = {
            "owner_id": OWNER, "status": "open"}
        stranger = self.interaction("close")
        stranger.user = FakeMember("723456789012345678")
        await self.bot.on_interaction(stranger)
        self.assertEqual(app.STATE.state["tickets"][GID][str(self.guild.created.id)]["status"], "open")
        stranger.response.send_message.assert_awaited_once()
        self.guild.created.edit.assert_not_awaited()

    async def test_giveaway_winner_is_persisted_and_not_redrawn_when_announcement_retried(self):
        class FakeReaction:
            emoji = "🎉"

            async def users(self, limit=None):
                yield SimpleNamespace(id=int(BOT), bot=True)
                yield SimpleNamespace(id=int(OWNER), bot=False)

        self.guild.channel.last_message.reactions = [FakeReaction()]
        event = app.STATE.add_interactive_event(GID, {
            "type": "giveaway", "channel_id": TEXT,
            "message_id": str(self.guild.channel.last_message.id),
            "prize": "Un cadeau", "ends_at": int(time.time()) - 1})
        await self.bot.finish_event(self.guild, event)
        self.assertEqual(event["result"], {"participants": 1, "winner_id": OWNER})
        self.assertTrue(event["announced"])
        first = event["result"].copy()
        event["announced"] = False
        await self.bot.finish_event(self.guild, event)
        self.assertEqual(event["result"], first)
        self.assertEqual(len(self.guild.channel.sent), 2)

    async def test_poll_counts_are_saved_and_bot_reaction_is_excluded(self):
        self.guild.channel.last_message.reactions = [
            SimpleNamespace(emoji="1️⃣", count=4, me=True),
            SimpleNamespace(emoji="2️⃣", count=2, me=True)]
        event = app.STATE.add_interactive_event(GID, {
            "type": "poll", "channel_id": TEXT,
            "message_id": str(self.guild.channel.last_message.id),
            "question": "La map ?", "options": ["Haven", "Ascent"], "ends_at": int(time.time()) - 1})
        await self.bot.finish_event(self.guild, event)
        self.assertEqual(event["result"]["votes"], [3, 1])
        self.assertIn("Haven", self.guild.channel.sent[0][0])


class InteractionHttpTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_endpoint_rejects_offline_writes_and_missing_csrf(self):
        self.assertEqual((await self.client.get(f"/api/interactive/{GID}")).status, 200)
        data = {"channel_id": TEXT, "minutes": 1, "prize": "Cadeau"}
        self.assertEqual((await self.client.post(f"/api/interactive/{GID}/giveaway",
                                                 json=data)).status, 403)
        self.assertEqual((await self.client.post(f"/api/interactive/{GID}/giveaway",
                                                 json=data, headers=self.headers)).status, 400)
        self.assertEqual(app.STATE.state["interactive_events"], {})

    async def test_poll_post_and_panel_use_real_discord_call_mock_and_save_ids(self):
        guild = FakeGuild()
        app.STATE.set_module(GID, "tickets", {
            "enabled": True, "panel_channel_id": TEXT, "category_id": CATEGORY,
            "staff_role_id": ""})
        with patch.object(app.MANAGER, "get_guild", return_value=guild), \
             patch.object(app.discord, "TextChannel", FakeText):
            poll = await self.client.post(f"/api/interactive/{GID}/poll", json={
                "channel_id": TEXT, "minutes": 2, "question": "Tu préfères ?",
                "options": ["A", "B"]}, headers=self.headers)
            self.assertEqual(poll.status, 200)
            self.assertEqual(guild.channel.last_message.add_reaction.await_count, 2)
            records = app.STATE.state["interactive_events"][GID]
            self.assertEqual(len(records), 1)
            self.assertEqual(next(iter(records.values()))["status"], "open")
            panel = await self.client.post(f"/api/interactive/{GID}/tickets/panel",
                                           json={}, headers=self.headers)
            self.assertEqual(panel.status, 200)
            self.assertEqual(app.STATE.state["ticket_panels"][GID]["channel_id"], TEXT)
            self.assertEqual(guild.channel.sent[-1][1]["view"].children[0].custom_id,
                             f"pilot:ticket:open:{GID}")


if __name__ == "__main__":
    unittest.main()
