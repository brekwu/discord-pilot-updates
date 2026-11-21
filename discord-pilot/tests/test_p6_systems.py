"""Regression coverage for complete button workflows and read-back verification."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from system_recipes import recipe_plan, recipe_kind
from plan_verification import verify_plan


class SystemRecipesTests(unittest.TestCase):
    def test_ticket_system_is_complete_and_ordered(self):
        prompt = ("Crée un système complet de tickets avec bouton. "
                  "Salon du panneau : #assistance, catégorie : TICKETS, rôle staff : Support.")
        actions, question = recipe_plan(prompt)
        self.assertIsNone(question)
        self.assertEqual([a["type"] for a in actions],
                         ["create_category", "create_role", "create_text_channel",
                          "configure_module", "publish_ticket_panel"])
        self.assertEqual(actions[3]["staff_role_id"], "Support")

    def test_recruitment_has_atomic_private_review_room(self):
        prompt = ("Mets en place un système complet de candidatures avec bouton. "
                  "Salon du panneau : #postuler, salon de suivi : #suivi-staff, "
                  "rôle staff : Recruteur, catégorie : RECRUTEMENT.")
        actions, question = recipe_plan(prompt)
        self.assertIsNone(question)
        self.assertEqual([a["type"] for a in actions],
                         ["create_category", "create_role", "create_text_channel",
                          "create_private_text_channel", "configure_module", "publish_application_panel"])
        self.assertEqual(actions[3]["role"], "Recruteur")
        self.assertEqual(actions[4]["staff_channel_id"], "suivi-staff")

    def test_no_guessing_without_named_resources(self):
        actions, question = recipe_plan("Crée un système de tickets avec bouton")
        self.assertEqual(actions, [])
        self.assertIn("salon du panneau", question)

    def test_reject_public_and_private_room_collision(self):
        actions, question = recipe_plan(
            "Crée un système complet de recrutement avec bouton. "
            "Salon du panneau : #postuler, salon de suivi : #postuler, rôle staff : Recruteur.")
        self.assertEqual(actions, [])
        self.assertIn("différents", question)

    def test_generic_commands_go_through_existing_planner(self):
        self.assertIsNone(recipe_kind("Crée un salon actualités et un rôle Support"))
        self.assertIsNone(recipe_plan("Crée un salon actualités et un rôle Support"))


class FakeGuild:
    id = 123456789012345678
    def __init__(self, channels, roles):
        self._channels = channels
        self._roles = roles
        self.fetch_channels = AsyncMock(return_value=channels)
        self.fetch_roles = AsyncMock(return_value=roles)
        self.default_role = roles[0]


class FakeState:
    def __init__(self):
        self.state = {"ticket_panels": {}, "application_panels": {}}
    def module(self, gid, name):
        return {"enabled": True}
    def automation_channel(self, gid, name):
        return None


class PlanVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_creation_is_verified_from_fresh_guild_reads(self):
        category = SimpleNamespace(id=20, name="TICKETS", type="category")
        channel = SimpleNamespace(id=21, name="assistance", type="text", category_id=20)
        everyone = SimpleNamespace(id=10, name="@everyone")
        staff = SimpleNamespace(id=11, name="Support")
        guild = FakeGuild([category, channel], [everyone, staff])
        actions = [{"type":"create_category","name":"TICKETS"},
                   {"type":"create_role","name":"Support"},
                   {"type":"create_text_channel","name":"assistance","category":"TICKETS"}]
        plan = {"actions":actions, "results":[{"index":i,"status":"done","detail":"OK"}
                                            for i in range(3)]}
        result = await verify_plan(guild, plan, FakeState())
        self.assertEqual(result["verified"], 3)
        self.assertEqual(result["mismatch"], 0)
        guild.fetch_channels.assert_awaited_once()
        guild.fetch_roles.assert_awaited_once()

    async def test_missing_room_is_reported_as_mismatch_not_success(self):
        guild = FakeGuild([], [])
        plan = {"actions":[{"type":"create_text_channel","name":"inexistant"}],
                "results":[{"index":0,"status":"done","detail":"Création HTTP 200"}]}
        result = await verify_plan(guild, plan, FakeState())
        self.assertEqual(result["mismatch"], 1)
        self.assertEqual(plan["results"][0]["verification"]["status"], "mismatch")

    async def test_discord_read_failure_is_unverified(self):
        guild = FakeGuild([], [])
        guild.fetch_channels = AsyncMock(side_effect=RuntimeError("API down"))
        plan = {"actions":[{"type":"create_text_channel","name":"test"}],
                "results":[{"index":0,"status":"done","detail":"Créé"}]}
        result = await verify_plan(guild, plan, FakeState())
        self.assertEqual(result["unverified"], 1)
        self.assertEqual(result["verified"], 0)

    async def test_module_enabled_is_local_only_for_runtime_behaviour(self):
        guild = FakeGuild([], [])
        plan = {"actions":[{"type":"configure_module","module":"tickets","enabled":"true"}],
                "results":[{"index":0,"status":"done","detail":"Configuré"}]}
        result = await verify_plan(guild, plan, FakeState())
        self.assertEqual(result["local_only"], 1)
        self.assertEqual(result["verified"], 0)


if __name__ == "__main__":
    unittest.main()
