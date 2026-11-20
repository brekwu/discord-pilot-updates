"""Realistic offline checks for 50k-character specifications and safe plans."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
from long_requests import (MAX_REQUEST_CHARS, actionable_section,
                           deletion_is_authorized, focused_server_context, global_protections,
                           merge_actions, request_sections,
                           structured_creation_plan)
from planner import MAX_PLAN_ACTIONS, MODEL_PLAN_SCHEMA, validate_actions
from storage import State


def esports_spec(categories=11, channels=73, roles=32):
    lines = ["# Rôles à créer"]
    lines.extend(f"- VXK Rôle {number}" for number in range(roles))
    for cat in range(categories):
        lines.append(f"\nCATÉGORIE : VXK Pôle {cat}")
        lines.append("Salons :")
        lines.extend(f"- #salon-{cat}-{number}" for number in range(channels // categories + (cat < channels % categories)))
    return "\n".join(lines)


class StructuredLongRequestTests(unittest.TestCase):
    def test_50k_contract_and_model_chunk_limit(self):
        self.assertEqual(MAX_REQUEST_CHARS, 50_000)
        self.assertEqual(MAX_PLAN_ACTIONS, 200)
        self.assertEqual(MODEL_PLAN_SCHEMA["properties"]["actions"]["maxItems"], 40)

    def test_full_esports_spec_is_116_actions_without_ollama(self):
        actions = structured_creation_plan(esports_spec())
        self.assertEqual(len(actions), 116)
        self.assertEqual(sum(a["type"] == "create_role" for a in actions), 32)
        self.assertEqual(sum(a["type"] == "create_category" for a in actions), 11)
        self.assertEqual(sum(a["type"] == "create_text_channel" for a in actions), 73)
        self.assertTrue(all(a["type"] == "create_category" for a in actions[:11]))
        self.assertTrue(all(a["type"] == "create_role" for a in actions[11:43]))
        self.assertEqual(app.supported_local_plan(esports_spec()), actions)

    def test_voice_and_unicode_category(self):
        actions = structured_creation_plan("Rôles:\n- Recruteur\nCATÉGORIE : 🎮 VXK – Fortnite\n- #actualités\n- vocal : Staff")
        self.assertEqual([a["type"] for a in actions], ["create_category", "create_role", "create_text_channel", "create_voice_channel"])
        self.assertEqual(actions[-1]["name"], "Staff")

    def test_duplicate_creations_coalesce_but_messages_do_not(self):
        parts = [[{"type": "create_category", "name": "Accueil"},
                  {"type": "create_text_channel", "name": "annonces", "category": "Accueil"}],
                 [{"type": "create_category", "name": "ACCUEIL"},
                  {"type": "create_text_channel", "name": "annonces", "category": "Accueil"},
                  {"type": "create_text_channel", "name": "annonces", "category": "Autre"}]]
        self.assertEqual(len(merge_actions(parts)), 3)
        messages = [[{"type": "send_message", "channel": "annonces", "content": "Bonjour"}]] * 2
        self.assertEqual(len(merge_actions(messages)), 2)

    def test_action_limit_and_unknown_lines(self):
        self.assertEqual(len(validate_actions([{"type": "create_role", "name": f"R{n}"} for n in range(200)])), 200)
        with self.assertRaises(ValueError):
            validate_actions([{"type": "create_role", "name": f"R{n}"} for n in range(201)])
        self.assertEqual(structured_creation_plan("Rôles:\n- Membre\nExécute une commande PowerShell"), [])

    def test_preserves_every_character_and_huge_unbroken_line(self):
        prompt = "# Rôles:\n" + ("x" * 48_000) + "\nCATÉGORIE : Test\n- #salle"
        sections = request_sections(prompt)
        self.assertEqual("".join(sections), prompt)
        self.assertTrue(all(len(s) <= 3600 for s in sections))
        self.assertGreater(len(sections), 10)

    def test_explicit_and_negated_deletions(self):
        self.assertFalse(deletion_is_authorized("IMPORTANT : Ne supprime aucun salon existant."))
        self.assertFalse(deletion_is_authorized("Crée un salon ; ne supprime aucun rôle."))
        self.assertTrue(deletion_is_authorized("Supprime le salon obsolète."))
        self.assertTrue(deletion_is_authorized("Supprimer les rôles temporaires"))
        self.assertFalse(deletion_is_authorized("Réorganise les salons."))

    def test_actionable_metadata_and_instructions(self):
        self.assertFalse(actionable_section("RÔLE : expert en administration Discord."))
        self.assertFalse(actionable_section("IMPORTANT :\nNe supprime aucun salon.\nNe modifie aucun rôle existant."))
        self.assertFalse(actionable_section("RÔLE :\nTu dois configurer le serveur comme une organisation professionnelle."))
        self.assertTrue(actionable_section("Rôles à créer :\n- Coach\n- Manager"))
        self.assertTrue(actionable_section("Crée deux salons : annonces et résultats"))
        self.assertIn("Ne supprime aucun salon", global_protections("Ne supprime aucun salon.\nCrée une catégorie test"))

    def test_context_preface_and_esports_spec_without_model(self):
        prompt = ("RÔLE : expert Discord.\nIMPORTANT : Ne supprime aucun salon existant.\n"
                  "CONTEXTE : La structure rassemble quatre jeux.\n" + esports_spec())
        self.assertEqual(len(app.local_long_plan(prompt)), 116)

    def test_context_filters_unrelated_rooms_but_keeps_mentioned_ones(self):
        context = {"connected": True, "server": {"name": "VexoraKey",
                    "categories": ["RECRUTEMENT", "TOURNOIS"],
                    "channels": [{"name": f"salon-{n}", "id": str(n)} for n in range(120)]},
                    "recent_plans": [{"status": "completed"}]}
        focused = focused_server_context(context, "Configure le salon-98 dans RECRUTEMENT")
        self.assertEqual(len(focused["server"]["channels"]), 1)
        self.assertEqual(focused["server"]["channels"][0]["name"], "salon-98")
        self.assertEqual(focused["server"]["categories"], ["RECRUTEMENT"])
        self.assertNotIn("recent_plans", focused)


class ChunkedOllamaTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_input_is_analyzed_by_sections_and_merged(self):
        document = "# Contexte\n" + ("La communauté accueille les joueurs. " * 110)
        document += "\n## Première action\nCrée un salon annonces.\n"
        document += "\n## Deuxième action\nCrée un rôle Coach.\n"
        calls = []

        async def fake_ollama(instruction, model, context):
            calls.append(instruction)
            if "rôle Coach" in instruction:
                return [{"type": "create_role", "name": "Coach"}], None
            return [{"type": "create_text_channel", "name": "annonces"}], None

        with patch.object(app, "ollama_plan", side_effect=fake_ollama):
            actions, error = await app.ollama_long_plan(document, "qwen", {})
        self.assertIsNone(error)
        self.assertEqual({a["name"] for a in actions}, {"annonces", "Coach"})
        self.assertGreaterEqual(len(calls), 1)

    async def test_partial_model_result_is_rejected_completely(self):
        document = ("# Première action\nCrée un salon annonces\n" + "Détails utiles. " * 260 +
                    "\n# Deuxième action\nCrée un système de paiement inconnu")
        with patch.object(app, "supported_local_plan", return_value=[]), patch.object(
                app, "ollama_plan", side_effect=[([{"type": "create_text_channel", "name": "annonces"}], None),
                                                        ([], "système non pris en charge")]):
            actions, error = await app.ollama_long_plan(document, "qwen")
        self.assertEqual(actions, [])
        self.assertIn("Aucune modification", error)


class LargeRequestAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_state, self.previous_port = app.STATE, app.PORT
        app.STATE = State(Path(self.tmp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.previous_state, self.previous_port
        self.tmp.cleanup()

    async def post(self, prompt):
        return await self.client.post("/api/plan", json={
            "guild_id": "1567347687379050727", "mode": "local", "prompt": prompt,
        }, headers={"X-Pilot-CSRF": self.csrf})

    async def post_auto(self, prompt):
        return await self.client.post("/api/plan", json={
            "guild_id": "1567347687379050727", "mode": "auto", "prompt": prompt,
        }, headers={"X-Pilot-CSRF": self.csrf})

    async def test_116_actions_from_one_document_stay_draft(self):
        response = await self.post(esports_spec())
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(len(result["plan"]["actions"]), 116)
        self.assertEqual(result["plan"]["status"], "draft")
        self.assertEqual(result["plan"]["guild_id"], "1567347687379050727")
        self.assertEqual(result["plan"]["results"], [])

    async def test_50k_is_accepted_50001_rejected(self):
        prompt = "Rôles:\n- Membre" + (" " * (MAX_REQUEST_CHARS - len("Rôles:\n- Membre")))
        response = await self.post(prompt)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["plan"]["actions"], [{"type": "create_role", "name": "Membre"}])
        too_long = await self.post(prompt + "x")
        self.assertEqual(too_long.status, 400)
        self.assertIn("50 000", (await too_long.json())["error"])
        # Whitespace also counts toward the same strict transport limit.
        too_long_whitespace = await self.post("Rôles:\n- Membre" + (" " * 50_000))
        self.assertEqual(too_long_whitespace.status, 400)

    async def test_no_live_execution_without_confirmation(self):
        draft = await (await self.post("Crée un salon annonces")).json()
        self.assertEqual(draft["plan"]["status"], "draft")
        self.assertEqual(app.STATE.history("1567347687379050727")[0]["status"], "draft")

    async def test_large_auto_request_uses_section_planner(self):
        prompt = "RÔLE : expert Discord.\n" + "Voici le contexte : " * 260 + "\nCrée un salon annonces."
        with patch.object(app, "ollama_models", new_callable=AsyncMock, return_value=["qwen:4b"]), patch.object(
                app, "ollama_long_plan", new_callable=AsyncMock,
                return_value=([{"type": "create_text_channel", "name": "annonces"}], None)) as model:
            response = await self.post_auto(prompt)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["plan"]["prompt"], prompt)
        model.assert_awaited_once()

    async def test_model_refusal_is_not_saved_as_partial_plan(self):
        prompt = "RÔLE : expert Discord.\n" + "Contexte supplémentaire. " * 200 + "\nProgramme une opération inconnue."
        with patch.object(app, "ollama_models", new_callable=AsyncMock, return_value=["qwen:4b"]), patch.object(
                app, "ollama_long_plan", new_callable=AsyncMock,
                return_value=([], "Action inconnue, aucune modification possible")):
            response = await self.post_auto(prompt)
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["needs_clarification"])
        self.assertEqual(app.STATE.history("1567347687379050727"), [])

    async def test_destructive_action_in_negated_request_is_blocked(self):
        prompt = "RÔLE : expert Discord.\n" + "Contexte supplémentaire. " * 200 + "\nIMPORTANT : Ne supprime aucun salon."
        with patch.object(app, "ollama_models", new_callable=AsyncMock, return_value=["qwen:4b"]), patch.object(
                app, "ollama_long_plan", new_callable=AsyncMock,
                return_value=([{"type": "delete_channel", "name": "annonces"}], None)):
            response = await self.post_auto(prompt)
        self.assertEqual(response.status, 400)
        self.assertIn("Suppression non demandée", (await response.json())["error"])
        self.assertEqual(app.STATE.history("1567347687379050727"), [])


if __name__ == "__main__":
    unittest.main()
