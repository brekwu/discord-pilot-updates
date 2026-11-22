"""Live read-only verification of the ALREADY-EXISTING official Vexora Esport guild.

No role, channel, ticket, permission or message is ever changed.
The expected inventory is the deployed bridge's 32+13 roles, 11 categories,
73 channels, including explicit @everyone denies for private rooms.
"""
from __future__ import annotations

from planner import norm
from vexora_official_layout import BASE_ROLES, EXTRA_ROLES, CATEGORIES, CHANNELS


def audit_official_vexora(guild, channels, roles) -> dict:
    checks: list[dict] = []
    categories = [c for c in channels if str(getattr(c, "type", "")) == "category"]
    ordinary = [c for c in channels if str(getattr(c, "type", "")) in {"text", "voice"}]

    def record(kind: str, name: str, parent: str | None,
               ok: bool, reason: str) -> None:
        checks.append({"type": kind, "name": name, "category": parent,
                       "ok": bool(ok), "detail": reason})

    def matches(seq, name):
        return [item for item in seq if norm(item.name) == norm(name)]

    def is_explicit_private(obj):
        default_role = getattr(guild, "default_role", None)
        if default_role is None:
            return False
        try:
            return obj.overwrites_for(default_role).view_channel is False
        except (AttributeError, TypeError, ValueError):
            return False

    for name in BASE_ROLES + EXTRA_ROLES:
        found = matches(roles, name)
        record("role", name, None, len(found) == 1,
               "Rôle Discord réel confirmé." if len(found) == 1
               else "Rôle absent." if not found else "Rôle ambigu : doublons.")

    for name in CATEGORIES:
        found = matches(categories, name)
        unique = len(found) == 1
        secure = not name.startswith("🔒") or (unique and is_explicit_private(found[0]))
        record("category", name, None, unique and secure,
               "Catégorie présente et confidentialité vérifiée." if unique and secure
               else "Catégorie absente." if not found else
               "Catégorie en double." if not unique else
               "Catégorie STAFF visible par @everyone (accès non sûr).")

    for category, name, kind, private in CHANNELS:
        parents = matches(categories, category)
        found = [c for c in ordinary if norm(c.name) == norm(name)
                 and str(getattr(c, "type", "")) == kind
                 and len(parents) == 1
                 and getattr(c, "category_id", None) == parents[0].id]
        unique = len(found) == 1
        secure = not private or (unique and is_explicit_private(found[0]))
        record(kind, name, category, unique and secure,
               "Salon réel confirmé, position et accès privé vérifiés."
               if unique and secure else
               "Catégorie absente ou en double." if len(parents) != 1
               else "Salon absent ou en double dans cette catégorie." if not unique
               else "Accès privé non sûr : @everyone n'est pas explicitement refusé.")

    expected = len(BASE_ROLES) + len(EXTRA_ROLES) + len(CATEGORIES) + len(CHANNELS)
    assert expected == 129
    passed = sum(check["ok"] for check in checks)
    return {
        "status": "verified" if passed == expected else "incomplete",
        "checked": len(checks), "expected": expected, "passed": passed,
        "missing": expected - passed, "checks": checks,
        "detail": ("Inventaire officiel existant confirmé en direct : 45 rôles, "
                   "11 catégories et 73 salons, y compris les refus explicites "
                   "pour les espaces privés." if passed == expected else
                   f"{expected - passed} élément(s) manquants, ambigus ou insuffisamment privés."),
        "note": ("Contrôle de configuration réel sur Discord, distinct des boutons "
                 "de recrutement, du Gateway et des clics candidats."),
        "canonical_guild": True,
    }
