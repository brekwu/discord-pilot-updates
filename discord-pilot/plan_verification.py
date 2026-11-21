"""Read back actual Discord resources after an approved configuration plan.

Batch REST reads once per plan to avoid one expensive guild request per action.
A checked cache, local configuration, and a live Discord REST confirmation have
different assurance levels; do not present them as interchangeable.
"""
from __future__ import annotations

import re
from planner import norm


def _find(items, name, label):
    target = norm(str(name).lstrip("#@"))
    matches = [o for o in items if (str(o.id) == str(name) or norm(o.name) == target)]
    if len(matches) != 1:
        return None, f"{label} absent ou ambigu après exécution."
    return matches[0], None


def _permission(channel, target, field):
    overwrite = channel.overwrites_for(target)
    return getattr(overwrite, field)


def _target_channel(item, channels):
    key = item.get("channel_id") or item.get("channel") or item.get("name")
    return _find([c for c in channels if str(getattr(c, "type", "")) != "category"], key, "Salon")


def _role(item, roles):
    return _find(roles, item.get("role_id") or item.get("role"), "Rôle")


def _value(raw):
    return {"allow": True, "deny": False, "inherit": None}.get(raw)


async def _check(item, row, guild, state, channels, roles):
    kind = item["type"]
    gid = str(guild.id)
    if kind == "suggest_integration":
        return "not_applicable", "Autorisation externe requise : non vérifiable automatiquement."
    if kind == "set_module":
        cfg = state.module(gid, item["module"])
        match = cfg.get("enabled") is (item["enabled"] == "true")
        return ("verified" if match else "mismatch"), "Configuration enregistrée." if match else "État du module non conforme."
    if kind == "configure_module":
        cfg = state.module(gid, item["module"])
        if cfg.get("enabled") is not (item["enabled"] == "true"):
            return "mismatch", "Le module n'est pas dans l'état demandé."
        return "local_only", "Paramètres enregistrés ; fonctionnement des événements à tester avec un utilisateur."
    if kind in {"configure_welcome", "configure_farewell", "configure_invites"}:
        channel, err = _find(channels or [], item["channel"], "Salon")
        if err:
            return "mismatch" if channels is not None else "unverified", err
        saved = state.automation_channel(gid, kind.removeprefix("configure_"))
        return ("local_only" if saved == str(channel.id) else "mismatch"), (
            "Automatisation enregistrée ; déclenchement réel non testé." if saved == str(channel.id)
            else "La configuration enregistrée est incorrecte.")
    if kind in {"publish_ticket_panel", "publish_application_panel"}:
        module = "tickets" if kind == "publish_ticket_panel" else "applications"
        key = "ticket_panels" if module == "tickets" else "application_panels"
        saved = state.state.get(key, {}).get(gid)
        if not saved:
            return "mismatch", "Aucune référence du panneau enregistré."
        channel, err = _find(channels or [], saved.get("channel_id", ""), "Salon du panneau")
        if err:
            return "mismatch" if channels is not None else "unverified", err
        try:
            msg = await channel.fetch_message(int(saved["message_id"]))
        except Exception as exc:
            return "unverified", f"Lecture du panneau impossible ({type(exc).__name__})."
        prefix = "pilot:ticket:open:" if module == "tickets" else "pilot:application:open:"
        buttons = [getattr(button, "custom_id", None) for block in msg.components
                   for button in getattr(block, "children", ())]
        good = any(isinstance(x, str) and x.startswith(prefix) for x in buttons)
        return ("verified" if good else "mismatch"), (
            "Panneau et bouton retrouvés sur Discord." if good else "Message présent mais bouton interactif absent.")
    if kind in {"create_role", "rename_role", "delete_role"}:
        if roles is None:
            return "unverified", "Lecture des rôles via l'API Discord indisponible."
        if kind == "delete_role":
            found, _ = _find(roles, item["name"], "Rôle")
            return ("verified" if found is None else "mismatch"), (
                "Rôle absent du serveur." if found is None else "Le rôle est encore présent.")
        found, err = _find(roles, item.get("new_name", item["name"]), "Rôle")
        return ("verified" if found else "mismatch"), "Rôle confirmé sur Discord." if found else err
    if kind in {"create_category", "create_text_channel", "create_voice_channel",
                "create_private_text_channel", "rename_channel", "set_topic",
                "make_private", "lock_channel_writing", "set_role_access",
                "set_channel_role_access", "delete_channel", "send_message"}:
        if channels is None:
            return "unverified", "Lecture des salons via l'API Discord indisponible."
        if kind == "create_category":
            found, err = _find([c for c in channels if str(getattr(c, "type", "")) == "category"],
                               item["name"], "Catégorie")
            return ("verified" if found else "mismatch"), "Catégorie confirmée sur Discord." if found else err
        if kind == "delete_channel":
            found, _ = _target_channel(item, channels)
            return ("verified" if found is None else "mismatch"), (
                "Salon absent du serveur." if found is None else "Salon encore présent sur Discord.")
        channel, err = _find([c for c in channels if str(getattr(c, "type", "")) != "category"],
                             item.get("new_name", item.get("channel_id", item.get("channel", item.get("name")))), "Salon")
        if err:
            return "mismatch", err
        if kind in {"create_text_channel", "create_voice_channel", "create_private_text_channel"}:
            expected = "voice" if kind == "create_voice_channel" else "text"
            if str(channel.type) != expected:
                return "mismatch", "Type de salon incorrect."
            if item.get("category"):
                category = next((c for c in channels if str(getattr(c, "type", "")) == "category"
                                 and norm(c.name) == norm(item["category"])), None)
                if not category or getattr(channel, "category_id", None) != category.id:
                    return "mismatch", "Salon créé dans la mauvaise catégorie."
            if kind == "create_private_text_channel":
                role, error = _role(item, roles or [])
                if error or _permission(channel, guild.default_role, "view_channel") is not False or (
                        _permission(channel, role, "view_channel") is not True):
                    return "mismatch", "La confidentialité du salon staff n'est pas conforme."
            return "verified", "Salon et catégorie confirmés sur Discord."
        if kind == "set_topic":
            equal = channel.topic == item["topic"]
            return ("verified" if equal else "mismatch"), "Description confirmée." if equal else "Description différente."
        if kind == "make_private":
            role, err = _role(item, roles or [])
            valid = not err and _permission(channel, guild.default_role, "view_channel") is False and (
                _permission(channel, role, "view_channel") is True)
            return ("verified" if valid else "mismatch"), (
                "Confidentialité confirmée." if valid else "Accès privé non conforme.")
        if kind == "lock_channel_writing":
            flags = ("send_messages", "send_messages_in_threads", "create_public_threads", "create_private_threads")
            base = all(_permission(channel, guild.default_role, f) is False for f in flags)
            grants = any(not r.is_default() and not r.permissions.administrator and
                         not getattr(r, "managed", False) and
                         any(_permission(channel, r, f) is True for f in flags) for r in (roles or []))
            return ("verified" if base and not grants else "mismatch"), (
                "Lecture seule confirmée." if base and not grants else "Un membre peut encore publier.")
        if kind in {"set_role_access", "set_channel_role_access"}:
            role, err = _role(item, roles or [])
            if err:
                return "mismatch", err
            field = "send_messages" if str(channel.type) == "text" else "connect"
            checks = [(key, flag) for key, flag in (("view", "view_channel"), ("participate", field))
                      if item[key] != "keep"]
            passed = all(_permission(channel, role, field_name) is _value(item[key])
                         for key, field_name in checks)
            return ("verified" if passed else "mismatch"), (
                "Permissions vérifiées sur Discord." if passed else "Permissions différentes de la demande.")
        if kind == "send_message":
            match = re.search(r"ID (\d{17,20})", row.get("detail", ""))
            if not match:
                return "unverified", "Impossible de retrouver l'identifiant du message."
            try:
                message = await channel.fetch_message(int(match.group(1)))
            except Exception as exc:
                return "unverified", f"Lecture du message impossible ({type(exc).__name__})."
            return ("verified" if message.content == item["content"] else "mismatch"), (
                "Message confirmé sur Discord." if message.content == item["content"]
                else "Contenu publié différent.")
        return "verified", "Modification confirmée sur Discord."
    return "unverified", "Cette action n'a pas encore de vérification automatique."


