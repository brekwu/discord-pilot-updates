"""P4: compound natural-language workflows and real-discord smoke diagnostics."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import app
import discord
import discord_ops
from aiohttp.test_utils import TestClient, TestServer
from conversational_workflows import (batch_module_plan, guided_workflow_plan,
                                      server_preset_plan, workflow_clauses)
from discord_diagnostics import inspect_guild
from storage import State
from test_p2_planner import FakeCategory, FakeGuild, FakeRole, GID
from test_p3_panels import PanelText


TICKETS_PROMPT = ("Crée une catégorie SUPPORT et un salon tickets dans la catégorie SUPPORT "
                  "et un rôle Support puis active les tickets et publie le panneau des tickets")
APPLICATIONS_PROMPT = (
    "Crée une catégorie RECRUTEMENT et un salon candidatures dans la catégorie RECRUTEMENT "
    "et un salon validation dans la catégorie RECRUTEMENT et un rôle RH "
    "puis rends le salon validation privé pour le rôle RH "
    "puis active les candidatures et publie le formulaire des candidatures")


class P4PlanningTests(unittest.TestCase):
    def test_ticket_workflow_from_one_normal_french_request(self):
        actions = app.supported_local_plan(TICKETS_PROMPT)
        self.assertEqual([a["type"] for a in actions], [
            "create_category", "create_text_channel", "create_role",
            "configure_module", "publish_ticket_panel"])
        self.assertEqual(actions[3]["panel_channel_id"], "tickets")
        self.assertEqual(actions[3]["category_id"], "SUPPORT")
        self.assertEqual(actions[3]["staff_role_id"], "Support")

    def test_application_workflow_protects_staff_review_room(self):
        actions = app.supported_local_plan(APPLICATIONS_PROMPT)
        self.assertEqual([a["type"] for a in actions][-3:], [
            "make_private", "configure_module", "publish_application_panel"])
        self.assertEqual(actions[-2]["staff_channel_id"], "validation")
        self.assertEqual(actions[-2]["panel_channel_id"], "candidatures")

    def test_no_implicit_private_channel_or_unrequested_features(self):
        self.assertEqual(guided_workflow_plan(
            "Crée un salon candidatures puis active les candidatures"), [])
        self.assertEqual(guided_workflow_plan(
            "Crée une catégorie SUPPORT et un salon tickets dans SUPPORT puis active les tickets et programme une radio"), [])
        self.assertEqual(guided_workflow_plan("Active les tickets"), [])

    def test_exact_multi_module_activation_and_templates(self):
        actions = batch_module_plan("Active XP, antispam et anti liens")
        self.assertEqual([a["module"] for a in actions], ["xp", "antispam", "antilinks"])
        self.assertTrue(all(a["enabled"] == "true" for a in actions))
        self.assertEqual([a["enabled"] for a in batch_module_plan("Désactive XP et antispam")],
                         ["false", "false"])
        self.assertEqual(batch_module_plan("Active XP, les cadeaux et antispam"), [])
        self.assertEqual(server_preset_plan("Crée un serveur tournoi"), app.PRESETS["tournoi"]["actions"])
        self.assertEqual(server_preset_plan("Crée un serveur pour tous"), [])

    def test_vexora_esport_preset_is_complete_and_strictly_additive(self):
        plan = app.PRESETS["vexora-esport"]["actions"]
        self.assertEqual(len(plan), 56)
        self.assertEqual(sum(a["type"] == "create_category" for a in plan), 6)
        self.assertEqual(sum(a["type"] == "create_text_channel" for a in plan), 28)
        self.assertEqual(sum(a["type"] == "create_role" for a in plan), 22)
        self.assertEqual(set(a["type"] for a in plan),
                         {"create_category", "create_text_channel", "create_role"})
        self.assertNotIn("configure_module", [a["type"] for a in plan])
        self.assertNotIn("publish_ticket_panel", [a["type"] for a in plan])
        self.assertNotIn("make_private", [a["type"] for a in plan])
        self.assertEqual(len({(a["type"], a["name"], a.get("category")) for a in plan}),
                         len(plan))
        role_names = {a["name"] for a in plan if a["type"] == "create_role"}
        self.assertIn("Manager Esport", role_names)
        self.assertIn("Recruteur Esport", role_names)
        self.assertIn("Roster Clash of Clans", role_names)
        for game, slug, category in (
            ("Rocket League", "rocket-league", "ROCKET LEAGUE"),
            ("Valorant", "valorant", "VALORANT"),
            ("Fortnite", "fortnite", "FORTNITE"),
            ("Clash of Clans", "clash-of-clans", "CLASH OF CLANS"),
        ):
            self.assertTrue({"Manager " + game, "Joueur " + game,
                             "Coach " + game, "Capitaine " + game} <= role_names)
            channels = {a["name"] for a in plan
                        if a["type"] == "create_text_channel"
                        and a.get("category") == category}
            self.assertEqual(channels, {
                f"{kind}-{slug}" for kind in (
                    "roster", "discussion", "strategie", "resultats",
                    "matchs-a-venir", "actualites")})
        # Generic esports tournament templates are left unchanged.
        self.assertEqual(server_preset_plan("Crée un serveur esport"),
                         app.PRESETS["tournoi"]["actions"])
        for phrase in ("Crée une structure Vexora Esport",
                       "Crée un serveur Vexora e-sport",
                       "Prépare le modèle pour Vexora Esports"):
            self.assertEqual(server_preset_plan(phrase), plan)
            self.assertEqual(app.supported_local_plan(phrase), plan)
        for phrase in ("Crée un serveur Vexora Community",
                       "Supprime les salons Vexora Esport",
                       "Configure tous les serveurs Vexora"):
            self.assertEqual(server_preset_plan(phrase), [])

    def test_quoted_message_is_not_split_by_conjunctions(self):
        clauses = workflow_clauses('Crée un salon annonces et publie "Bonjour, et bienvenue" dans annonces')
        self.assertEqual(clauses, ["Crée un salon annonces", 'publie "Bonjour, et bienvenue" dans annonces'])


class P4ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_ticket_actions_against_discord_mocks(self):
        guild = FakeGuild(existing=False)
        guild.channel = PanelText("tickets")
        guild.create_text_channel.return_value = guild.channel
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            actions = app.supported_local_plan(TICKETS_PROMPT)
            plan = state.add(str(GID), TICKETS_PROMPT, actions, "local")
            with patch.object(app, "STATE", state), \
                 patch.object(discord_ops.discord, "TextChannel", PanelText), \
                 patch.object(app.MANAGER, "activate_automations", new_callable=AsyncMock):
                await app.run_plan(plan, guild)
            self.assertEqual(plan["status"], "completed", plan["results"])
            self.assertEqual(len(guild.channel.sent), 1)
            self.assertTrue(state.module(str(GID), "tickets")["enabled"])

    async def test_real_application_actions_and_private_room_against_discord_mocks(self):
        guild = FakeGuild(existing=False)
        guild.role = FakeRole("RH")
        guild.create_role.return_value = guild.role
        guild.category = FakeCategory("RECRUTEMENT")
        created_channels = {}

        async def create_channel(name, **kwargs):
            channel = PanelText(name, 223456789012345678 + len(created_channels) + 1)
            channel.category_id = guild.category.id
            created_channels[name] = channel
            return channel

        guild.create_text_channel.side_effect = create_channel
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            actions = app.supported_local_plan(APPLICATIONS_PROMPT)
            plan = state.add(str(GID), APPLICATIONS_PROMPT, actions, "local")
            with patch.object(app, "STATE", state), \
                 patch.object(discord_ops.discord, "TextChannel", PanelText), \
                 patch.object(app.MANAGER, "activate_automations", new_callable=AsyncMock):
                await app.run_plan(plan, guild)
            self.assertEqual(plan["status"], "completed", plan["results"])
            self.assertTrue(created_channels["validation"].private)
            self.assertEqual(len(created_channels["candidatures"].sent), 1)
            self.assertEqual(state.module(str(GID), "applications")["staff_channel_id"],
                             str(created_channels["validation"].id))


class P4LiveDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def make_guild(self):
        guild = SimpleNamespace()
        guild.id = GID
        guild.name = "Serveur de test"
        guild.default_role = FakeRole("@everyone", GID, default=True)
        guild.me = FakeRole("Discord Pilot", 323456789012345679)
        guild.me.guild_permissions = SimpleNamespace(manage_channels=True, send_messages=True)
        guild.fetch_channels = AsyncMock(return_value=[SimpleNamespace(id=1)])
        guild.fetch_roles = AsyncMock(return_value=[SimpleNamespace(id=2)])
        guild.create_text_channel = AsyncMock()
        return guild

    async def test_read_only_fetches_remote_state_and_does_not_mutate(self):
        guild = self.make_guild()
        result = await inspect_guild(guild)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["mode"], "read_only")
        guild.create_text_channel.assert_not_awaited()


    async def test_active_test_creates_checks_then_removes_only_temporary_channel(self):
        guild = self.make_guild()
        temporary = PanelText("discordpilot-test")
        temporary.delete = AsyncMock()
        guild.create_text_channel.return_value = temporary
        result = await inspect_guild(guild, active=True)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual([item["ok"] for item in result["checks"]], [True] * 6)
        self.assertEqual(len(temporary.sent), 1)
        guild.create_text_channel.assert_awaited_once()
        private_overwrite = guild.create_text_channel.await_args.kwargs["overwrites"][guild.default_role]
        self.assertIs(private_overwrite.view_channel, False)
        temporary.delete.assert_awaited_once()

    async def test_failed_cleanup_is_clearly_reported_with_channel_id(self):
        guild = self.make_guild()
        temporary = PanelText("discordpilot-test")
        temporary.delete = AsyncMock(side_effect=OSError("simulation suppression impossible"))
        guild.create_text_channel.return_value = temporary
        result = await inspect_guild(guild, active=True)
        self.assertEqual(result["status"], "failed")
        self.assertIn(str(temporary.id), result["checks"][-1]["detail"])

    async def test_no_active_mutation_without_required_permissions(self):
        guild = self.make_guild()
        guild.me.guild_permissions.manage_channels = False
        result = await inspect_guild(guild, active=True)
        self.assertEqual(result["status"], "blocked")
        guild.create_text_channel.assert_not_awaited()


class P4ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_state, self.original_port = app.STATE, app.PORT
        app.STATE = State(Path(self.temp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.original_state, self.original_port
        self.temp.cleanup()

    async def test_compound_prompt_returns_reviewable_draft_without_model(self):
        with patch.object(app, "ollama_models", new=AsyncMock(
                 side_effect=AssertionError("Ollama should not be needed"))):
            response = await self.client.post("/api/plan", json={
                "guild_id": str(GID), "mode": "auto", "prompt": TICKETS_PROMPT
            }, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["plan"]["status"], "draft")
        self.assertEqual(len(body["plan"]["actions"]), 5)
        self.assertEqual(body["plan"]["actions"][-1]["type"], "publish_ticket_panel")

    async def test_vexora_esport_preset_is_a_draft_until_confirmation(self):
        response = await self.client.post("/api/preset", json={
            "guild_id": str(GID), "preset_id": "vexora-esport",
        }, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["plan"]["status"], "draft")
        self.assertEqual(len(body["plan"]["actions"]), 56)
        self.assertEqual(len(app.STATE.history(str(GID))), 1)
        # Preparing a reviewable draft never invokes Discord.
        response = await self.client.post("/api/preset", json={
            "guild_id": str(GID), "preset_id": "vexora-esport",
        })
        self.assertEqual(response.status, 403)

    async def test_real_diagnostic_refuses_disconnected_bot(self):
        with patch.object(app.MANAGER, "get_guild", return_value=None):
            response = await self.client.post("/api/live-test", json={
                "guild_id": str(GID), "mode": "active"
            }, headers={"X-Pilot-CSRF": self.csrf})
        self.assertEqual(response.status, 400)
        self.assertIn("Bot non connecté", (await response.json())["error"])

    async def test_live_diagnostic_requires_csrf(self):
        response = await self.client.post("/api/live-test", json={
            "guild_id": str(GID), "mode": "active"
        })
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
