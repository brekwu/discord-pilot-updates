"""Non-destructive regression tests for conversational Discord instructions."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
from planner import (MODEL_PLAN_SCHEMA, collapse_old_clarifications, default_creation_plan,
                     channel_role_configuration_request, local_parse,
                     missing_information, parse_ollama_decision, validate_actions)
from storage import State


class LocalLanguageTests(unittest.TestCase):
    def test_ambiguous_role_access_request_requires_explicit_choices(self):
        self.assertTrue(channel_role_configuration_request("Gère les rôles des salons que tu viens de créer"))
        self.assertTrue(channel_role_configuration_request("Configure les permissions des salons"))
        self.assertTrue(channel_role_configuration_request("Configure les accès aux salons pour les membres"))
        self.assertTrue(channel_role_configuration_request("Organise les droits des salons que tu as créés"))
        self.assertTrue(channel_role_configuration_request("Mets les permissions des salons pour les rôles"))
        self.assertFalse(channel_role_configuration_request("Crée un salon annonces et ajoute des rôles"))
        self.assertFalse(channel_role_configuration_request("Gère les rôles des salons puis supprime général"))
        self.assertFalse(channel_role_configuration_request("Crée des salons puis configure les permissions des rôles"))
        with self.assertRaises(ValueError):
            validate_actions([{"type": "set_channel_role_access", "channel_id": "223456789012345678",
                               "role_id": "123456789012345678", "view": "keep", "participate": "keep"}])

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

    def test_complex_clarification_is_preserved_for_the_model(self):
        self.assertEqual(collapse_old_clarifications("Réorganise le serveur\nPrécision : les salons d'annonces"),
                         "Réorganise le serveur\nPrécision : les salons d'annonces")

    def test_composed_commands_are_complete_and_ordered(self):
        self.assertEqual(app.supported_local_plan("Crée un salon annonces et active les statistiques des messages"), [
            {"type": "create_text_channel", "name": "annonces"},
            {"type": "set_module", "module": "activity_stats", "enabled": "true"},
        ])
        self.assertEqual(app.supported_local_plan("Crée un salon annonces puis crée un rôle Membre"), [
            {"type": "create_text_channel", "name": "annonces"},
            {"type": "create_role", "name": "Membre"},
        ])
        self.assertEqual(app.supported_local_plan("Crée un salon annonces et programme une campagne"), [])

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

            def __init__(self, answer, status=200):
                self.answer = answer
                self.status = status

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
                answer = self.answers.pop(0)
                return FakeResponse(*answer) if isinstance(answer, tuple) else FakeResponse(answer)

        first = '{"actions":[{"type":"create_forum_channel","name":"bienvenue"}]}'
        repaired = '{"actions":[{"type":"create_text_channel","name":"bienvenue"}]}'
        fake = FakeSession([first, repaired])
        with patch.object(app.aiohttp, "ClientSession", return_value=fake):
            actions, question = await app.ollama_plan("Crée un salon textuel bienvenue", "qwen-test")
        self.assertEqual(actions, [{"type": "create_text_channel", "name": "bienvenue"}])
        self.assertIsNone(question)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("create_text_channel", fake.calls[1]["messages"][-1]["content"])
        self.assertEqual(fake.calls[0]["format"], MODEL_PLAN_SCHEMA)

        schema_fallback = FakeSession([("", 400), repaired])
        with patch.object(app.aiohttp, "ClientSession", return_value=schema_fallback):
            result, _ = await app.ollama_plan("Crée un salon bienvenue", "qwen-test",
                                              {"connected": False, "recent_plans": []})
        self.assertEqual(result, [{"type": "create_text_channel", "name": "bienvenue"}])
        self.assertEqual(schema_fallback.calls[1]["format"], "json")
        self.assertIn("recent_plans", schema_fallback.calls[0]["messages"][1]["content"])

        no_actions = FakeSession(['{"actions":[]}', repaired])
        with patch.object(app.aiohttp, "ClientSession", return_value=no_actions):
            recovered, _ = await app.ollama_plan("Je voudrais créer un salon bienvenue", "qwen-test")
        self.assertEqual(recovered, [{"type": "create_text_channel", "name": "bienvenue"}])
        self.assertEqual(len(no_actions.calls), 2)

        invalid = FakeSession([first, first])
        with patch.object(app.aiohttp, "ClientSession", return_value=invalid):
            self.assertEqual(await app.ollama_plan("Crée un salon textuel bienvenue", "qwen-test"), ([], None))

        empty = FakeSession(['{"actions":[]}', '{"actions":[]}'])
        with patch.object(app.aiohttp, "ClientSession", return_value=empty):
            self.assertEqual(await app.ollama_plan("Configure les récompenses avec des détails manquants", "qwen-test"), ([], None))

        question = FakeSession(['{"actions":[],"question":"Quel rôle ?"}'])
        with patch.object(app.aiohttp, "ClientSession", return_value=question):
            self.assertEqual(await app.ollama_plan("Organise les rôles", "qwen-test"), ([], "Quel rôle ?"))
        self.assertEqual(len(question.calls), 1)


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

    async def test_ai_missing_details_get_an_editable_response_without_creating_plan(self):
        prompt = {"guild_id": "1567347687379050727", "mode": "ollama",
                  "prompt": "Réorganise les conversations à ta convenance"}
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=([], "Quel salon ?"))):
            res = await self.client.post("/api/plan", json=prompt, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertTrue(body["needs_clarification"])
        self.assertEqual(body["question"], "Quel salon ?")
        self.assertEqual(len(body["examples"]), 3)
        self.assertEqual(app.STATE.history(prompt["guild_id"]), [])

    async def test_empty_model_and_local_unsupported_request_never_create_draft(self):
        original = {"guild_id": "1567347687379050727", "mode": "ollama",
                    "prompt": "Arrange le serveur à ta convenance"}
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=([], None))):
            res = await self.client.post("/api/plan", json=original, headers=self.headers)
        self.assertEqual(res.status, 200)
        self.assertTrue((await res.json())["needs_clarification"])
        original["mode"] = "local"
        local_res = await self.client.post("/api/plan", json=original, headers=self.headers)
        self.assertEqual(local_res.status, 200)
        self.assertTrue((await local_res.json())["needs_clarification"])
        self.assertEqual(app.STATE.history(original["guild_id"]), [])

    async def test_recent_plan_context_contains_server_facts_not_secrets(self):
        gid = "1567347687379050727"
        p = app.STATE.add(gid, "Crée un salon annonces", [{"type": "create_text_channel", "name": "annonces"}], "local")
        p["status"] = "completed"
        p["results"] = [{"index": 0, "status": "done", "detail": "Salon créé (ID 223456789012345678)."}]
        with patch.object(app.MANAGER, "get_guild", return_value=None):
            context = app.planning_context(gid)
        self.assertFalse(context["connected"])
        self.assertEqual(context["recent_plans"][0]["actions"],
                         [{"type": "create_text_channel", "name": "annonces"}])
        self.assertIn("223456789012345678", context["recent_plans"][0]["completed_results"][0]["detail"])
        self.assertNotIn("token", str(context).lower())

    async def test_local_explicit_request_creates_draft(self):
        res = await self.client.post("/api/plan", json={"guild_id": "1567347687379050727",
                                                        "mode": "local", "prompt": "Rajoute un channel annonces"}, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertEqual(body["plan"]["status"], "draft")
        self.assertEqual(body["plan"]["actions"], [{"type": "create_text_channel", "name": "annonces"}])

    async def test_multi_action_request_includes_all_supported_tasks(self):
        with patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("no model needed"))):
            res = await self.client.post("/api/plan", json={
                "guild_id": "1567347687379050727", "mode": "auto",
                "prompt": "Crée un salon annonces et active les statistiques des messages",
            }, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertEqual(body["plan"]["actions"], [
            {"type": "create_text_channel", "name": "annonces"},
            {"type": "set_module", "module": "activity_stats", "enabled": "true"},
        ])

    async def test_model_receives_recent_server_context_for_followups(self):
        gid = "1567347687379050727"
        previous = app.STATE.add(gid, "Crée un salon annonces", [
            {"type": "create_text_channel", "name": "annonces"}], "local")
        previous["status"] = "completed"
        mock = AsyncMock(return_value=([{"type": "set_topic", "name": "annonces", "topic": "Infos"}], None))
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=mock), \
             patch.object(app.MANAGER, "get_guild", return_value=None):
            res = await self.client.post("/api/plan", json={"guild_id": gid, "mode": "auto",
                "prompt": "Change la description du dernier salon en Infos"}, headers=self.headers)
        self.assertEqual(res.status, 200)
        self.assertEqual(mock.await_args.args[2]["recent_plans"][0]["actions"],
                         [{"type": "create_text_channel", "name": "annonces"}])
        self.assertEqual((await res.json())["plan"]["status"], "draft")

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

    async def test_recent_channels_role_permissions_require_a_confirmed_draft(self):
        gid, cid, rid = "1567347687379050727", "223456789012345678", "123456789012345678"
        class FakeText:
            def __init__(self):
                self.id, self.name = int(cid), "annonces"

        class FakeVoice:
            pass

        channel = FakeText()
        role = SimpleNamespace(id=int(rid), name="Membre", managed=False)
        guild = SimpleNamespace(channels=[channel], roles=[role],
                                get_channel=lambda x: channel if x == channel.id else None,
                                get_role=lambda x: role if x == role.id else None)
        old = app.STATE.add(gid, "Crée un salon annonces", [{"type": "create_text_channel", "name": "annonces"}], "local")
        old["status"] = "completed"
        old["results"] = [{"index": 0, "status": "done", "detail": f"Salon créé (ID {cid})."}]
        app.STATE.save()
        with patch.object(app.MANAGER, "get_guild", return_value=guild), \
             patch.object(app.discord, "TextChannel", FakeText), \
             patch.object(app.discord, "VoiceChannel", FakeVoice), \
             patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("Ollama inutilisé"))):
            prompt = await self.client.post("/api/plan", json={"guild_id": gid, "mode": "auto",
                "prompt": "Gère les rôles des salons que tu viens de créer"}, headers=self.headers)
            self.assertEqual(prompt.status, 200)
            self.assertEqual((await prompt.json())["configuration_required"], "channel_role_access")
            self.assertEqual(len(app.STATE.history(gid)), 1)
            context = await self.client.get(f"/api/permissions/{gid}")
            self.assertEqual(context.status, 200)
            self.assertEqual((await context.json())["recent_channels"],
                             [{"id": cid, "name": "annonces", "type": "text"}])
            payload = {"channels": [cid], "role_id": rid, "view": "deny", "participate": "keep"}
            self.assertEqual((await self.client.post(f"/api/permissions/{gid}/draft", json=payload)).status, 403)
            other = {**payload, "channels": ["333333333333333333"]}
            self.assertEqual((await self.client.post(f"/api/permissions/{gid}/draft", json=other,
                                                      headers=self.headers)).status, 400)
            draft = await self.client.post(f"/api/permissions/{gid}/draft", json=payload, headers=self.headers)
            self.assertEqual(draft.status, 200)
            new_plan = (await draft.json())["plan"]
            self.assertEqual(new_plan["status"], "draft")
            self.assertEqual(new_plan["actions"], [{"type": "set_channel_role_access",
                 "channel_id": cid, "role_id": rid, "view": "deny", "participate": "keep"}])

    async def test_ai_cannot_invent_deletion(self):
        prompt = {"guild_id": "1567347687379050727", "mode": "ollama", "prompt": "Arrange les salons"}
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=([{"type": "delete_channel", "name": "annonces"}], None))):
            res = await self.client.post("/api/plan", json=prompt, headers=self.headers)
        self.assertEqual(res.status, 400)
        self.assertEqual(app.STATE.history("1567347687379050727"), [])

    async def test_ai_cannot_invent_role_permissions_even_with_valid_ids(self):
        prompt = {"guild_id": "1567347687379050727", "mode": "ollama", "prompt": "Organise les membres"}
        invented = [{"type": "set_channel_role_access", "channel_id": "223456789012345678",
                     "role_id": "123456789012345678", "view": "allow", "participate": "allow"}]
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=(invented, None))):
            result = await self.client.post("/api/plan", json=prompt, headers=self.headers)
        self.assertEqual(result.status, 400)
        self.assertEqual(app.STATE.history(prompt["guild_id"]), [])


if __name__ == "__main__":
    unittest.main()
