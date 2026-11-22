"""P3: inspectable, idempotent Discord panel publication and plan chaining."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import discord

import app
import discord_ops
from panel_actions import publish_panel
from panel_planning import complete_panel_plan, direct_panel_plan, publication_requested
from planner import parse_ollama_decision, validate_actions
from storage import State
from test_p2_planner import CATID, CID, GID, RID, FakeChannel, FakeGuild


class PanelText(FakeChannel):
    def __init__(self, name="tickets", ident=CID, private=False):
        super().__init__(name, ident, private)
        self.sent = []
        self.deleted = False
        self.last_message = None

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))
        self.last_message = SimpleNamespace(id=713456789012345678 + len(self.sent), edit=AsyncMock())
        self.deleted = False
        return self.last_message

    async def fetch_message(self, ident):
        if self.deleted or not self.last_message or ident != self.last_message.id:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "deleted")
        return self.last_message


class PanelPlanningTests(unittest.TestCase):
    def test_explicit_publication_is_supported_without_ollama(self):
        self.assertEqual(direct_panel_plan("Publie le panneau des tickets"),
                         [{"type": "publish_ticket_panel"}])
        self.assertEqual(direct_panel_plan("Publie le formulaire des candidatures"),
                         [{"type": "publish_application_panel"}])
        self.assertEqual(app.supported_local_plan("Publie le panneau des tickets"),
                         [{"type": "publish_ticket_panel"}])
        self.assertEqual(direct_panel_plan("Organise les tickets"), [])

    def test_activation_adds_one_visible_publish_step_only_when_requested(self):
        configured = [{"type": "configure_module", "module": "tickets", "enabled": "true",
                       "panel_channel_id": "tickets", "category_id": "SUPPORT"}]
        self.assertEqual([a["type"] for a in complete_panel_plan("Active les tickets", configured)],
                         ["configure_module", "publish_ticket_panel"])
        self.assertEqual(complete_panel_plan("Configure les tickets sans publier", configured), configured)
        self.assertFalse(publication_requested("Configure les tickets sans publier", "tickets"))
        once = complete_panel_plan("Active les tickets", configured)
        self.assertEqual(complete_panel_plan("Active les tickets", once), once)
        model, _ = parse_ollama_decision('{"actions":[{"type":"publish_ticket_panel"},'
                                         '{"type":"publish_application_panel"}]}')
        self.assertEqual([a["type"] for a in model], ["publish_ticket_panel", "publish_application_panel"])
        with self.assertRaises(ValueError):
            validate_actions([{"type": "publish_ticket_panel", "content": "@everyone"}])


class PanelRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_publications_do_not_create_duplicate_messages(self):
        class SlowPanelText(PanelText):
            async def send(self, content, **kwargs):
                await asyncio.sleep(0.02)
                return await super().send(content, **kwargs)

        guild = FakeGuild()
        guild.channel = SlowPanelText("tickets")
        guild.channels[0] = guild.channel
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            state.set_module(str(GID), "tickets", {"enabled": True,
                "panel_channel_id": str(CID), "category_id": str(CATID), "staff_role_id": str(RID)})
            with patch.object(discord_ops.discord, "TextChannel", PanelText):
                results = await asyncio.gather(
                    publish_panel(guild, state, "tickets"),
                    publish_panel(guild, state, "tickets"),
                )
            self.assertEqual([result[0] for result in results], ["done", "skipped"])
            self.assertEqual(len(guild.channel.sent), 1)

    async def test_ticket_panel_is_reused_and_repaired_only_when_deleted(self):
        guild = FakeGuild()
        guild.channel = PanelText("tickets")
        guild.channels[0] = guild.channel
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            state.set_module(str(GID), "tickets", {"enabled": True,
                "panel_channel_id": str(CID), "category_id": str(CATID), "staff_role_id": str(RID)})
            with patch.object(discord_ops.discord, "TextChannel", PanelText):
                first, _detail, record = await publish_panel(guild, state, "tickets")
                self.assertEqual(first, "done")
                self.assertEqual(record["message_id"], str(guild.channel.last_message.id))
                again, _detail, same = await publish_panel(guild, state, "tickets")
                self.assertEqual(again, "skipped")
                self.assertEqual(same, record)
                self.assertEqual(len(guild.channel.sent), 1)
                guild.channel.deleted = True
                renewed, _detail, updated = await publish_panel(guild, state, "tickets")
                self.assertEqual(renewed, "done")
                self.assertNotEqual(updated["message_id"], record["message_id"])
                self.assertEqual(len(guild.channel.sent), 2)

    async def test_recruitment_buttons_update_existing_panel_without_new_public_messages(self):
        guild = FakeGuild()
        guild.channel = PanelText("tickets")
        guild.channels[0] = guild.channel
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            base = {"enabled": True, "panel_channel_id": str(CID),
                    "category_id": str(CATID), "staff_role_id": str(RID)}
            state.set_module(str(GID), "tickets", base)
            with patch.object(discord_ops.discord, "TextChannel", PanelText):
                first, _, old = await publish_panel(guild, state, "tickets")
                self.assertEqual(first, "done")
                self.assertEqual(len(guild.channel.sent), 1)
                self.assertEqual(len(guild.channel.sent[0][1]["view"].children), 1)
                state.set_module(str(GID), "tickets",
                                 {**base, "recruitment_games": "valorant, rocket-league, fortnite, clash-of-clans"})
                status, _, updated = await publish_panel(guild, state, "tickets")
                self.assertEqual(status, "done")
                self.assertEqual(updated["message_id"], old["message_id"])
                self.assertEqual(len(guild.channel.sent), 1)
                edit_kwargs = guild.channel.last_message.edit.call_args.kwargs
                buttons = edit_kwargs["view"].children
                self.assertEqual(len(buttons), 5)
                self.assertEqual([b.label for b in buttons][1:],
                                 ["Valorant", "Rocket League", "Fortnite", "Clash of Clans"])
                self.assertEqual(buttons[1].custom_id,
                                 f"pilot:ticket:open:{GID}:valorant")
                again, _, _ = await publish_panel(guild, state, "tickets")
                self.assertEqual(again, "skipped")
                self.assertEqual(guild.channel.last_message.edit.await_count, 1)
                state.set_module(str(GID), "tickets", base)
                disabled, _, _ = await publish_panel(guild, state, "tickets")
                self.assertEqual(disabled, "done")
                self.assertEqual(len(guild.channel.last_message.edit.call_args.kwargs["view"].children), 1)

    async def test_application_panel_requires_private_review_channel(self):
        guild = FakeGuild()
        guild.channel = PanelText("candidatures")
        guild.channels[0] = guild.channel
        guild.review = PanelText("validation", 623456789012345678)
        guild.channels.append(guild.review)
        original_get_channel = guild.get_channel
        guild.get_channel = lambda ident: guild.review if ident == guild.review.id else original_get_channel(ident)
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            state.set_module(str(GID), "applications", {"enabled": True,
                "panel_channel_id": str(CID), "staff_channel_id": str(guild.review.id),
                "staff_role_id": ""})
            with patch.object(discord_ops.discord, "TextChannel", PanelText):
                with self.assertRaises(ValueError):
                    await publish_panel(guild, state, "applications")
                self.assertEqual(guild.channel.sent, [])
                guild.review.private = True
                status, _detail, record = await publish_panel(guild, state, "applications")
                self.assertEqual(status, "done")
                self.assertEqual(record["channel_id"], str(CID))
                self.assertEqual(guild.channel.sent[0][1]["view"].children[0].custom_id,
                                 f"pilot:application:open:{GID}")

    async def test_end_to_end_plan_creates_ticket_structure_and_real_panel_mock(self):
        guild = FakeGuild(existing=False)
        guild.channel = PanelText("tickets")
        guild.create_text_channel.return_value = guild.channel
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            actions = validate_actions([
                {"type": "create_category", "name": "SUPPORT"},
                {"type": "create_role", "name": "Support"},
                {"type": "create_text_channel", "name": "tickets", "category": "SUPPORT"},
                {"type": "configure_module", "module": "tickets", "enabled": "true",
                 "panel_channel_id": "tickets", "category_id": "SUPPORT", "staff_role_id": "Support"},
                {"type": "publish_ticket_panel"},
            ])
            plan = state.add(str(GID), "Crée SUPPORT et active les tickets", actions, "test")
            with patch.object(app, "STATE", state), \
                 patch.object(discord_ops.discord, "TextChannel", PanelText), \
                 patch.object(app.MANAGER, "activate_automations", new_callable=AsyncMock):
                await app.run_plan(plan, guild)
            self.assertEqual(plan["status"], "completed", plan["results"])
            self.assertEqual(len(guild.channel.sent), 1)
            self.assertEqual(guild.channel.sent[0][1]["view"].children[0].custom_id,
                             f"pilot:ticket:open:{GID}")
            self.assertIn(str(GID), state.state["ticket_panels"])
            self.assertTrue(state.module(str(GID), "tickets")["enabled"])

    async def test_publish_failure_blocks_later_plan_steps(self):
        guild = FakeGuild()
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            actions = validate_actions([{"type": "publish_ticket_panel"},
                                       {"type": "create_role", "name": "Autre"}])
            plan = state.add(str(GID), "Publie le panneau puis crée Autre", actions, "test")
            with patch.object(app, "STATE", state), \
                 patch.object(app.MANAGER, "activate_automations", new_callable=AsyncMock):
                await app.run_plan(plan, guild)
            self.assertEqual(plan["status"], "failed")
            self.assertEqual([item["status"] for item in plan["results"]], ["failed", "blocked"])
            guild.create_role.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
