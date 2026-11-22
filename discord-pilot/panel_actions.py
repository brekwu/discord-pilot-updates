"""Publish interactive Discord panels once, with strict guild validation.

Both the HTTP module tab and the natural-language plan use this executor.  A
stored message is checked before another one is sent; transient fetch errors
are propagated, not mistaken for deleted messages.  No background hosting.
"""

from __future__ import annotations

import asyncio
import discord

from community_modules import normalize_module
from plan_runtime import PlanGuildView
from recruitment_tickets import GAME_LABELS, enabled_games


PANEL_SPECS = {
    "tickets": {
        "state_key": "ticket_panels",
        "label": "Ouvrir un ticket",
        "custom_prefix": "pilot:ticket:open",
        "button_style": discord.ButtonStyle.primary,
        "emoji": "🎟️",
        "message": "🎟️ **Besoin d'aide ?** Clique ci-dessous pour ouvrir un ticket privé.",
    },
    "applications": {
        "state_key": "application_panels",
        "label": "Déposer ma candidature",
        "custom_prefix": "pilot:application:open",
        "button_style": discord.ButtonStyle.primary,
        "emoji": "📝",
        "message": "📝 **Candidatures ouvertes** — clique sur le bouton pour remplir le formulaire.",
    },
}

PANEL_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


async def publish_panel(guild, state, module: str, created: dict | None = None) -> tuple[str, str, dict]:
    """Create exactly one active panel per guild and module.

    Returns (done|skipped, detail, saved panel record). In ambiguous states,
    fail closed instead of duplicating public messages.
    """
    if module not in PANEL_SPECS:
        raise ValueError("Type de panneau interactif inconnu.")
    # Two rapid clicks or an HTTP request arriving during a plan may race.
    # Serialize the lookup + send + persistent record as one operation.
    async with PANEL_LOCKS.setdefault((str(guild.id), module), asyncio.Lock()):
        return await _publish_panel_once(guild, state, module, created)


async def _publish_panel_once(guild, state, module: str, created: dict | None) -> tuple[str, str, dict]:
    gid = str(guild.id)
    cfg = state.module(gid, module)
    if not cfg.get("enabled"):
        raise ValueError(f"Active et configure d'abord le module {module}.")
    view_guild = PlanGuildView(guild, created)
    # Check that all configured objects exist on this server, including the
    # private staff channel and the ticket category where applicable.
    cfg = normalize_module(module, cfg, view_guild)
    channel = view_guild.get_channel(int(cfg["panel_channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Le salon public du panneau n'existe plus.")
    spec = PANEL_SPECS[module]
    records = state.state[spec["state_key"]]
    previous = records.get(gid)
    if previous:
        former_channel_id = previous.get("channel_id", "")
        former_message_id = previous.get("message_id", "")
        if isinstance(former_channel_id, str) and former_channel_id.isdigit() and \
                isinstance(former_message_id, str) and former_message_id.isdigit():
            previous_channel = view_guild.get_channel(int(former_channel_id))
            if not isinstance(previous_channel, discord.TextChannel):
                raise ValueError("Ancien salon du panneau inaccessible : vérifie sa suppression avant de republier.")
            try:
                former_message = await previous_channel.fetch_message(int(former_message_id))
            except discord.NotFound:
                pass  # A genuinely deleted message can be recreated.
            except (discord.Forbidden, discord.HTTPException):
                raise ValueError("Impossible de vérifier le précédent panneau. Aucune publication en double.")
            else:
                if former_channel_id == str(channel.id):
                    if module == "tickets" and previous.get("games", []) != enabled_games(cfg):
                        # Updating our own panel preserves the original message and ID.
                        await former_message.edit(
                            content=panel_message(module, cfg),
                            view=make_panel_view(module, gid, cfg),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        previous["games"] = enabled_games(cfg)
                        state.save()
                        return "done", "Boutons de recrutement actualisés sur le panneau existant.", previous
                    return "skipped", "Panneau déjà publié et vérifié dans ce salon.", previous
                raise ValueError("Un panneau existe dans un autre salon : supprime-le d'abord ou conserve son emplacement.")
        else:
            raise ValueError("L'ancien panneau a des identifiants incomplets : vérifie-le manuellement.")
    button_view = make_panel_view(module, gid, cfg)
    message = await channel.send(panel_message(module, cfg), view=button_view,
                                 allowed_mentions=discord.AllowedMentions.none())
    saved = {"channel_id": str(channel.id), "message_id": str(message.id)}
    if module == "tickets":
        saved["games"] = enabled_games(cfg)
    records[gid] = saved
    state.save()
    if records.get(gid) != saved:
        raise ValueError("La référence du panneau n'a pas été conservée.")
    return "done", "Panneau interactif publié, ID du message enregistré.", saved

def panel_message(module: str, cfg: dict) -> str:
    if module == "tickets" and enabled_games(cfg):
        return ("🎟️ **Support et recrutement esport** — choisis le jeu pour ouvrir un "
                "salon privé visible uniquement par toi, le support et le bot.")
    return PANEL_SPECS[module]["message"]


def make_panel_view(module: str, guild_id: str, cfg: dict) -> discord.ui.View:
    spec = PANEL_SPECS[module]
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label=spec["label"], style=spec["button_style"],
        custom_id=f"{spec['custom_prefix']}:{guild_id}", emoji=spec["emoji"]))
    if module == "tickets":
        for game in enabled_games(cfg):
            view.add_item(discord.ui.Button(
                label=GAME_LABELS[game], style=discord.ButtonStyle.secondary,
                custom_id=f"pilot:ticket:open:{guild_id}:{game}",
            ))
    return view
