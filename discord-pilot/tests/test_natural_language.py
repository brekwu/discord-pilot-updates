"""Non-destructive regression tests for conversational Discord instructions."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
from planner import (collapse_old_clarifications, default_creation_plan,
                     local_parse, missing_information, parse_ollama_decision)
from storage import State


class LocalLanguageTests(unittest.TestCase):
    def test_rajoute_channel_synonyms(self):
        for phrase in ("Rajoute un channel annonces", "Rajoute-moi un channel nommé annonces",
                       "Ajoute le salon annonces", "Crée un canal annonces"):
            with self.subTest(phrase=phrase):
                self.assertEqual(local_parse(phrase), [{"type": "create_text_channel", "name": "annonces"}])

    def test_voice_channel_and_category(self):
        self.assertEqual(local_parse("Rajoute un channel vocal Général dans la catégorie COMMUNAUTÉ"),
                         [{"type": "create_voice_channel", "name": "Général", "category": "COMMUNAUTÉ"}])

    def test_conversational_french_directly_creates_complete_drafts(self):
        examples = (
            "Je veux créer deux salons bienvenue et au revoir",
            "Crée deux salons bienvenue et au revoir",
            "J’aimerais créer deux salons bienvenue et au revoir",
            "Tu peux me créer deux salons bienvenue et au revoir ?",
            "Créer deux salons bienvenue et au revoir",
            "Je voudrais que tu crées un salon bienvenue puis un salon au revoir",
        )
        expected = [{"type": "create_text_channel", "name": "bienvenue"},
                    {"type": "create_text_channel", "name": "au revoir"}]
        for utterance in examples:
            with self.subTest(utterance=utterance):
                self.assertEqual(local_parse(utterance), expected)

    def test_natural_voice_and_role_commands(self):
        self.assertEqual(local_parse("Ajoute-moi un vocal Général et un salon annonces"), [
            {"type": "create_voice_channel", "name": "Général"},
            {"type": "create_text_channel", "name": "annonces"},
        ])
        self.assertEqual(local_parse("Je veux un salon textuel pour les annonces"), [
            {"type": "create_text_channel", "name": "annonces"},
        ])
        self.assertEqual(local_parse("Peux-tu créer les rôles Membre et Modérateur ?"), [
            {"type": "create_role", "name": "Membre"},
            {"type": "create_role", "name": "Modérateur"},
        ])

    def test_missing_names_keep_explicit_requested_count_without_clarifications(self):
        self.assertEqual(default_creation_plan("Je veux deux salons"), [
            {"type": "create_text_channel", "name": "nouveau-salon-1"},
            {"type": "create_text_channel", "name": "nouveau-salon-2"},
        ])
        self.assertEqual(local_parse("Crée trois salons bienvenue et annonces"), [
            {"type": "create_text_channel", "name": "bienvenue"},
            {"type": "create_text_channel", "name": "annonces"},
            {"type": "create_text_channel", "name": "nouveau-salon-3"},
        ])

    def test_unsupported_tail_does_not_create_a_partial_plan(self):
        self.assertEqual(local_parse("Je veux créer un salon annonces ; et programme une campagne"), [])

    def test_incomplete_request_has_safe_draft_defaults(self):
        self.assertIn("Quel nom", missing_information("Rajoute un channel"))
        self.assertIn("Quel nom", missing_information("Ajoute un canal dans la catégorie ACCUEIL"))
        self.assertIsNone(missing_information("Ajoute un salon annonces"))
        self.assertEqual(default_creation_plan("Rajoute un channel"),
                         [{"type": "create_text_channel", "name": "nouveau-salon"}])
        self.assertEqual(default_creation_plan("Ajoute un canal dans la catégorie ACCUEIL"),
                         [{"type": "create_text_channel", "name": "nouveau-salon", "category": "ACCUEIL"}])

    def test_old_clarifications_are_ignored_when_request_is_clear(self):
        prompt = "cree un salon bienvenu et au revoir\nPrécision : Bienvenue\nPrécision : au revoir"
        clean = collapse_old_clarifications(prompt)
        self.assertEqual(clean, "cree un salon bienvenu et au revoir")
        self.assertEqual(local_parse(clean), [
            {"type": "create_text_channel", "name": "bienvenu"},
            {"type": "create_text_channel", "name": "au revoir"},
        ])

    def test_old_clarification_can_complete_incomplete_creation(self):
        self.assertEqual(collapse_old_clarifications("Crée un salon\nPrécision : annonces"),
                         "Crée un salon annonces")

    def test_local_model_can_ask_a_question(self):
        actions, question = parse_ollama_decision('{"actions":[],"question":"Quel salon veux-tu créer ?"}')
        self.assertEqual(actions, [])
        self.assertEqual(question, "Quel salon veux-tu créer ?")

    def test_model_response_variants_stay_within_allowlist(self):
        actions, _ = parse_ollama_decision('{"operations":[{"type":"creer_salon_vocal", "name":"Général"}]}')
        self.assertEqual(actions, [{"type": "create_voice_channel", "name": "Général"}])
        actions, _ = parse_ollama_decision('<think>reasoning hidden</think>{"action":"creer_salon","name":"annonces"}')
        self.assertEqual(actions, [{"type": "create_text_channel", "name": "annonces"}])

    def test_model_plan_wrappers_and_single_action_are_supported_safely(self):
        for payload in (
            '{"plan":[{"type":"create_text_channel","name":"annonces"}]}',
            '{"commands":[{"action":"create_channel","name":"annonces"}]}',
            '{"actions":{"type":"create_text_channel","name":"annonces"}}',
            '{"result":{"actions":[{"type":"create_text_channel","name":"annonces"}]}}',
        ):
            with self.subTest(payload=payload):
                actions, question = parse_ollama_decision(payload)
                self.assertIsNone(question)
                self.assertEqual(actions, [{"type": "create_text_channel", "name": "annonces"}])
        for payload in (
            '{"plan":[{"type":"run_shell","cmd":"powershell"}]}',
            '{"actions":[{"type":"create_role","name":"Admin","permissions":"administrator"}]}',
            '{"actions":[{"type":"create_text_channel","name":"annonces"}],'
            '"plan":[{"type":"delete_channel","name":"general"}]}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_ollama_decision(payload)

    def test_no_code_execution(self):
        with self.assertRaises(ValueError):
            parse_ollama_decision('{"actions":[{"type":"run_shell","cmd":"powershell"}]}')

    def test_ai_common_discord_aliases_are_canonicalized(self):
        actions, question = parse_ollama_decision('{"actions":['
            '{"action":"create_channel","channel_name":"bienvenue",'
            '"channel_type":"text","category_name":"ACCUEIL"},'
            '{"type":"add_channel","name":"Général","channel_type":"voice"},'
            '{"type":"add_role","role_name":"Membre"},'
            '{"type":"post_message","channel_name":"annonces","message":"Bonjour !"},'
            '{"type":"private_channel","channel_name":"staff","role_name":"Modérateur"}'
            ']}')
        self.assertIsNone(question)
        self.assertEqual(actions, [
            {"type": "create_text_channel", "name": "bienvenue", "category": "ACCUEIL"},
            {"type": "create_voice_channel", "name": "Général"},
            {"type": "create_role", "name": "Membre"},
            {"type": "send_message", "channel": "annonces", "content": "Bonjour !"},
            {"type": "make_private", "name": "staff", "role": "Modérateur"},
        ])
        camel, _ = parse_ollama_decision('{"actions":['
            '{"action":"createChannel","channelName":"nouveautes",'
            '"channelType":"GUILD_TEXT"},'
            '{"type":"addRole","roleName":"VIP"}'
            ']}')
        self.assertEqual(camel, [
            {"type": "create_text_channel", "name": "nouveautes"},
            {"type": "create_role", "name": "VIP"},
        ])

    def test_unsupported_or_dangerous_model_actions_are_never_approximated(self):
        for payload in (
            '{"actions":[{"type":"create_forum_channel","name":"forum"}]}',
            '{"actions":[{"type":"run_shell","cmd":"powershell"}]}',
            '{"actions":[{"type":"create_role","name":"Admin","permissions":"administrator"}]}',
            '{"actions":[{"type":"create_channel","name":"forum","channel_type":"forum"}]}',
            '{"actions":[{"type":"create_text_channel","name":"staff","channel_type":"voice"}]}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_ollama_decision(payload)


class OllamaRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_automatic_repair_recovers_from_model_hallucination(self):
        class FakeResponse:
            status = 200

            def __init__(self, answer):
                self.answer = answer

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def json(self):
                return {"message": {"content": self.answer}}

        class FakeSession:
            def __init__(self, answers):
                self.answers = list(answers)
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            def post(self, _url, json):
                self.calls.append(json)
                return FakeResponse(self.answers.pop(0))

        first = '{"actions":[{"type":"create_forum_channel","name":"bienvenue"}]}'
        repaired = '{"actions":[{"type":"create_text_channel","name":"bienvenue"}]}'
        fake = FakeSession([first, repaired])
        with patch.object(app.aiohttp, "ClientSession", return_value=fake):
            actions, question = await app.ollama_plan("Crée un salon textuel bienvenue", "qwen-test")
        self.assertEqual(actions, [{"type": "create_text_channel", "name": "bienvenue"}])
        self.assertIsNone(question)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("create_text_channel", fake.calls[1]["messages"][-1]["content"])

        no_actions = FakeSession(['{"actions":[]}', repaired])
        with patch.object(app.aiohttp, "ClientSession", return_value=no_actions):
            recovered, _ = await app.ollama_plan("Je voudrais créer un salon bienvenue", "qwen-test")
        self.assertEqual(recovered, [{"type": "create_text_channel", "name": "bienvenue"}])
        self.assertEqual(len(no_actions.calls), 2)

        invalid = FakeSession([first, first])
        with patch.object(app.aiohttp, "ClientSession", return_value=invalid):
            with self.assertRaisesRegex(ValueError, "plan vérifiable"):
                await app.ollama_plan("Crée un salon textuel bienvenue", "qwen-test")

        empty = FakeSession(['{"actions":[]}', '{"actions":[]}'])
        with patch.object(app.aiohttp, "ClientSession", return_value=empty):
            with self.assertRaisesRegex(ValueError, "Modules actifs"):
                await app.ollama_plan("Configure les récompenses avec des détails manquants", "qwen-test")


class ApiLanguageTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_incomplete_create_proposes_draft_without_questions(self):
        res = await self.client.post("/api/plan", json={"guild_id": "1567347687379050727",
                                                        "mode": "auto", "prompt": "Rajoute un channel"}, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertNotIn("needs_clarification", body)
        self.assertEqual(body["plan"]["actions"], [{"type": "create_text_channel", "name": "nouveau-salon"}])
        self.assertEqual(body["plan"]["status"], "draft")

    async def test_screenshot_request_creates_two_channels_directly_with_model_available(self):
        prompt = "cree un salon bienvenu et au revoir\nPrécision : Bienvenue\nPrécision : au revoir"
        with patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("not needed"))), \
             patch.object(app, "ollama_plan", new=AsyncMock(side_effect=AssertionError("not needed"))):
            res = await self.client.post("/api/plan", json={
                "guild_id": "1567347687379050727", "mode": "auto", "prompt": prompt
            }, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertEqual(body["plan"]["actions"], [
            {"type": "create_text_channel", "name": "bienvenu"},
            {"type": "create_text_channel", "name": "au revoir"},
        ])
        self.assertEqual(body["plan"]["prompt"], "cree un salon bienvenu et au revoir")

    async def test_ai_questions_cannot_loop_back_into_clarification_modals(self):
        prompt = {"guild_id": "1567347687379050727", "mode": "ollama",
                  "prompt": "Réorganise les conversations à ta convenance"}
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=([], "Quel salon ?"))):
            res = await self.client.post("/api/plan", json=prompt, headers=self.headers)
        self.assertEqual(res.status, 400)
        self.assertNotIn("needs_clarification", await res.text())

    async def test_local_explicit_request_creates_draft(self):
        res = await self.client.post("/api/plan", json={"guild_id": "1567347687379050727",
                                                        "mode": "local", "prompt": "Rajoute un channel annonces"}, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertEqual(body["plan"]["status"], "draft")
        self.assertEqual(body["plan"]["actions"], [{"type": "create_text_channel", "name": "annonces"}])

    async def test_conversational_request_skips_model_and_creates_both_channels(self):
        with patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("not needed"))):
            res = await self.client.post("/api/plan", json={
                "guild_id": "1567347687379050727", "mode": "auto",
                "prompt": "Je veux créer deux salons bienvenue et au revoir",
            }, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertEqual(body["plan"]["actions"], [
            {"type": "create_text_channel", "name": "bienvenue"},
            {"type": "create_text_channel", "name": "au revoir"},
        ])

    async def test_enable_activity_stats_without_ai_or_guessing_other_features(self):
        with patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("not needed"))):
            result = await self.client.post("/api/plan", json={
                "guild_id": "1567347687379050727", "mode": "auto",
                "prompt": "Active les statistiques des messages",
            }, headers=self.headers)
        self.assertEqual(result.status, 200)
        self.assertEqual((await result.json())["plan"]["actions"], [
            {"type": "set_module", "module": "activity_stats", "enabled": "true"},
        ])

    async def test_ai_cannot_invent_deletion(self):
        prompt = {"guild_id": "1567347687379050727", "mode": "ollama", "prompt": "Arrange les salons"}
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=([{"type": "delete_channel", "name": "annonces"}], None))):
            res = await self.client.post("/api/plan", json=prompt, headers=self.headers)
        self.assertEqual(res.status, 400)
        self.assertEqual(app.STATE.history("1567347687379050727"), [])


if __name__ == "__main__":
    unittest.main()
