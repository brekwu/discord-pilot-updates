"""Opt-in, locally executed Discord community modules.

Every module is disabled by default.  This module contains the strict settings
schema and deterministic, testable state transitions; network effects are in
PilotBot.  External services and music providers are deliberately not claimed
as part of these native modules.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
import re
import time
from zoneinfo import ZoneInfo
from recruitment_tickets import normalize_recruitment_games


MODULES = {
    "autorole": {"title": "Rôle automatique", "icon": "🎭", "description": "Attribue un rôle à chaque nouvel arrivant.",
                 "fields": [("role_id", "role", "Rôle attribué")], "requires": "members"},
    "xp": {"title": "XP et classement", "icon": "🏆", "description": "10 XP par message valide, une fois par minute et par personne, avec niveaux et classement.",
           "fields": [("channel_id", "optional_text", "Salon des annonces de niveau (facultatif)")]},
    "level_rewards": {"title": "Récompense de niveau", "icon": "🎖️", "description": "Attribue un rôle lorsque le membre atteint le niveau XP indiqué. Le module XP doit aussi être actif.",
                      "fields": [("level", "positive_int", "Niveau requis (1 à 1 000)"),
                                 ("role_id", "role", "Rôle récompense")]},
    "invite_rewards": {"title": "Récompense d'invitations", "icon": "🎉", "description": "Attribue un rôle à l'invitant après le nombre d'arrivées identifiées indiqué. Les invitations non attribuables ne comptent pas.",
                       "fields": [("invites", "positive_int", "Invitations requises (1 à 1 000)"),
                                  ("role_id", "role", "Rôle récompense")], "requires": "members"},
    "activity_stats": {"title": "Statistiques des messages", "icon": "📈", "description": "Compte les messages reçus pendant la connexion du bot, sans enregistrer leur contenu. Affiche un classement dans le tableau de bord.",
                       "fields": []},
    "warnings": {"title": "Avertissements manuels", "icon": "⚠️", "description": "Permet à l'administrateur local d'enregistrer un avertissement et d'envoyer un journal privé. Aucune sanction automatique.",
                 "fields": [("channel_id", "private_text", "Salon privé des avertissements")]},
    "antispam": {"title": "Anti-spam", "icon": "🛡️", "description": "Supprime le 6e message en 8 secondes et applique une pause de 60 secondes si autorisé.",
                 "fields": []},
    "antilinks": {"title": "Anti-liens", "icon": "🔗", "description": "Supprime les messages contenant des liens externes, hors modérateurs.",
                  "fields": [], "requires": "content"},
    "wordfilter": {"title": "Filtre de mots", "icon": "🚫", "description": "Supprime les messages contenant des mots ou expressions configurés.",
                    "fields": [("words", "words", "Mots séparés par des virgules")], "requires": "content"},
    "audit": {"title": "Journal des messages", "icon": "📋", "description": "Signale les suppressions et modifications dans un salon privé choisi.",
              "fields": [("channel_id", "text", "Salon des journaux")]},
    "suggestions": {"title": "Votes et suggestions", "icon": "💡", "description": "Ajoute automatiquement 👍 et 👎 à chaque proposition dans un salon.",
                    "fields": [("channel_id", "text", "Salon des suggestions")]},
    "voice_rooms": {"title": "Salons vocaux temporaires", "icon": "🎙️", "description": "Créer un vocal quand un membre rejoint le salon d'entrée, puis le supprimer lorsqu'il est vide.",
                    "fields": [("lobby_id", "voice", "Salon vocal d'entrée")]},
    "reaction_role": {"title": "Rôle par réaction", "icon": "🎨", "description": "Attribue ou retire un rôle quand quelqu'un réagit à un message déterminé.",
                      "fields": [("message_id", "snowflake", "ID du message"), ("emoji", "emoji", "Émoji (ex. ✅)"),
                                 ("role_id", "role", "Rôle à attribuer")]},
    "daily_post": {"title": "Annonce quotidienne", "icon": "📅", "description": "Publie un message chaque jour à l'heure de Paris tant que ton PC et le bot sont lancés.",
                   "fields": [("channel_id", "text", "Salon de publication"), ("hour", "hour", "Heure (HH:MM)"),
                              ("message", "message", "Message quotidien")]},
    "tickets": {"title": "Tickets privés interactifs", "icon": "🎟️", "description": "Tickets de support privés. Option : ajouter quatre boutons de recrutement esports distincts (sans attribuer automatiquement des rôles).",
                "fields": [("panel_channel_id", "text", "Salon du panneau"),
                           ("category_id", "category", "Catégorie des tickets"),
                           ("staff_role_id", "optional_role", "Rôle du support (facultatif)"),
                           ("recruitment_games", "games", "Recrutement (facultatif) : rocket-league, valorant, fortnite, clash-of-clans")]},
    "modmail": {"title": "Modmail privé par MP", "icon": "✉️", "description": "Transmet les messages privés au support et permet aux modérateurs de répondre avec !reply ID message. Nécessite Message Content Intent.",
                "fields": [("staff_channel_id", "private_text", "Salon privé du support"),
                           ("staff_role_id", "optional_role", "Rôle du support (facultatif)")], "requires": "content"},
    "applications": {"title": "Candidatures interactives", "icon": "📝", "description": "Publie un formulaire Discord (pseudo, disponibilités, motivation), transmet au support et permet d'accepter ou refuser.",
                     "fields": [("panel_channel_id", "text", "Salon public des candidatures"),
                                ("staff_channel_id", "private_text", "Salon privé des candidatures"),
                                ("staff_role_id", "optional_role", "Rôle de validation (facultatif)")]},
}

SNOWFLAKE = re.compile(r"^[0-9]{17,20}$")
LINK_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def public_modules() -> list[dict]:
    return [{"id": key, **spec} for key, spec in MODULES.items()]


def normalize_module(name: str, data: dict, guild) -> dict:
    """Reject unknown keys and IDs not belonging to this guild."""
    if name not in MODULES or not isinstance(data, dict):
        raise ValueError("Module inconnu.")
    allowed = {field[0] for field in MODULES[name]["fields"]} | {"enabled"}
    if set(data) - allowed:
        raise ValueError("Paramètre de module inconnu.")
    if not isinstance(data.get("enabled", False), bool):
        raise ValueError("Le statut du module doit être un booléen.")
    result = {"enabled": data.get("enabled", False)}
    for key, kind, _ in MODULES[name]["fields"]:
        value = data.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"Paramètre invalide : {key}.")
        value = value.strip()
        if not result["enabled"] and not value:
            continue
        if kind in {"role", "optional_role", "text", "private_text", "optional_text", "voice", "category", "snowflake"}:
            if not value and kind in {"optional_text", "optional_role"}:
                result[key] = ""
                continue
            if not SNOWFLAKE.fullmatch(value):
                raise ValueError(f"Identifiant Discord invalide : {key}.")
            if kind in {"role", "optional_role"} and not any(str(role.id) == value and not role.is_default()
                                                            for role in guild.roles):
                raise ValueError("Le rôle choisi n'existe pas sur ce serveur.")
            if kind in {"text", "private_text", "optional_text", "voice", "category"}:
                channel = guild.get_channel(int(value))
                expected = "voice" if kind == "voice" else "category" if kind == "category" else "text"
                if channel is None or str(getattr(channel, "type", "")) != expected:
                    raise ValueError("Choisis un salon du type attendu sur ce serveur.")
                if (name == "audit" or kind == "private_text") and result["enabled"]:
                    if channel.permissions_for(guild.default_role).view_channel:
                        raise ValueError("Le salon des journaux ou du support doit être privé pour @everyone.")
            result[key] = value
        elif kind == "games":
            games = normalize_recruitment_games(value)
            if games:
                result[key] = games
        elif kind == "words":
            words = [word.strip().casefold() for word in value.split(",") if word.strip()]
            if len(words) > 30 or any(len(word) > 45 for word in words):
                raise ValueError("Limite : 30 mots de 45 caractères maximum.")
            if result["enabled"] and not words:
                raise ValueError("Saisis au moins un mot à filtrer.")
            result[key] = ", ".join(dict.fromkeys(words))
        elif kind == "positive_int":
            if not re.fullmatch(r"[1-9][0-9]{0,3}", value) or int(value) > 1000:
                raise ValueError(f"{key} doit être un entier compris entre 1 et 1 000.")
            result[key] = value
        elif kind == "emoji":
            if not value or len(value) > 80 or any(ch.isspace() for ch in value):
                raise ValueError("Émoji invalide.")
            result[key] = value
        elif kind == "hour":
            if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
                raise ValueError("Indique une heure au format 08:30.")
            result[key] = value
        elif kind == "message":
            if not value or len(value) > 1800:
                raise ValueError("Message requis (1 à 1 800 caractères).")
            result[key] = value
    return result


def level_for_xp(xp: int) -> int:
    """Monotone threshold: level N begins at 5*N*N + 50*N XP."""
    level = 0
    while level < 1000 and xp >= 5 * (level + 1) ** 2 + 50 * (level + 1):
        level += 1
    return level


class SpamTracker:
    """Ephemeral sliding-window moderation, no message bodies persisted."""

    def __init__(self):
        self.events = defaultdict(deque)
        self.last_action = {}

    def flag(self, guild_id: int, user_id: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        key = (guild_id, user_id)
        queue = self.events[key]
        while queue and queue[0] <= now - 8:
            queue.popleft()
        queue.append(now)
        if len(queue) < 6 or now - self.last_action.get(key, -9999) < 60:
            return False
        self.last_action[key] = now
        queue.clear()
        return True


def should_filter(content: str, config: dict, *, links: bool = False) -> bool:
    if not content or not config.get("enabled"):
        return False
    if links:
        return bool(LINK_RE.search(content))
    words = [word.strip() for word in config.get("words", "").split(",") if word.strip()]
    body = content.casefold()
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", body) for word in words)


def paris_slot(now: datetime | None = None) -> tuple[str, str]:
    local = (now or datetime.now(ZoneInfo("Europe/Paris"))).astimezone(ZoneInfo("Europe/Paris"))
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
