"""Small allowlisted executor. No arbitrary Discord code, shell, or eval."""

from __future__ import annotations

import discord

from planner import norm


class NotFoundOrAmbiguous(ValueError):
    pass


def find_unique(items, name: str, description: str):
    matches = [item for item in items if norm(item.name) == norm(name)]
    if not matches:
        raise NotFoundOrAmbiguous(f"{description} « {name} » introuvable.")
    if len(matches) > 1:
        raise NotFoundOrAmbiguous(f"Plusieurs {description.lower()}s se nomment « {name} » : précise un identifiant.")
    return matches[0]


def role_by_name(guild, name: str):
    return find_unique(guild.roles, name, "Rôle")


def channel_by_name(guild, name: str):
    target = norm(name.lstrip("#"))
    # Discord exposes categories in guild.channels too.  A category and a
    # text channel may legitimately have the same name; only rooms qualify.
    category_ids = {category.id for category in getattr(guild, "categories", [])}
    eligible = [channel for channel in guild.channels if channel.id not in category_ids]
    exact = [channel for channel in eligible if norm(channel.name) == target]
    if exact:
        return find_unique(exact, exact[0].name, "Salon")
    # Common dictation variants for the built-in welcome room.
    if target in {"bienvenu", "bienvenue"}:
        welcome_matches = [channel for channel in eligible
                           if norm(channel.name) in {"bienvenu", "bienvenue"}]
        if len(welcome_matches) == 1:
            return welcome_matches[0]
        if len(welcome_matches) > 1:
            raise NotFoundOrAmbiguous("Plusieurs salons de bienvenue existent : choisis le nom exact.")
    # Discord converts spaces to hyphens in text-channel names.
    slug = target.replace(" ", "-").replace("_", "-")
    matches = [channel for channel in eligible
               if norm(channel.name).replace(" ", "-").replace("_", "-") == slug]
    if not matches:
        raise NotFoundOrAmbiguous(f"Salon « {name} » introuvable.")
    if len(matches) > 1:
        raise NotFoundOrAmbiguous(f"Plusieurs salons correspondent à « {name} ».")
    return matches[0]


def category_by_name(guild, name: str):
    return find_unique(guild.categories, name, "Catégorie")


