"""Explicit live Discord smoke checks from the user's locally connected bot.

The read-only mode uses authenticated Discord HTTP fetches. The active mode
creates a private temporary room, sends and re-reads one message, then removes
only that room. The result distinguishes verified actions and cleanup errors.
"""

from __future__ import annotations

import secrets

import discord


async def inspect_guild(guild, active: bool = False) -> dict:
    me = guild.me
    if me is None:
        raise ValueError("Discord n'a pas encore fourni l'identité du bot sur ce serveur.")
    channels = await guild.fetch_channels()
    roles = await guild.fetch_roles()
    result = {
        "server_id": str(guild.id),
        "server_name": guild.name,
        "mode": "active" if active else "read_only",
        "status": "verified",
        "checks": [
            {"name": "Connexion API Discord", "ok": True,
             "detail": f"{len(channels)} salons et {len(roles)} rôles lus via Discord."},
            {"name": "Permission Gérer les salons", "ok": bool(me.guild_permissions.manage_channels),
             "detail": "Nécessaire pour créer les salons et ouvrir les tickets."},
            {"name": "Permission Envoyer des messages", "ok": bool(me.guild_permissions.send_messages),
             "detail": "Nécessaire pour les annonces et les panneaux interactifs."},
        ],
    }
    if not active:
        result["status"] = "verified" if all(c["ok"] for c in result["checks"]) else "warning"
        return result
    if not me.guild_permissions.manage_channels or not me.guild_permissions.send_messages:
        result["status"] = "blocked"
        result["checks"].append({"name": "Test actif", "ok": False,
                                 "detail": "Permissions insuffisantes. Aucun salon de test créé."})
        return result
    temporary = None
    run_error = None
    cleanup_error = None
    try:
        name = f"discordpilot-test-{secrets.token_hex(3)}"
        temporary = await guild.create_text_channel(
            name,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                read_message_history=True),
            },
            reason="Discord Pilot — test actif explicitement demandé dans l'application")
        result["checks"].append({"name": "Création privée", "ok": True,
                                 "detail": f"Salon temporaire {name} (ID {temporary.id})."})
        sent = await temporary.send("Test technique Discord Pilot : message temporaire.",
                                    allowed_mentions=discord.AllowedMentions.none())
        actual = await temporary.fetch_message(sent.id)
        if actual.id != sent.id:
            raise ValueError("Discord a renvoyé un identifiant de message différent.")
        result["checks"].append({"name": "Écriture et lecture du message", "ok": True,
                                 "detail": f"Message {sent.id} retrouvé via Discord."})
    except (discord.DiscordException, ValueError, OSError) as exc:
        run_error = type(exc).__name__
        result["checks"].append({"name": "Test actif", "ok": False,
                                 "detail": f"Échec de l'opération Discord : {run_error}."})
    finally:
        if temporary is not None:
            try:
                await temporary.delete(reason="Discord Pilot — nettoyage du salon temporaire de test")
                result["checks"].append({"name": "Nettoyage du salon temporaire", "ok": True,
                                         "detail": "Salon de test supprimé de Discord."})
            except (discord.DiscordException, OSError) as exc:
                cleanup_error = type(exc).__name__
                result["checks"].append({"name": "Nettoyage du salon temporaire", "ok": False,
                    "detail": f"Échec de suppression ({cleanup_error}) : vérifie manuellement le salon {temporary.name} (ID {temporary.id})."})
    result["status"] = "verified" if not run_error and not cleanup_error else "failed"
    return result
