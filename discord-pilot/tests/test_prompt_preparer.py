import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import tempfile

import discord
from aiohttp.test_utils import TestClient, TestServer

import app
from app import supported_local_plan
from discord_ops import execute_action
from planner import (direct_lock_writing_plan, resolve_lock_targets,
                     understood_request, writing_restriction_requested)
from storage import State


class PromptPreparerTests(unittest.TestCase):
    def test_spoken_request_becomes_three_actions(self):
        prompt = ("modifie les rôles pour les salons au revoir, bienvenue, invitation "
                  "pour pas que tout le monde puisse écrire dedans")
        actions = supported_local_plan(prompt)
        self.assertEqual(actions, [
            {"type": "lock_channel_writing", "name": "au revoir"},
            {"type": "lock_channel_writing", "name": "bienvenue"},
            {"type": "lock_channel_writing", "name": "invitation"},
        ])
        self.assertIn("lecture seule", understood_request(actions))

    def test_lock_and_create_are_both_preserved(self):
        plan = supported_local_plan("Mets les salons annonces en lecture seule ; crée le salon discussion")
        self.assertEqual([a["type"] for a in plan], ["lock_channel_writing", "create_text_channel"])

    def test_authorization_and_ambiguity(self):
        self.assertFalse(writing_restriction_requested("Autorise tout le monde à écrire"))
        self.assertEqual(direct_lock_writing_plan("Autorise tout le monde à écrire dans les salons général"), [])
        items = [{"type": "lock_channel_writing", "name": "au revoir"},
                 {"type": "lock_channel_writing", "name": "invitation"}]
        result, question = resolve_lock_targets(items, ["👋・au-revoir", "invitations"])
        self.assertIsNone(question)
        self.assertEqual([a["name"] for a in result], ["👋・au-revoir", "invitations"])
        _, question = resolve_lock_targets(items, ["au-revoir", "au_revoir", "invitations"])
        self.assertIn("ambigu", question)


class FakeRole:
    def __init__(self, name, *, default=False, managed=False, admin=False):
        self.name = name
        self.id = len(name) * 1000 + id(self)
        self.default = default
        self.managed = managed
        self.permissions = discord.Permissions(administrator=admin)

    def is_default(self):
        return self.default


class FakeMember:
    def __init__(self, bot=False):
        self.bot = bot
        self.guild_permissions = discord.Permissions.none()


class FakeChannel:
    def __init__(self, name, overwrites):
        self.name = name
        self.id = 333
        self._overwrites = overwrites
        self.changes = 0

    @property
    def overwrites(self):
        return dict(self._overwrites)

    def overwrites_for(self, target):
        previous = self._overwrites.get(target, discord.PermissionOverwrite())
        return discord.PermissionOverwrite.from_pair(*previous.pair())

    async def set_permissions(self, target, *, overwrite, reason):
        self.changes += 1
        self._overwrites[target] = overwrite


class PermissionExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_keeps_visibility_and_bot(self):
        everyone = FakeRole("@everyone", default=True)
        member_role = FakeRole("Membre")
        integration_role = FakeRole("Bot accueil", managed=True)
        admin = FakeRole("Administrateur", admin=True)
        human = FakeMember()
        pilot = FakeMember(bot=True)
        channel = FakeChannel("bienvenue", {
            everyone: discord.PermissionOverwrite(view_channel=True),
            member_role: discord.PermissionOverwrite(send_messages=True),
            integration_role: discord.PermissionOverwrite(send_messages=True),
            human: discord.PermissionOverwrite(send_messages=True),
        })
        guild = SimpleNamespace(roles=[everyone, member_role, integration_role, admin],
                                channels=[channel], categories=[], me=pilot)
        with patch("discord_ops.discord.TextChannel", FakeChannel):
            status, _ = await execute_action(guild, {"type": "lock_channel_writing", "name": "bienvenue"})
            self.assertEqual(status, "done")
            self.assertTrue(channel.overwrites_for(everyone).view_channel)
            self.assertFalse(channel.overwrites_for(everyone).send_messages)
            self.assertFalse(channel.overwrites_for(member_role).send_messages)
            self.assertFalse(channel.overwrites_for(human).send_messages)
            self.assertTrue(channel.overwrites_for(integration_role).send_messages)
            self.assertTrue(channel.overwrites_for(pilot).send_messages)
            count = channel.changes
            status, _ = await execute_action(guild, {"type": "lock_channel_writing", "name": "bienvenue"})
            self.assertEqual(status, "skipped")
            self.assertEqual(channel.changes, count)


class PromptApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_state, self.original_port = app.STATE, app.PORT
        app.STATE = State(Path(self.temp.name))
        self.server = TestServer(app.build_app(), host="127.0.0.1")
        await self.server.start_server()
        app.PORT = self.server.port
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        app.STATE, app.PORT = self.original_state, self.original_port
        self.temp.cleanup()

    async def test_no_automatic_discord_change(self):
        csrf = (await (await self.client.get("/api/bootstrap")).json())["csrf"]
        result = await self.client.post("/api/plan", json={
            "guild_id": "1567347687379050727", "mode": "local",
            "prompt": ("Modifie les rôles pour les salons au revoir, bienvenue, invitation "
                       "pour pas que tout le monde puisse écrire dedans"),
        }, headers={"X-Pilot-CSRF": csrf})
        self.assertEqual(result.status, 200)
        body = await result.json()
        self.assertEqual([a["type"] for a in body["plan"]["actions"]], ["lock_channel_writing"] * 3)
        self.assertEqual(body["plan"]["status"], "draft")
        self.assertIn("lecture seule", body["plan"]["interpretation"])
