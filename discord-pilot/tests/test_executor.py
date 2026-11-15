import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from discord_ops import execute_action


class FakeRole:
    def __init__(self, name, role_id):
        self.name, self.id = name, role_id


class FakeGuild:
    def __init__(self):
        self.categories = []
        self.roles = []
        self.channels = []
        self.created_role_permissions = None

    async def create_category(self, name, **kwargs):
        category = SimpleNamespace(name=name, id=len(self.categories) + 100)
        self.categories.append(category)
        return category

    async def create_role(self, name, **kwargs):
        self.created_role_permissions = kwargs["permissions"].value
        role = FakeRole(name, len(self.roles) + 200)
        self.roles.append(role)
        return role


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_role_access_changes_only_the_explicit_permission(self):
        import discord_ops

        class FakeText:
            def __init__(self):
                self.id = 223456789012345678
                self.overwrite = SimpleNamespace(view_channel=None, send_messages=True, connect=None,
                                                 manage_channels=None)
                self.set_permissions = AsyncMock()

            def overwrites_for(self, _role):
                return self.overwrite

        class FakeVoice:
            pass

        role = SimpleNamespace(id=123456789012345678, managed=False)
        channel = FakeText()
        guild = SimpleNamespace(get_channel=lambda x: channel if x == channel.id else None,
                                get_role=lambda x: role if x == role.id else None)
        item = {"type": "set_channel_role_access", "channel_id": str(channel.id),
                "role_id": str(role.id), "view": "deny", "participate": "keep"}
        with patch.object(discord_ops.discord, "TextChannel", FakeText), \
             patch.object(discord_ops.discord, "VoiceChannel", FakeVoice):
            self.assertEqual((await execute_action(guild, item))[0], "done")
            self.assertIs(channel.overwrite.view_channel, False)
            self.assertIs(channel.overwrite.send_messages, True)
            self.assertIsNone(channel.overwrite.manage_channels)
            channel.set_permissions.assert_awaited_once()
            self.assertEqual((await execute_action(guild, item))[0], "skipped")
            self.assertEqual(channel.set_permissions.await_count, 1)

    async def test_create_category_is_idempotent(self):
        guild = FakeGuild()
        first = await execute_action(guild, {"type": "create_category", "name": "ACCUEIL"})
        second = await execute_action(guild, {"type": "create_category", "name": "accueil"})
        self.assertEqual([first[0], second[0]], ["done", "skipped"])
        self.assertEqual(len(guild.categories), 1)

    async def test_created_role_has_no_privileges(self):
        guild = FakeGuild()
        first = await execute_action(guild, {"type": "create_role", "name": "Membre"})
        second = await execute_action(guild, {"type": "create_role", "name": "membre"})
        self.assertEqual([first[0], second[0]], ["done", "skipped"])
        self.assertEqual(len(guild.roles), 1)
        self.assertEqual(guild.created_role_permissions, 0)

    async def test_invalid_color_fails_closed(self):
        guild = FakeGuild()
        with self.assertRaises(ValueError):
            await execute_action(guild, {"type": "create_role", "name": "VIP", "color": "red;admin"})
        self.assertEqual(len(guild.roles), 0)


if __name__ == "__main__":
    unittest.main()
