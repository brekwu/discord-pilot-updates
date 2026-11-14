"""Small, auditable validation helpers for private support workflows."""

from __future__ import annotations

import re


USER_ID = re.compile(r"^[0-9]{17,20}$")


def staff_allowed(member, role_id: str = "") -> bool:
    permissions = getattr(member, "guild_permissions", None)
    elevated = bool(getattr(permissions, "manage_channels", False) or
                    getattr(permissions, "administrator", False))
    roles = getattr(member, "roles", [])
    return elevated or bool(role_id and any(str(role.id) == role_id for role in roles))


def parse_staff_reply(content: str) -> tuple[str, str]:
    match = re.fullmatch(r"!reply\s+(?:<@!?(\d{17,20})>|(\d{17,20}))\s+([\s\S]{1,1300})", content.strip())
    if not match:
        raise ValueError("Commande attendue : !reply ID_UTILISATEUR message (1 à 1 300 caractères).")
    message = match.group(3).strip()
    if not message:
        raise ValueError("La réponse ne peut pas être vide.")
    return match.group(1) or match.group(2), message


def parse_dm_target(content: str) -> tuple[str | None, str]:
    """An explicit guild is required only when the sender has several options."""
    message = content.strip()
    if not message:
        raise ValueError("Écris ton message pour le support.")
    if message.startswith("!mail"):
        match = re.fullmatch(r"!mail\s+(\d{17,20})\s+([\s\S]{1,1300})", message)
        if not match:
            raise ValueError("Utilise !mail ID_SERVEUR ton message.")
        text = match.group(2).strip()
        if not text:
            raise ValueError("Le message ne peut pas être vide.")
        return match.group(1), text
    if len(message) > 1300:
        raise ValueError("Le message ne peut pas dépasser 1 300 caractères.")
    return None, message


def validate_application(values: dict) -> dict:
    limits = {"nickname": (2, 70), "availability": (2, 240), "motivation": (10, 900)}
    if not isinstance(values, dict) or set(values) != set(limits):
        raise ValueError("Le formulaire de candidature est incomplet.")
    output = {}
    for key, (minimum, maximum) in limits.items():
        value = values[key]
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError(f"Le champ {key} doit contenir de {minimum} à {maximum} caractères.")
        output[key] = value.strip()
    return output
