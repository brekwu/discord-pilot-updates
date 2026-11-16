"""P2: native module configuration, named permissions and safe plan chaining."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

import app
import discord_ops
from community_modules import MODULES
from plan_runtime import (direct_permission_plan, explicit_permission_intent, permission_action_is_authorized,
                          resolve_module_settings, set_module_config)
from planner import MODEL_PLAN_SCHEMA, parse_ollama_decision, validate_actions
from storage import State


GID = 1567347687379050727
CID = 223456789012345678
RID = 123456789012345678
CATID = 323456789012345678


class FakeRole:
    def __init__(self, name="Support", ident=RID, default=False):
        self.name, self.id, self.default, self.managed = name, ident, default, False

    def is_default(self):
        return self.default


class FakeChannel:
    def __init__(self, name="support", ident=CID, private=False):
        self.name, self.id, self.type, self.private = name, ident, "text", private
        self.category_id = None
        self.set_permissions = AsyncMock(side_effect=self.set_permission)

    async def set_permission(self, role, *, overwrite, reason):
        if role.is_default() and overwrite.view_channel is False:
            self.private = True

    def permissions_for(self, _role):
        return SimpleNamespace(view_channel=not self.private)

    def overwrites_for(self, _role):
        return discord.PermissionOverwrite()


class FakeCategory:
    def __init__(self, name="SUPPORT", ident=CATID):
        self.name, self.id, self.type = name, ident, "category"


class FakeGuild:
    def __init__(self, *, existing=True):
        self.id = GID
        self.default_role = FakeRole("@everyone", GID, default=True)
        self.role = FakeRole()
        self.channel = FakeChannel()
        self.category = FakeCategory()
        self.roles = [self.default_role, self.role] if existing else [self.default_role]
        self.channels = [self.channel, self.category] if existing else []
        self.categories = [self.category] if existing else []
        self.me = None
        self.create_role = AsyncMock(return_value=self.role)
        self.create_text_channel = AsyncMock(return_value=self.channel)
        self.create_category = AsyncMock(return_value=self.category)

    def get_channel(self, ident):
        return next((ch for ch in self.channels if ch.id == ident), None)

    def get_role(self, ident):
        return next((r for r in self.roles if r.id == ident), None)


class P2ValidationTests(unittest.TestCase):
    def test_every_native_module_has_safe_plan_schema(self):
        self.assertEqual(len(MODULES), 17)
        for name, spec in MODULES.items():
            fields = {key: "support" for key, _kind, _label in spec["fields"]}
            with self.subTest(module=name):
                parsed = validate_actions([{"type": "configure_module", "module": name,
                                            "enabled": "true", **fields}])
                self.assertEqual(parsed[0]["module"], name)
        self.assertIn("configure_module", MODEL_PLAN_SCHEMA["properties"]["actions"]["items"]["properties"]["type"]["enum"])

    def test_unknown_options_and_sensitive_permissions_are_rejected(self):
        for action in (
            {"type": "configure_module", "module": "xp", "enabled": "true", "role_id": str(RID)},
            {"type": "configure_module", "module": "unknown", "enabled": "true"},
            {"type": "configure_module", "module": "tickets", "enabled": "yes"},
            {"type": "set_role_access", "channel": "support", "role": "Staff", "view": "keep", "participate": "keep"},
            {"type": "create_role", "name": "Admin", "permissions": "administrator"},
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_actions([action])

    def test_model_module_and_permission_configuration(self):
        parsed, question = parse_ollama_decision('{"actions":['
            '{"type":"configure_module","module":"wordfilter","enabled":"true","words":"spam, fraude"},'
            '{"type":"set_role_access","channel":"annonces","role":"Membre",'
            '"view":"allow","participate":"keep"}]}')
        self.assertIsNone(question)
        self.assertEqual([item["type"] for item in parsed], ["configure_module", "set_role_access"])
        self.assertEqual(direct_permission_plan("Autorise le rôle Membre à voir le salon annonces"), [
            {"type": "set_role_access", "channel": "annonces", "role": "Membre",
             "view": "allow", "participate": "keep"}])
        self.assertEqual(direct_permission_plan("Interdis au rôle Visiteur d'écrire dans le salon annonces"), [
            {"type": "set_role_access", "channel": "annonces", "role": "Visiteur",
             "view": "keep", "participate": "deny"}])
        self.assertEqual(direct_permission_plan("Organise les rôles"), [])
        self.assertFalse(explicit_permission_intent("Organise les membres"))
        self.assertFalse(explicit_permission_intent("Configure les permissions des membres du salon annonces"))
        self.assertTrue(explicit_permission_intent("Interdis au rôle Visiteur d'écrire dans le salon annonces"))
        self.assertFalse(permission_action_is_authorized("Autorise le rôle Membre à voir le salon annonces",
            {"type": "set_role_access", "channel": "annonces", "role": "Membre",
             "view": "allow", "participate": "allow"}))
        daily, _ = parse_ollama_decision('{"actions":[{"type":"configure_module",'
            '"module":"daily_post","enabled":"true","channel_id":"annonces",'
            '"hour":"08:30","message":"Bonjour à tous"}]}')
        self.assertEqual(daily[0]["message"], "Bonjour à tous")

    def test_config_resolves_only_existing_entities_and_requires_private_support(self):
        guild = FakeGuild()
        config = resolve_module_settings(guild, {}, {"type": "configure_module", "module": "tickets",
            "enabled": "true", "panel_channel_id": "support", "category_id": "SUPPORT", "staff_role_id": "Support"})
        self.assertEqual(config, {"enabled": True, "panel_channel_id": str(CID),
                                  "category_id": str(CATID), "staff_role_id": str(RID)})
        words = resolve_module_settings(guild, {}, {"type": "configure_module", "module": "wordfilter",
            "enabled": "true", "words": "Spam, Arnaque"})
        self.assertEqual(words["words"], "spam, arnaque")
        with self.assertRaises(ValueError):
            resolve_module_settings(guild, {}, {"type": "configure_module", "module": "modmail",
                "enabled": "true", "staff_channel_id": "support"})
        with self.assertRaises(ValueError):
            resolve_module_settings(guild, {}, {"type": "configure_module", "module": "tickets",
                "enabled": "true", "panel_channel_id": "inexistant", "category_id": "SUPPORT"})

    def test_repeated_config_is_idempotent(self):
        guild = FakeGuild()
        with tempfile.TemporaryDirectory() as temp:
            state = State(Path(temp))
            item = {"type": "configure_module", "module": "xp", "enabled": "true"}
            self.assertEqual(set_module_config(state, guild, item)[0], "done")
            self.assertEqual(set_module_config(state, guild, item)[0], "skipped")


class P2ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_local_plan_chains_creation_privacy_and_module(self):
        guild = FakeGuild(existing=False)
        with tempfile.TemporaryDirectory() as temp:
            state = State(Path(temp))
            actions = validate_actions([
                {"type": "create_category", "name": "SUPPORT"},
                {"type": "create_role", "name": "Support"},
                {"type": "create_text_channel", "name": "support", "category": "SUPPORT"},
                {"type": "make_private", "name": "support", "role": "Support"},
                {"type": "configure_module", "module": "modmail", "enabled": "true",
                 "staff_channel_id": "support", "staff_role_id": "Support"},
            ])
            plan = state.add(str(GID), "Crée une équipe support et configure le modmail", actions, "test")
            with patch.object(app, "STATE", state), \
                 patch.object(discord_ops.discord, "TextChannel", FakeChannel), \
                 patch.object(app.MANAGER, "activate_automations", new_callable=AsyncMock):
                await app.run_plan(plan, guild)
            self.assertEqual(plan["status"], "completed", plan["results"])
            self.assertEqual([row["status"] for row in plan["results"]], ["done"] * 5)
            self.assertEqual(state.module(str(GID), "modmail")["staff_role_id"], str(RID))
            self.assertTrue(guild.channel.private)

    async def test_new_category_role_and_channel_are_accessible_to_following_actions(self):
        guild = FakeGuild(existing=False)
        guild.channel.name = "support"
        created = {"channels": {}, "roles": {}, "categories": {}}
        with patch.object(discord_ops.discord, "TextChannel", FakeChannel):
            for action in (
                {"type": "create_category", "name": "SUPPORT"},
                {"type": "create_role", "name": "Support"},
                {"type": "create_text_channel", "name": "support", "category": "SUPPORT"},
            ):
                self.assertEqual((await discord_ops.execute_action(guild, action, created=created))[0], "done")
            guild.create_text_channel.assert_awaited_once()
            self.assertIs(guild.create_text_channel.await_args.kwargs["category"], guild.category)
            result = await discord_ops.execute_action(guild, {"type": "set_role_access",
                "channel": "support", "role": "Support", "view": "allow", "participate": "keep"}, created=created)
            self.assertEqual(result[0], "done")
            self.assertTrue(guild.channel.set_permissions.await_args.kwargs["overwrite"].view_channel)

    async def test_failed_step_blocks_rest_of_plan_without_sending_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            state = State(Path(temp))
            actions = validate_actions([
                {"type": "create_role", "name": "Staff"},
                {"type": "send_message", "channel": "annonces", "content": "Bonjour"},
            ])
            plan = state.add(str(GID), "Crée Staff puis annonce", actions, "test")
            executor = AsyncMock(side_effect=ValueError("Rôle déjà interdit"))
            with patch.object(app, "STATE", state), patch.object(app, "execute_action", executor):
                await app.run_plan(plan, FakeGuild())
            self.assertEqual(plan["status"], "failed")
            self.assertEqual([row["status"] for row in plan["results"]], ["failed", "blocked"])
            self.assertEqual(executor.await_count, 1)

    async def test_transient_idempotent_error_is_retried_once(self):
        with tempfile.TemporaryDirectory() as temp:
            state = State(Path(temp))
            actions = validate_actions([{"type": "set_role_access", "channel": "support",
                "role": "Support", "view": "allow", "participate": "keep"}])
            plan = state.add(str(GID), "Autorise Support à voir support", actions, "test")
            transient = discord.HTTPException(SimpleNamespace(status=503, reason="temporaire"), "Essaye encore")
            executor = AsyncMock(side_effect=[transient, ("done", "Permissions appliquées")])
            with patch.object(app, "STATE", state), patch.object(app, "execute_action", executor), \
                 patch.object(app.asyncio, "sleep", new_callable=AsyncMock):
                await app.run_plan(plan, FakeGuild())
            self.assertEqual(plan["status"], "completed")
            self.assertEqual(executor.await_count, 2)


if __name__ == "__main__":
    unittest.main()
