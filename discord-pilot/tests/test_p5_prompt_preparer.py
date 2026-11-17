"""P5: conversational prompt preparation cannot invent access changes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
import discord_ops
from prompt_preparer import prepare_prompt
from storage import State
from test_p2_planner import FakeChannel, FakeGuild, GID


ORIGINAL = (
    "modifie les rôles pour les salons au revoir, bienvenue, invitation "
    "pour pas que tout le monde puisse écrire dedans"
)


class PromptPreparerTests(unittest.TestCase):
    def test_multi_channel_deny_is_explicit_and_only_modifies_writing(self):
        result = prepare_prompt(ORIGINAL)
        self.assertTrue(result["changed"])
        self.assertEqual(result["rewritten"],
                         "Interdis au rôle @everyone d'écrire dans le salon au revoir;\n"
                         "Interdis au rôle @everyone d'écrire dans le salon bienvenue;\n"
                         "Interdis au rôle @everyone d'écrire dans le salon invitation")
        actions = app.supported_local_plan(result["rewritten"])
        self.assertEqual([action["channel"] for action in actions],
                         ["au revoir", "bienvenue", "invitation"])
        self.assertTrue(all(action["type"] == "set_role_access" and
                            action["role"] == "@everyone" and
                            action["view"] == "keep" and action["participate"] == "deny"
                            for action in actions))

    def test_other_clear_phrasings_and_deduplication(self):
        samples = (
            "Empêche tout le monde d’écrire dans les salons bienvenue et annonces",
            "configure les salons bienvenue, annonces pour que tout le monde ne puisse pas écrire dedans",
            "modifie les salons bienvenue, annonces afin que personne ne puisse écrire",
            "modifie les salons bienvenue, bienvenue, annonces pour pas que @everyone puisse écrire dedans",
        )
        for value in samples:
            with self.subTest(value=value):
                result = prepare_prompt(value)
                self.assertTrue(result["changed"])
                self.assertEqual([a["channel"] for a in app.supported_local_plan(result["rewritten"])],
                                 ["bienvenue", "annonces"])

    def test_ambiguous_or_extra_request_is_never_rewritten(self):
        samples = (
            "modifie les rôles pour les salons au revoir, bienvenue pour que tout le monde puisse écrire dedans",
            "modifie les rôles pour les salons au revoir et bienvenue pour que les modérateurs puissent écrire",
            "modifie les rôles pour les salons au revoir et bienvenue pour pas que tout le monde puisse écrire dedans puis supprime le salon général",
            "empêche pas tout le monde d'écrire dans les salons bienvenue et annonces",
            "configure les permissions des salons",
            "modifie les salons bienvenue, annonces pour pas que tout le monde puisse écrire dedans; et donne les permissions admin",
            "modifie les salons bienvenue, annonces pour pas que tout le monde puisse écrire dedans et donne accès au staff",
        )
        for value in samples:
            with self.subTest(value=value):
                result = prepare_prompt(value)
                self.assertFalse(result["changed"])
                self.assertEqual(result["rewritten"], value)


class PromptPreparerApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.old_state, self.old_port = app.STATE, app.PORT
        app.STATE = State(Path(self.temporary.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        boot = await self.client.get("/api/bootstrap")
        self.headers = {"X-Pilot-CSRF": (await boot.json())["csrf"]}

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.old_state, self.old_port
        self.temporary.cleanup()

    async def test_rewrite_preview_creates_no_plan_or_discord_calls(self):
        blocked = await self.client.post("/api/rewrite", json={"prompt": ORIGINAL})
        self.assertEqual(blocked.status, 403)
        result = await self.client.post("/api/rewrite", json={"prompt": ORIGINAL}, headers=self.headers)
        self.assertEqual(result.status, 200)
        data = await result.json()
        self.assertTrue(data["changed"])
        self.assertIn("@everyone", data["rewritten"])
        self.assertEqual(app.STATE.history(str(GID)), [])

    async def test_ollama_rewrite_is_only_a_suggestion_not_a_saved_plan(self):
        prompt = "Fais des annonces d'accueil bien organisées"
        with patch.object(app, "ollama_models", new_callable=AsyncMock, return_value=["local:latest"]), \
             patch.object(app, "ollama_rewrite", new_callable=AsyncMock,
                          return_value="Configure un accueil sur le serveur") as proposed:
            result = await self.client.post("/api/rewrite", json={"prompt": prompt, "mode": "auto"},
                                            headers=self.headers)
        self.assertEqual(result.status, 200)
        data = await result.json()
        self.assertTrue(data["changed"])
        self.assertIn("IA locale Ollama", data["source"])
        self.assertEqual(data["rewritten"], "Configure un accueil sur le serveur")
        proposed.assert_awaited_once_with(prompt, "local:latest")
        self.assertEqual(app.STATE.history(str(GID)), [])

    async def test_local_rewrite_never_calls_ai(self):
        with patch.object(app, "ollama_models", new_callable=AsyncMock) as models:
            response = await self.client.post("/api/rewrite", json={"prompt": ORIGINAL, "mode": "auto"},
                                              headers=self.headers)
            self.assertEqual(response.status, 200)
            models.assert_not_awaited()

    async def test_real_plan_endpoint_only_creates_a_draft(self):
        result = await self.client.post("/api/plan", json={"guild_id": str(GID),
                "mode": "local", "prompt": ORIGINAL}, headers=self.headers)
        self.assertEqual(result.status, 200)
        plan = (await result.json())["plan"]
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(plan["prompt"], ORIGINAL)
        self.assertIn("@everyone", plan["interpreted_prompt"])
        self.assertEqual(len(plan["actions"]), 3)
        self.assertEqual({a["view"] for a in plan["actions"]}, {"keep"})
        self.assertEqual({a["participate"] for a in plan["actions"]}, {"deny"})
        self.assertEqual(len(app.STATE.history(str(GID))), 1)

    async def test_other_channels_and_permissions_are_untouched_on_execution(self):
        """Exercise the real allowlisted operation against a simulated guild."""
        guild = FakeGuild(existing=True)
        guild.channels = [FakeChannel(name, GID + number + 100)
                          for number, name in enumerate(("au-revoir", "bienvenue", "invitation", "général"))]
        commands = app.supported_local_plan(prepare_prompt(ORIGINAL)["rewritten"])
        with patch.object(discord_ops.discord, "TextChannel", FakeChannel):
            for command in commands:
                status, _ = await discord_ops.execute_action(guild, command)
                self.assertEqual(status, "done")
        for channel in guild.channels[:3]:
            channel.set_permissions.assert_awaited_once()
            args, kwargs = channel.set_permissions.await_args
            self.assertIs(args[0], guild.default_role)
            self.assertIs(kwargs["overwrite"].send_messages, False)
            self.assertIsNone(kwargs["overwrite"].view_channel)
        guild.channels[3].set_permissions.assert_not_awaited()

