"""Non-destructive regression tests for conversational Discord instructions."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
from planner import local_parse, missing_information, parse_ollama_decision
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

    def test_incomplete_request_asks_instead_of_guessing(self):
        self.assertIn("Quel nom", missing_information("Rajoute un channel"))
        self.assertIn("Quel nom", missing_information("Ajoute un canal dans la catégorie ACCUEIL"))
        self.assertIsNone(missing_information("Ajoute un salon annonces"))

    def test_local_model_can_ask_a_question(self):
        actions, question = parse_ollama_decision('{"actions":[],"question":"Quel salon veux-tu créer ?"}')
        self.assertEqual(actions, [])
        self.assertEqual(question, "Quel salon veux-tu créer ?")

    def test_no_code_execution(self):
        with self.assertRaises(ValueError):
            parse_ollama_decision('{"actions":[{"type":"run_shell","cmd":"powershell"}]}')


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

    async def test_ask_for_name_without_changing_discord(self):
        res = await self.client.post("/api/plan", json={"guild_id": "1567347687379050727",
                                                        "mode": "auto", "prompt": "Rajoute un channel"}, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertTrue(body["needs_clarification"])
        self.assertEqual(app.STATE.history("1567347687379050727"), [])

    async def test_local_explicit_request_creates_draft(self):
        res = await self.client.post("/api/plan", json={"guild_id": "1567347687379050727",
                                                        "mode": "local", "prompt": "Rajoute un channel annonces"}, headers=self.headers)
        self.assertEqual(res.status, 200)
        body = await res.json()
        self.assertEqual(body["plan"]["status"], "draft")
        self.assertEqual(body["plan"]["actions"], [{"type": "create_text_channel", "name": "annonces"}])

    async def test_ai_cannot_invent_deletion(self):
        prompt = {"guild_id": "1567347687379050727", "mode": "ollama", "prompt": "Arrange les salons"}
        with patch.object(app, "ollama_models", new=AsyncMock(return_value=["model-essai"])), \
             patch.object(app, "ollama_plan", new=AsyncMock(return_value=([{"type": "delete_channel", "name": "annonces"}], None))):
            res = await self.client.post("/api/plan", json=prompt, headers=self.headers)
        self.assertEqual(res.status, 400)
        self.assertEqual(app.STATE.history("1567347687379050727"), [])


if __name__ == "__main__":
    unittest.main()