async def verify_plan(guild, plan, state) -> dict:
    """Attach per-action readback evidence; never claim validation on API error."""
    rows = plan.get("results", [])
    active = [(plan["actions"][row["index"]], row) for row in rows
              if row.get("status") in {"done", "skipped"}]
    if not active:
        return {"verified": 0, "mismatch": 0, "unverified": 0, "local_only": 0}
    needs_channels = any(item["type"] not in {"create_role", "rename_role", "delete_role", "set_module",
                                             "configure_module", "suggest_integration"} for item, _ in active)
    needs_roles = any(item["type"] in {"create_role", "rename_role", "delete_role",
                                     "create_private_text_channel", "make_private",
                                     "set_role_access", "set_channel_role_access",
                                     "lock_channel_writing"} for item, _ in active)
    channels, roles = [], []
    if needs_channels:
        try:
            channels = await guild.fetch_channels()
        except Exception:
            channels = None
    if needs_roles:
        try:
            roles = await guild.fetch_roles()
        except Exception:
            roles = None
    result = {"verified": 0, "mismatch": 0, "unverified": 0, "local_only": 0}
    for item, row in active:
        try:
            level, detail = await _check(item, row, guild, state, channels, roles)
        except Exception as exc:
            level, detail = "unverified", f"Contrôle impossible ({type(exc).__name__})."
        row["verification"] = {"status": level, "detail": detail}
        row["detail"] += f" | Vérification : {detail}"
        if level in result:
            result[level] += 1
    return result