async def execute_action(guild: discord.Guild, item: dict, state=None, created=None) -> tuple[str, str]:
    """Returns (done|skipped, human-readable detail). Permission errors bubble up."""
    t = item["type"]
    reason = "Discord Pilot — modification confirmée depuis l'application locale"
    created = created if created is not None else {"channels": {}, "roles": {}, "categories": {}}

    def get_channel(name):
        if name.isdigit():
            found = guild.get_channel(int(name))
            if found is not None:
                return found
        return created["channels"].get(norm(name)) or channel_by_name(guild, name)

    def get_role(name):
        if name.isdigit():
            found = guild.get_role(int(name))
            if found is not None:
                return found
        return created["roles"].get(norm(name)) or role_by_name(guild, name)

    def get_category(name):
        return created["categories"].get(norm(name)) or category_by_name(guild, name)
    if t in {"configure_welcome", "configure_farewell", "configure_invites"}:
        if state is None:
            raise ValueError("Stockage des automatisations indisponible.")
        channel = get_channel(item["channel"])
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Les messages automatiques exigent un salon textuel.")
        kind = t.removeprefix("configure_")
        changed = state.set_automation(str(guild.id), kind, str(channel.id))
        if not changed:
            return "skipped", "Cette automatisation utilise déjà ce salon."
        return "done", ("Automatisation enregistrée : elle fonctionne lorsque le bot local est connecté "
                        "avec l'intent Server Members activé dans Discord Developer Portal.")
    if t == "create_category":
        existing = [c for c in guild.categories if norm(c.name) == norm(item["name"])]
        if existing:
            return "skipped", "Cette catégorie existe déjà."
        result = await guild.create_category(item["name"], reason=reason)
        created["categories"][norm(item["name"])] = result
        return "done", f"Catégorie créée (ID {result.id})."
    if t in {"create_text_channel", "create_voice_channel"}:
        category = get_category(item["category"]) if item.get("category") else None
        existing = [c for c in guild.channels
                    if norm(c.name) == norm(item["name"])
                    and c.category_id == (category.id if category else None)
                    and isinstance(c, discord.VoiceChannel if t == "create_voice_channel" else discord.TextChannel)]
        if existing:
            return "skipped", "Ce salon existe déjà dans cette catégorie."
        if t == "create_voice_channel":
            result = await guild.create_voice_channel(item["name"], category=category, reason=reason)
        else:
            result = await guild.create_text_channel(item["name"], category=category,
                                                     topic=item.get("topic"), reason=reason)
        created["channels"][norm(item["name"])] = result
        return "done", f"Salon créé (ID {result.id})."
    if t == "create_role":
        existing = [r for r in guild.roles if norm(r.name) == norm(item["name"])]
        if existing:
            return "skipped", "Ce rôle existe déjà."
        color = item.get("color")
        kwargs = {}
        if color:
            if len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
                raise ValueError("La couleur doit être au format #RRGGBB.")
            kwargs["colour"] = discord.Colour(int(color[1:], 16))
        result = await guild.create_role(name=item["name"], permissions=discord.Permissions.none(),
                                         reason=reason, **kwargs)
        created["roles"][norm(item["name"])] = result
        return "done", f"Rôle créé sans permissions sensibles (ID {result.id})."
    if t == "rename_channel":
        channel = get_channel(item["name"])
        if channel.name == item["new_name"]:
            return "skipped", "Le salon porte déjà ce nom."
        await channel.edit(name=item["new_name"], reason=reason)
        created["channels"].pop(norm(item["name"]), None)
        created["channels"][norm(item["new_name"])] = channel
        return "done", "Salon renommé."
    if t == "rename_role":
        role = get_role(item["name"])
        if role.is_default() or role.managed:
            raise ValueError("Un rôle système ne peut pas être renommé.")
        if role.name == item["new_name"]:
            return "skipped", "Le rôle porte déjà ce nom."
        await role.edit(name=item["new_name"], reason=reason)
        created["roles"].pop(norm(item["name"]), None)
        created["roles"][norm(item["new_name"])] = role
        return "done", "Rôle renommé."
    if t == "set_topic":
        channel = get_channel(item["name"])
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("La description concerne les salons textuels.")
        if channel.topic == item["topic"]:
            return "skipped", "Description déjà identique."
        await channel.edit(topic=item["topic"], reason=reason)
        return "done", "Description mise à jour."
    if t == "send_message":
        channel = get_channel(item["channel"])
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Un message ne peut être publié que dans un salon textuel.")
        msg = await channel.send(item["content"], allowed_mentions=discord.AllowedMentions.none())
        return "done", f"Message publié (ID {msg.id}), sans mention automatique."
    if t == "make_private":
        channel = get_channel(item["name"])
        role = get_role(item["role"])
        if role.is_default():
            raise ValueError("Le rôle @everyone ne peut pas être l'exception d'un salon privé.")
        everyone = guild.default_role
        every_overwrite = channel.overwrites_for(everyone)
        role_overwrite = channel.overwrites_for(role)
        if every_overwrite.view_channel is False and role_overwrite.view_channel is True:
            return "skipped", "Ce salon est déjà privé pour ce rôle."
        every_overwrite.view_channel = False
        role_overwrite.view_channel = True
        # Keep the bot's access even after @everyone loses access.
        if guild.me:
            bot_overwrite = channel.overwrites_for(guild.me)
            bot_overwrite.view_channel = True
            await channel.set_permissions(guild.me, overwrite=bot_overwrite, reason=reason)
        await channel.set_permissions(role, overwrite=role_overwrite, reason=reason)
        await channel.set_permissions(everyone, overwrite=every_overwrite, reason=reason)
        return "done", "Accès fermé à @everyone et autorisé au rôle choisi."
    if t == "lock_channel_writing":
        channel = get_channel(item["name"])
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("La lecture seule concerne les salons textuels uniquement.")
        flags = ("send_messages", "send_messages_in_threads",
                 "create_public_threads", "create_private_threads")
        changes = 0
        for role in guild.roles:
            if not role.is_default() and (role.managed or role.permissions.administrator):
                # Preserve managed integrations and administrator bypasses.
                continue
            overwrite = channel.overwrites_for(role)
            if role.is_default():
                requires_update = any(getattr(overwrite, key) is not False for key in flags)
            else:
                requires_update = any(getattr(overwrite, key) is True for key in flags)
            if requires_update:
                for key in flags:
                    if role.is_default() or getattr(overwrite, key) is True:
                        setattr(overwrite, key, False)
                await channel.set_permissions(role, overwrite=overwrite, reason=reason)
                changes += 1
        for target in channel.overwrites:
            if target in guild.roles or getattr(target, "bot", False):
                continue
            if getattr(getattr(target, "guild_permissions", None), "administrator", False):
                continue
            overwrite = channel.overwrites_for(target)
            if any(getattr(overwrite, key) is True for key in flags):
                for key in flags:
                    if getattr(overwrite, key) is True:
                        setattr(overwrite, key, False)
                await channel.set_permissions(target, overwrite=overwrite, reason=reason)
                changes += 1
        if guild.me:
            bot_overwrite = channel.overwrites_for(guild.me)
            if bot_overwrite.send_messages is not True or bot_overwrite.send_messages_in_threads is not True:
                bot_overwrite.send_messages = True
                bot_overwrite.send_messages_in_threads = True
                await channel.set_permissions(guild.me, overwrite=bot_overwrite, reason=reason)
                changes += 1
        if changes == 0:
            return "skipped", "Ce salon est déjà en lecture seule pour les membres non administrateurs."
        return "done", (f"Lecture seule appliquée : {changes} réglage(s). Visibilité inchangée. "
                        "Vérifie les permissions des autres bots automatisés si nécessaire.")
    if t in {"set_channel_role_access", "set_role_access"}:
        channel = (guild.get_channel(int(item["channel_id"])) if t == "set_channel_role_access"
                   else get_channel(item["channel"]))
        role = (guild.get_role(int(item["role_id"])) if t == "set_channel_role_access"
                else get_role(item["role"]))
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            raise ValueError("Ce salon n'existe plus ou n'est pas textuel/vocal sur ce serveur.")
        if role is None or getattr(role, "managed", False):
            raise ValueError("Le rôle choisi n'existe plus ou est géré par une autre intégration.")
        choices = {"allow": True, "deny": False, "inherit": None}
        overwrite = channel.overwrites_for(role)
        changed = False
        if item["view"] != "keep":
            target = choices[item["view"]]
            changed = changed or overwrite.view_channel is not target
            overwrite.view_channel = target
        permission = "send_messages" if isinstance(channel, discord.TextChannel) else "connect"
        if item["participate"] != "keep":
            target = choices[item["participate"]]
            changed = changed or getattr(overwrite, permission) is not target
            setattr(overwrite, permission, target)
        if not changed:
            return "skipped", "Ces permissions sont déjà configurées pour ce rôle."
        await channel.set_permissions(role, overwrite=overwrite, reason=reason)
        return "done", "Permissions de visibilité et d'écriture/connexion mises à jour pour le rôle choisi."
    if t == "delete_channel":
        channel = get_channel(item["name"])
        await channel.delete(reason=reason)
        created["channels"].pop(norm(item["name"]), None)
        return "done", "Salon supprimé (action irréversible)."
    if t == "delete_role":
        role = get_role(item["name"])
        if role.is_default() or role.managed:
            raise ValueError("Impossible de supprimer un rôle système.")
        await role.delete(reason=reason)
        created["roles"].pop(norm(item["name"]), None)
        return "done", "Rôle supprimé (action irréversible)."
    raise ValueError("Action inconnue.")
