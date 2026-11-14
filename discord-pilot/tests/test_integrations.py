"""Integration catalogue and safe, user-authorized third-party install handoff."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import app
from integration_catalog import PROVIDERS, all_features, recommended_providers
from planner import validate_actions
from storage import State


GUILD = "1567347687379050727"


class IntegrationRoutingTests(unittest.TestCase):
    def test_all_ninety_features_are_classified_honestly(self):
        features = all_features()
        self.assertEqual(len(features), 90)
        self.assertEqual([f["number"] for f in features], list(range(1, 91)))
        self.assertEqual(len({f["id"] for f in features}), 90)
        self.assertEqual(features[-1]["title"], "Sauvegarde et restauration du serveur")
        for feature in features:
            if feature["native_module"]:
                self.assertEqual(feature["availability"], "native")
                continue
            if feature["provider_id"]:
                provider = PROVIDERS[feature["provider_id"]]
                self.assertEqual(feature["availability"], "external")
                self.assertTrue(provider["url"].startswith("https://"))
            else:
                self.assertEqual(feature["availability"], "planned")
        self.assertEqual(sum(bool(feature["native_module"]) for feature in features), 12)

    def test_recognize_multiple_requests_and_do_not_falsely_claim_installation(self):
        self.assertEqual(recommended_providers(
            "Ajoute un bot de musique, des niveaux, un système de tickets, "
            "une protection antiraid et un système de giveaways."),
            ["jockie", "tickettool", "wick", "lyx"])
        self.assertEqual(recommended_providers("Mets de la musique"), ["jockie"])
        self.assertEqual(recommended_providers("Crée un salon pour la musique"), [])
        self.assertEqual(recommended_providers("bonjour"), [])

    def test_integrations_are_strictly_whitelisted(self):
        self.assertEqual(validate_actions([{"type": "suggest_integration", "provider": "jockie"}]),
                         [{"type": "suggest_integration", "provider": "jockie"}])
        with self.assertRaises(ValueError):
            validate_actions([{"type": "suggest_integration", "provider": "https://evil.invalid"}])
        with self.assertRaises(ValueError):
            validate_actions([{"type": "suggest_integration", "provider": "jockie", "token": "abc"}])


class IntegrationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original, self.original_port = app.STATE, app.PORT
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
        app.STATE, app.PORT = self.original, self.original_port
        self.tmp.cleanup()

    async def test_catalogue_is_readonly_and_safe(self):
        response = await self.client.get("/api/catalog")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(len(data["features"]), 90)
        self.assertIn("jockie", data["providers"])
        self.assertNotIn("token", str(data).lower())

    async def test_voice_request_yields_draft_without_external_install(self):
        with patch.object(app, "ollama_models", new=AsyncMock(side_effect=AssertionError("No model required"))), \
             patch.object(app, "execute_action", new=AsyncMock(side_effect=AssertionError("No Discord write"))):
            result = await self.client.post("/api/plan", json={
                "guild_id": GUILD, "mode": "auto", "prompt": "Mets de la musique",
            }, headers=self.headers)
        self.assertEqual(result.status, 200)
        plan = (await result.json())["plan"]
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(plan["actions"], [{"type": "suggest_integration", "provider": "jockie"}])

    async def test_install_requires_authorization_and_does_not_fake_success(self):
        without_csrf = await self.client.post("/api/integrations/plan", json={
            "guild_id": GUILD, "provider": "jockie",
        })
        self.assertEqual(without_csrf.status, 403)
        unknown = await self.client.post("/api/integrations/plan", json={
            "guild_id": GUILD, "provider": "https://evil.invalid",
        }, headers=self.headers)
        self.assertEqual(unknown.status, 400)
        response = await self.client.post("/api/integrations/plan", json={
            "guild_id": GUILD, "provider": "jockie",
        }, headers=self.headers)
        self.assertEqual(response.status, 200)
        plan = (await response.json())["plan"]
        self.assertEqual(plan["status"], "draft")
        with patch.object(app, "execute_action", new=AsyncMock(side_effect=AssertionError("No Discord write"))):
            execute = await self.client.post(f"/api/execute/{plan['id']}", json={}, headers=self.headers)
            self.assertEqual(execute.status, 200)
            for _ in range(20):
                await __import__("asyncio").sleep(0.01)
                fresh = app.STATE.get(plan["id"])
                if fresh["status"] not in {"queued", "running"}:
                    break
        self.assertEqual(fresh["status"], "authorization_required")
        self.assertEqual(fresh["results"][0]["status"], "authorization_required")
        self.assertEqual(fresh["results"][0]["authorization_url"], PROVIDERS["jockie"]["url"])
        self.assertIn("Non installé", fresh["results"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
