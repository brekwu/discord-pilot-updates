"""No Discord network: verify full community workflow and invite attribution."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
from discord_ops import execute_action, channel_by_name
from planner import community_automation_plan, validate_actions, parse_ollama_decision
from storage import State


FULL_REQUEST = (
    "Je veux que tu crées un salon. Bienvenue, au revoir et invitation. "
    "Je veux également dans le salon bienvenu, il est déjà créé, que dès qu'une "
    "personne arrive dans le serveur il y ait des bienvenus. Même chose que "
    "quelqu'un quitte, ça va dans le salon au revoir. Et invitation, si un "
    "utilisateur invite quelqu'un ça dit vous avez invité votre première "
    "personne, puis s'il a déjà dix personnes sa onzième personne."
)


class CommunityPlanTests(unittest.TestCase):
    def test_full_natural_request_is_five_action_draft(self):
        self.assertEqual(community_automation_plan(FULL_REQUEST), [
            {"type": "create_text_channel", "name": "au-revoir"},
            {"type": "create_text_channel", "name": "invitation"},
            {"type": "configure_welcome", "channel": "bienvenu"},
            {"type": "configure_farewell", "channel": "au-revoir"},
            {"type": "configure_invites", "channel": "invitation"},
        ])

    def test_bot_events_not_inferred_without_explicit_instruction(self):
        self.assertEqual(community_automation_plan("Crée trois salons bienvenue, au revoir et invitation"), [])
        self.assertEqual(community_automation_plan("Supprime un salon et configure les messages de bienvenue à chaque arrivée"), [])

    def test_model_alias_normalization_remains_safe(self):
        actions, _ = parse_ollama_decision('{"actions":['
            '{"type":"welcome_messages","name":"bienvenu"},'
            '{"type":"setup_goodbye","channel_name":"au-revoir"},'
            '{"type":"invite_tracker","channel":"invitation"}]}')
        self.assertEqual(actions, [
            {"type": "configure_welcome", "channel": "bienvenu"},
            {"type": "configure_farewell", "channel": "au-revoir"},
            {"type": "configure_invites", "channel": "invitation"},
        ])
        with self.assertRaises(ValueError):
            validate_actions([{"type": "configure_invites", "channel": "invitation", "script": "powershell"}])

    def test_attribution_requires_unique_increment(self):
        self.assertEqual(app.identify_inviter({"a": (2, 123)}, {"a": (3, 123)}), 123)
        self.assertIsNone(app.identify_inviter({}, {"a": (1, 123)}))
        self.assertIsNone(app.identify_inviter({"a": (2, 123)}, {"a": (4, 123)}))
        self.assertIsNone(app.identify_inviter({"a": (2, 123), "b": (1, 234)},
                                                   {"a": (3, 123), "b": (2, 234)}))
        self.assertEqual(app.invite_ordinal(1), "première")
        self.assertEqual(app.invite_ordinal(11), "onzième")


class FakeTextChannel:
    def __init__(self, name, channel_id):
        self.name, self.id = name, channel_id
        self.messages = []

    async def send(self, content, **kwargs):
        self.messages.append((content, kwargs))


class FakeGuild:
    def __init__(self):
        self.id = 1567347687379050727
        self.name = "Test"
        self.channels = [FakeTextChannel("bienvenu", 10), FakeTextChannel("au-revoir", 20),
                         FakeTextChannel("invitation", 30)]
        self.invite_data = []

    def get_channel(self, channel_id):
        return next((c for c in self.channels if c.id == channel_id), None)

    async def invites(self):
        return self.invite_data


class RuntimeAutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_state = app.STATE
        app.STATE = State(Path(self.temp.name))
        self.guild = FakeGuild()
        self.text_patch = patch.object(app.discord, "TextChannel", FakeTextChannel)
        self.text_patch.start()
        self.manager = SimpleNamespace(error=None, automation_warning=None, remember=False,
                                       current_token=None, ready=False)
        self.bot = app.PilotBot(self.manager, member_events=True)

    async def asyncTearDown(self):
        await self.bot.close()
        self.text_patch.stop()
        app.STATE = self.original_state
        self.temp.cleanup()

    async def test_configuration_persists_and_resolves_slugged_channels(self):
        guild_id = str(self.guild.id)
        self.assertEqual(channel_by_name(self.guild, "au revoir").id, 20)
        for kind, channel in (("configure_welcome", "bienvenu"),
                              ("configure_farewell", "au revoir"),
                              ("configure_invites", "invitation")):
            status, _ = await execute_action(self.guild, {"type": kind, "channel": channel}, state=app.STATE)
            self.assertEqual(status, "done")
        self.assertEqual(State(Path(self.temp.name)).automation_channel(guild_id, "farewell"), "20")

    async def test_arrival_departure_and_first_eleventh_invitation(self):
        guild_id = str(self.guild.id)
        app.STATE.set_automation(guild_id, "welcome", "10")
        app.STATE.set_automation(guild_id, "farewell", "20")
        app.STATE.set_automation(guild_id, "invites", "30")
        inviter = SimpleNamespace(id=123456789012345678)
        self.guild.invite_data = [SimpleNamespace(code="abc", uses=0, inviter=inviter)]
        await self.bot.refresh_invites(self.guild)
        member = SimpleNamespace(id=987654321012345678, mention="<@987654321012345678>",
                                 display_name="Membre", guild=self.guild)
        self.guild.invite_data = [SimpleNamespace(code="abc", uses=1, inviter=inviter)]
        await self.bot.on_member_join(member)
        self.assertEqual(len(self.guild.channels[0].messages), 1)
        self.assertIn("Bienvenue", self.guild.channels[0].messages[0][0])
        self.assertIn("première", self.guild.channels[2].messages[0][0])
        self.assertEqual(app.STATE.state["invite_counts"][guild_id][str(inviter.id)], 1)
        # Simulate ten further attributable joins; the 11th is grammatical.
        for count in range(2, 12):
            self.guild.invite_data = [SimpleNamespace(code="abc", uses=count, inviter=inviter)]
            await self.bot.on_member_join(member)
        self.assertIn("onzième", self.guild.channels[2].messages[-1][0])
        self.assertEqual(State(Path(self.temp.name)).state["invite_counts"][guild_id][str(inviter.id)], 11)
        await self.bot.on_member_remove(member)
        self.assertIn("a quitté", self.guild.channels[1].messages[0][0])

    async def test_ambiguous_invites_are_not_falsely_attributed(self):
        guild_id = str(self.guild.id)
        app.STATE.set_automation(guild_id, "invites", "30")
        inviter = SimpleNamespace(id=123456789012345678)
        self.guild.invite_data = [SimpleNamespace(code="abc", uses=0, inviter=inviter)]
        await self.bot.refresh_invites(self.guild)
        self.guild.invite_data = [SimpleNamespace(code="abc", uses=2, inviter=inviter)]
        member = SimpleNamespace(id=987654321012345678, mention="<@987654321012345678>", guild=self.guild)
        with patch.object(app.asyncio, "sleep", new=AsyncMock()):
            await self.bot.on_member_join(member)
        self.assertEqual(app.STATE.state["invite_counts"], {})
        self.assertEqual(self.guild.channels[2].messages, [])


class ApiAutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_state, self.original_port = app.STATE, app.PORT
        app.STATE = State(Path(self.temp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        self.headers = {"X-Pilot-CSRF": csrf}

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.original_state, self.original_port
        self.temp.cleanup()

    async def test_full_request_yields_five_actions_without_model_or_execution(self):
        with patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("no AI needed"))), \
             patch.object(app, "execute_action", new=AsyncMock(side_effect=AssertionError("no write"))):
            res = await self.client.post("/api/plan", json={
                "guild_id": "1567347687379050727", "mode": "auto", "prompt": FULL_REQUEST,
            }, headers=self.headers)
        self.assertEqual(res.status, 200)
        plan = (await res.json())["plan"]
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(len(plan["actions"]), 5)
        self.assertEqual([a["type"] for a in plan["actions"][-3:]],
                         ["configure_welcome", "configure_farewell", "configure_invites"])


if __name__ == "__main__":
    unittest.main()
