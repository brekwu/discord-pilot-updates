"""Read-only validation of Discord Pilot's live ticket panel and permissions.

A passing result means ready for a REAL user click, not an E2E ticket validation.
Never create, edit, delete, or publish a Discord object in this diagnostic.
"""
from __future__ import annotations

import discord

from community_modules import normalize_module
from recruitment_tickets import GAME_LABELS, enabled_games


async def inspect_ticket_panel(guild, state) -> dict:
    checks: list[dict] = []
    gid = str(guild.id) if guild else ""
    games: list[str] = []

    def check(code: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "ok": bool(ok), "detail": detail})

    if guild is None:
        check("bot", False, "Le bot n'est pas connecté au serveur sélectionné.")
        return {"status": "offline", "checks": checks, "games": games,
                "requires_interaction_test": True}

    check("bot", True, "Bot présent sur le serveur Discord sélectionné.")
    config = state.module(gid, "tickets")
    if not config.get("enabled"):
        check("module", False, "Le module de tickets est désactivé.")
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}
    try:
        cfg = normalize_module("tickets", config, guild)
        games = enabled_games(cfg)
        check("configuration", True, "Configuration Discord et paramètres des tickets cohérents.")
    except (ValueError, KeyError, TypeError) as exc:
        check("configuration", False, str(exc))
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}

    member = getattr(guild, "me", None)
    permissions = getattr(member, "guild_permissions", None)
    can_create = bool(getattr(permissions, "manage_channels", False) or
                      getattr(permissions, "administrator", False))
    check("create_channels", can_create,
          "Le bot peut créer les salons privés." if can_create
          else "Permission Gérer les salons absente : impossible d'ouvrir les tickets.")

    staff_id = cfg.get("staff_role_id", "")
    staff = guild.get_role(int(staff_id)) if staff_id else None
    if games:
        check("staff", bool(staff and not staff.is_default()),
              "Rôle staff du recrutement trouvé." if staff and not staff.is_default()
              else "Configure un rôle staff valide pour le recrutement.")
    else:
        check("staff", True, "Mode support générique ; rôle staff facultatif.")

    channel = guild.get_channel(int(cfg["panel_channel_id"]))
    valid_channel = isinstance(channel, discord.TextChannel)
    check("panel_channel", valid_channel,
          "Salon public des tickets présent." if valid_channel
          else "Salon du panneau introuvable ou non textuel.")

    if not valid_channel:
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}

    effective = channel.permissions_for(member) if member is not None else None
    can_read = bool(effective and getattr(effective, "view_channel", False) and
                    getattr(effective, "read_message_history", False))
    can_send = bool(effective and getattr(effective, "send_messages", False))
    check("read_panel", can_read,
          "Le bot peut lire le panneau." if can_read
          else "Le bot ne peut pas lire ce salon ou son historique.")
    check("send_panel", can_send,
          "Le bot peut publier dans le salon." if can_send
          else "Le bot ne peut pas publier dans le salon du panneau.")

    record = state.state.get("ticket_panels", {}).get(gid)
    if not isinstance(record, dict) or record.get("channel_id") != str(channel.id):
        check("panel_record", False,
              "Panneau non enregistré ou enregistré dans un autre salon : publie-le.")
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}
    message_id = record.get("message_id", "")
    if not isinstance(message_id, str) or not message_id.isdigit():
        check("panel_record", False, "Identifiant du message du panneau invalide.")
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}

    if not can_read:
        check("live_message", False, "Lecture Discord refusée avant toute requête.")
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}
    try:
        message = await channel.fetch_message(int(message_id))
    except discord.NotFound:
        check("live_message", False, "Le panneau a été supprimé sur Discord.")
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}
    except (discord.Forbidden, discord.HTTPException):
        check("live_message", False,
              "Discord refuse la lecture du message du panneau ; aucun changement tenté.")
        return {"status": "attention", "checks": checks, "games": games,
                "requires_interaction_test": True}

    check("live_message", True, "Message du panneau retrouvé dans Discord.")
    expected = {f"pilot:ticket:open:{gid}"}
    expected.update(f"pilot:ticket:open:{gid}:{game}" for game in games)
    observed = {
        getattr(button, "custom_id", None)
        for row in getattr(message, "components", ())
        for button in getattr(row, "children", ())
    }
    valid_buttons = expected <= observed
    check("buttons", valid_buttons,
          "Boutons du support et des jeux présents dans le message publié."
          if valid_buttons else "Boutons absents ou non à jour : republie le panneau existant.")
    record_games = record.get("games", [])
    check("recorded_games", record_games == games,
          "Liste des jeux synchronisée avec le panneau." if record_games == games
          else "Les jeux enregistrés ne correspondent pas à la configuration actuelle.")

    return {"status": "ready_for_manual_test" if all(c["ok"] for c in checks)
            else "attention", "checks": checks, "games": games,
            "requires_interaction_test": True}
