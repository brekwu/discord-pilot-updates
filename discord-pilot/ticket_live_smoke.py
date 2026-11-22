"""Explicit active Discord ticket infrastructure smoke test, no fake applicant.

Requires a user click; creates ONE private temporary room under the configured
ticket category; verifies access, sending, reading, archiving and cleanup.
Never modifies persistent application tickets or existing rooms/roles/panels.
"""
from __future__ import annotations

import secrets

import discord

from community_modules import normalize_module


async def smoke_test_ticket(guild, state) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if guild is None or getattr(guild, "me", None) is None:
        return {"status": "blocked", "checks": checks,
                "detail": "Bot non connecté au serveur sélectionné.",
                "requires_user_click_test": True}

    cfg = state.module(str(guild.id), "tickets")
    if not cfg.get("enabled"):
        return {"status": "blocked", "checks": checks,
                "detail": "Module tickets désactivé : aucun salon de test créé.",
                "requires_user_click_test": True}
    try:
        cfg = normalize_module("tickets", cfg, guild)
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "blocked", "checks": checks, "detail": str(exc),
                "requires_user_click_test": True}
    me = guild.me
    permissions = me.guild_permissions
    if not getattr(permissions, "manage_channels", False):
        return {"status": "blocked", "checks": checks,
                "detail": "Permission Gérer les salons absente : aucun test effectué.",
                "requires_user_click_test": True}
    category = guild.get_channel(int(cfg["category_id"]))
    if not isinstance(category, discord.CategoryChannel):
        return {"status": "blocked", "checks": checks,
                "detail": "Catégorie de tickets manquante : aucun test effectué.",
                "requires_user_click_test": True}
    staff_id = cfg.get("staff_role_id", "")
    staff = guild.get_role(int(staff_id)) if staff_id else None
    if not staff or staff.is_default():
        return {"status": "blocked", "checks": checks,
                "detail": "Configure un vrai rôle staff avant le test de confidentialité.",
                "requires_user_click_test": True}

    name = "pilot-ticket-test-" + secrets.token_hex(3)
    channel = None
    failed = False
    cleanup_failed = False
    try:
        channel = await guild.create_text_channel(
            name, category=category, overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                staff: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                    read_message_history=True),
                me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                read_message_history=True, manage_channels=True),
            },
            reason="Discord Pilot : test technique de ticket explicitement lancé",
        )
        check("Création temporaire", True,
              f"Salon de test privé créé (ID {channel.id}).")
        everyone_hidden = not channel.permissions_for(guild.default_role).view_channel
        staff_visible = bool(channel.permissions_for(staff).view_channel and
                             channel.permissions_for(staff).send_messages)
        bot_visible = bool(channel.permissions_for(me).view_channel and
                           channel.permissions_for(me).send_messages)
        check("Confidentialité @everyone", everyone_hidden,
              "Le public ne voit pas le salon." if everyone_hidden
              else "Le public peut voir le salon : configuration à corriger.")
        check("Accès du staff", staff_visible,
              "Le staff peut lire et écrire." if staff_visible
              else "Le staff n'a pas les accès de lecture/écriture attendus.")
        check("Accès du bot", bot_visible,
              "Le bot peut lire et écrire." if bot_visible
              else "Le bot ne peut pas lire et écrire.")
        if not (everyone_hidden and staff_visible and bot_visible):
            failed = True
        else:
            marker = "Test technique Discord Pilot : ticket temporaire, ne pas répondre."
            msg = await channel.send(marker, allowed_mentions=discord.AllowedMentions.none())
            saved = await channel.fetch_message(msg.id)
            ok = saved.id == msg.id and saved.content == marker
            check("Envoi et lecture Discord", ok,
                  "Message de test retrouvé sur Discord." if ok
                  else "Message de test non retrouvé ou altéré.")
            if not ok:
                failed = True
            else:
                archived = await channel.edit(
                    name="archive-" + name,
                    reason="Discord Pilot : test technique d'archivage temporaire",
                )
                ok_archived = bool(archived and archived.name.startswith("archive-"))
                check("Archivage technique", ok_archived,
                      "Discord confirme le renommage d'archive." if ok_archived
                      else "Discord n'a pas confirmé le renommage d'archive.")
                if not ok_archived:
                    failed = True
    except (discord.DiscordException, OSError, ValueError) as exc:
        failed = True
        check("Test technique", False, f"Discord a refusé une étape ({type(exc).__name__}).")
    finally:
        if channel is not None:
            try:
                await channel.delete(reason="Discord Pilot : nettoyage du ticket temporaire")
                check("Nettoyage", True, "Salon temporaire supprimé.")
            except (discord.DiscordException, OSError) as exc:
                cleanup_failed = True
                check("Nettoyage", False,
                      f"Suppression impossible ({type(exc).__name__}) : supprimer "
                      f"manuellement le salon ID {channel.id}.")

    return {
        "status": "verified_technical_only" if not failed and not cleanup_failed else "failed",
        "checks": checks,
        "requires_user_click_test": True,
        "detail": ("Test technique d'infrastructure passé ; un candidat doit encore "
                   "cliquer sur le vrai bouton, ouvrir et fermer son ticket."
                   if not failed and not cleanup_failed else
                   "Test incomplet ou nettoyage échoué : vérifier les contrôles ci-dessus."),
    }
