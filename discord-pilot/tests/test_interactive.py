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
from community_support import parse_dm_target, parse_staff_reply, staff_allowed, validate_application
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

    def permissions_for(self, role):
        return SimpleNamespace(view_channel=False)

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
        self.bot = False
        self.guild_permissions = SimpleNamespace(manage_channels=administrator)


class FakeGuild:
    id = int(GID)
    name = "Communauté test"

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

    async def fetch_member(self, user_id):
        if user_id != self.opener.id:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Member not found")
        return self.opener

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
        self.assertEqual(validate_event("quiz", {
            "channel_id": TEXT, "minutes": 15, "question": "La meilleure map ?",
            "options": ["Ascent", "Haven"], "correct_index": 1}, guild)["correct_index"], 1)
        bad = [
            ("poll", {"channel_id": CATEGORY, "minutes": 10, "question": "Map ?", "options": ["A", "B"]}),
            ("poll", {"channel_id": TEXT, "minutes": 10, "question": "Map ?", "options": ["A", "a"]}),
            ("poll", {"channel_id": TEXT, "minutes": 0, "question": "Map ?", "options": ["A", "B"]}),
            ("poll", {"channel_id": TEXT, "minutes": True, "question": "Map ?", "options": ["A", "B"]}),
            ("giveaway", {"channel_id": TEXT, "minutes": 10081, "prize": "Lot"}),
            ("giveaway", {"channel_id": TEXT, "minutes": 1, "prize": "Lot", "script": "extra"}),
            ("quiz", {"channel_id": TEXT, "minutes": 1, "question": "Une question ?",
                      "options": ["A", "B"], "correct_index": True}),
            ("quiz", {"channel_id": TEXT, "minutes": 1, "question": "Une question ?",
                      "options": ["A", "B"], "correct_index": 2}),
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

    def test_support_inputs_and_staff_authorization(self):
        self.assertEqual(parse_dm_target(f"!mail {GID} Bonjour"), (GID, "Bonjour"))
        self.assertEqual(parse_dm_target("Bonjour"), (None, "Bonjour"))
        self.assertEqual(parse_staff_reply(f"!reply <@{OWNER}> Réponse"), (OWNER, "Réponse"))
        self.assertFalse(staff_allowed(FakeMember()))
        self.assertTrue(staff_allowed(FakeMember(administrator=True)))
        self.assertEqual(validate_application({"nickname": "Hugo", "availability": "Soir",
                                               "motivation": "Une motivation assez longue"})["nickname"], "Hugo")
        for value in ("!reply", f"!reply {OWNER}    ", "!reply 1 bonjour"):
            with self.assertRaises(ValueError):
                parse_staff_reply(value)
        with self.assertRaises(ValueError):
            parse_dm_target(f"!mail {GID}  ")
        with self.assertRaises(ValueError):
            validate_application({"nickname": "H", "availability": "Soir", "motivation": "Pourquoi pas"})


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
                               response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(),
                                                        send_modal=AsyncMock()),
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

    async def test_esport_recruitment_opens_isolated_private_tickets_per_game(self):
        app.STATE.set_module(GID, "tickets", {
            "enabled": True, "panel_channel_id": TEXT, "category_id": CATEGORY,
            "staff_role_id": "", "recruitment_games": "valorant, fortnite",
        })
        created = {}
        next_id = 623456789012345678
        self.guild.created_names = []

        async def create_channel(name, **kwargs):
            nonlocal next_id
            next_id += 1
            channel = FakeText(str(next_id))
            created[channel.id] = channel
            self.guild.created_names.append(name)
            self.guild.last_overwrites = kwargs["overwrites"]
            return channel

        previous_get = self.guild.get_channel
        self.guild.get_channel = lambda ident: created.get(ident) or previous_get(ident)
        self.guild.create_text_channel = create_channel
        valorant = self.interaction("open")
        valorant.data["custom_id"] = f"pilot:ticket:open:{GID}:valorant"
        await self.bot.on_interaction(valorant)
        self.assertEqual(self.guild.created_names, ["recrut-valorant-345678"])
        first = next(iter(created.values()))
        first_record = app.STATE.state["tickets"][GID][str(first.id)]
        self.assertEqual(first_record["game"], "valorant")
        self.assertFalse(self.guild.last_overwrites[self.guild.default_role].view_channel)
        self.assertTrue(self.guild.last_overwrites[self.guild.opener].view_channel)

        # Same owner/game never produces a duplicate.
        await self.bot.on_interaction(valorant)
        self.assertEqual(len(created), 1)

        fortnite = self.interaction("open")
        fortnite.data["custom_id"] = f"pilot:ticket:open:{GID}:fortnite"
        await self.bot.on_interaction(fortnite)
        self.assertEqual(len(created), 2)
        self.assertEqual(self.guild.created_names[-1], "recrut-fortnite-345678")
        self.assertEqual(
            set(row["game"] for row in app.STATE.state["tickets"][GID].values()),
            {"valorant", "fortnite"},
        )

        blocked = self.interaction("open")
        blocked.data["custom_id"] = f"pilot:ticket:open:{GID}:rocket-league"
        await self.bot.on_interaction(blocked)
        self.assertEqual(len(created), 2)
        blocked.response.send_message.assert_awaited_once()

    async def test_missing_configured_staff_role_blocks_ticket_before_channel_creation(self):
        app.STATE.set_module(GID, "tickets", {
            "enabled": True, "panel_channel_id": TEXT, "category_id": CATEGORY,
            "staff_role_id": "723456789012345678",
        })
        interaction = self.interaction("open")
        self.guild.create_text_channel = AsyncMock()
        await self.bot.on_interaction(interaction)
        self.guild.create_text_channel.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()
        self.assertIn("n'existe plus", interaction.followup.send.call_args.args[0])

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

    async def test_quiz_uses_one_answer_per_user_and_reveals_correct_at_end(self):
        event_id = "a" * 32
        event = app.STATE.add_interactive_event(GID, {
            "type": "quiz", "id": event_id, "channel_id": TEXT,
            "message_id": str(self.guild.channel.last_message.id),
            "question": "La map ?", "options": ["Haven", "Ascent"],
            "correct_index": 1, "answers": {}, "ends_at": int(time.time()) + 120})
        interaction = self.interaction("open")
        interaction.channel = self.guild.channel
        interaction.channel_id = self.guild.channel.id
        interaction.data = {"custom_id": f"pilot:quiz:answer:{GID}:{event_id}:1"}
        await self.bot.on_interaction(interaction)
        await self.bot.on_interaction(interaction)
        self.assertEqual(event["answers"], {OWNER: 1})
        self.assertEqual(interaction.response.send_message.await_count, 2)
        event["ends_at"] = int(time.time()) - 1
        await self.bot.finish_event(self.guild, event)
        self.assertEqual(event["result"], {"votes": [0, 1], "participants": 1, "correct": 1})
        self.assertIn("Ascent", self.guild.channel.sent[-1][0])

    async def test_application_modal_panel_and_review(self):
        app.STATE.set_module(GID, "applications", {"enabled": True, "panel_channel_id": TEXT,
                                                       "staff_channel_id": str(self.guild.created.id),
                                                       "staff_role_id": ""})
        start = self.interaction("open")
        start.data = {"custom_id": f"pilot:application:open:{GID}"}
        await self.bot.on_interaction(start)
        start.response.send_modal.assert_awaited_once()
        modal = start.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, app.ApplicationModal)
        self.assertEqual(len(modal.children), 3)
        candidate = self.interaction("open")
        await self.bot.submit_application(candidate, {
            "nickname": "Joueur", "availability": "Chaque vendredi soir",
            "motivation": "Je veux vraiment rejoindre le support."})
        records = app.STATE.state["applications"][GID]
        self.assertEqual(len(records), 1)
        rec_id = next(iter(records))
        self.assertEqual(records[rec_id]["status"], "pending")
        unauthorized = self.interaction("open")
        unauthorized.channel = self.guild.created
        unauthorized.channel_id = self.guild.created.id
        unauthorized.user = FakeMember("723456789012345678")
        unauthorized.data = {"custom_id": f"pilot:application:reject:{GID}:{rec_id}"}
        await self.bot.on_interaction(unauthorized)
        self.assertEqual(records[rec_id]["status"], "pending")
        unauthorized.response.send_message.assert_awaited_once()
        await self.bot.submit_application(candidate, {
            "nickname": "Joueur", "availability": "Chaque vendredi soir",
            "motivation": "Je veux vraiment rejoindre le support."})
        self.assertEqual(len(records), 1)
        self.assertEqual(len(self.guild.created.sent), 1)
        reviewer = self.interaction("open")
        reviewer.channel = self.guild.created
        reviewer.channel_id = self.guild.created.id
        reviewer.user = FakeMember("723456789012345678", administrator=True)
        reviewer.data = {"custom_id": f"pilot:application:approve:{GID}:{rec_id}"}
        user = SimpleNamespace(send=AsyncMock())
        with patch.object(self.bot, "get_user", return_value=user):
            await self.bot.on_interaction(reviewer)
        self.assertEqual(records[rec_id]["status"], "approved")
        user.send.assert_awaited_once()
        await self.bot.on_interaction(reviewer)
        self.assertEqual(user.send.await_count, 1)

    async def test_modmail_requires_membership_and_protects_staff_reply(self):
        app.STATE.set_module(GID, "modmail", {"enabled": True,
                                               "staff_channel_id": str(self.guild.created.id),
                                               "staff_role_id": ""})
        dm_channel = FakeText("823456789012345678")
        dm = SimpleNamespace(author=self.guild.opener, content="Bonjour, j'ai besoin d'aide.",
                             channel=dm_channel, guild=None)
        with patch.object(app.PilotBot, "guilds", new_callable=__import__("unittest.mock").mock.PropertyMock,
                          return_value=[self.guild]):
            await self.bot.handle_modmail_dm(dm)
            await self.bot.handle_modmail_dm(dm)
        self.assertEqual(len(self.guild.created.sent), 1)
        self.assertEqual(len(dm_channel.sent), 2)
        staff_message = SimpleNamespace(author=FakeMember("723456789012345678", administrator=True),
                                        content=f"!reply {OWNER} Nous allons aider.",
                                        channel=self.guild.created, guild=self.guild)
        user = SimpleNamespace(send=AsyncMock())
        with patch.object(self.bot, "get_user", return_value=user):
            await self.bot.handle_modmail_staff(staff_message, app.STATE.module(GID, "modmail"))
        user.send.assert_awaited_once()
        stranger = SimpleNamespace(author=FakeMember("723456789012345678", administrator=True),
                                   content="!reply 923456789012345678 Un message non demandé",
                                   channel=self.guild.created, guild=self.guild)
        with patch.object(self.bot, "get_user", return_value=user):
            await self.bot.handle_modmail_staff(stranger, app.STATE.module(GID, "modmail"))
        self.assertEqual(user.send.await_count, 1)
        self.assertIn("Aucune conversation", self.guild.created.sent[-1][0])


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
            posted_before = len(guild.channel.sent)
            repeat = await self.client.post(f"/api/interactive/{GID}/tickets/panel",
                                            json={}, headers=self.headers)
            self.assertEqual((await repeat.json())["status"], "skipped")
            self.assertEqual(len(guild.channel.sent), posted_before)
            quiz = await self.client.post(f"/api/interactive/{GID}/quiz", json={
                "channel_id": TEXT, "minutes": 2, "question": "Quel est ton rang ?",
                "options": ["Gold", "Platinum", "Diamond"], "correct_index": 2}, headers=self.headers)
            self.assertEqual(quiz.status, 200)
            record = (await quiz.json())["event"]
            self.assertEqual(record["type"], "quiz")
            self.assertEqual(len(guild.channel.sent[-1][1]["view"].children), 3)
            app.STATE.set_module(GID, "applications", {
                "enabled": True, "panel_channel_id": TEXT,
                "staff_channel_id": str(guild.created.id), "staff_role_id": ""})
            form = await self.client.post(f"/api/interactive/{GID}/applications/panel",
                                          json={}, headers=self.headers)
            self.assertEqual(form.status, 200)
            self.assertEqual(app.STATE.state["application_panels"][GID]["channel_id"], TEXT)
            self.assertEqual(guild.channel.sent[-1][1]["view"].children[0].custom_id,
                             f"pilot:application:open:{GID}")
            posted_before = len(guild.channel.sent)
            repeat = await self.client.post(f"/api/interactive/{GID}/applications/panel",
                                            json={}, headers=self.headers)
            self.assertEqual((await repeat.json())["status"], "skipped")
            self.assertEqual(len(guild.channel.sent), posted_before)


if __name__ == "__main__":
    unittest.main()
