"""Resolve conversational plan references against a live guild, then validate.

Only known Discord entities and native module fields may be used.  No fuzzy
matching, guessed IDs, arbitrary Discord permissions, or external code.
"""

from __future__ import annotations

import re

from community_modules import MODULES, SNOWFLAKE, normalize_module
from discord_ops import category_by_name, channel_by_name, role_by_name


class PlanGuildView:
    """Include just-created API objects before Discord's gateway cache catches up."""

    def __init__(self, guild, created: dict | None = None):
        self.guild = guild
        created = created or {}
        self.id = guild.id
        self.default_role = guild.default_role
        def merged(original, new):
            return list({obj.id: obj for obj in [*original, *new]}.values())
        self.channels = merged(getattr(guild, "channels", []), created.get("channels", {}).values())
        self.categories = merged(getattr(guild, "categories", []), created.get("categories", {}).values())
        self.roles = merged(getattr(guild, "roles", []), created.get("roles", {}).values())

    def get_channel(self, ident):
        return next((c for c in [*self.channels, *self.categories] if c.id == ident), None) or self.guild.get_channel(ident)

    def get_role(self, ident):
        return next((r for r in self.roles if r.id == ident), None) or self.guild.get_role(ident)


def resolve_module_settings(guild, previous: dict, item: dict, created: dict | None = None) -> dict:
    """Return strict module configuration with names converted to guild IDs.

    Previous settings are retained for follow-up commands that only change one
    field.  Actual configured module state is updated only after validation.
    """
    guild = PlanGuildView(guild, created)
    name = item["module"]
    spec = MODULES[name]
    payload = {**previous, "enabled": item["enabled"] == "true"}
    kinds = {key: kind for key, kind, _ in spec["fields"]}
    for key, value in item.items():
        if key in {"type", "module", "enabled"}:
            continue
        kind = kinds[key]
        if kind in {"role", "optional_role", "text", "private_text", "optional_text", "voice", "category"}:
            if SNOWFLAKE.fullmatch(value):
                payload[key] = value
            elif kind in {"role", "optional_role"}:
                payload[key] = str(role_by_name(guild, value).id)
            elif kind == "category":
                payload[key] = str(category_by_name(guild, value).id)
            else:
                payload[key] = str(channel_by_name(guild, value).id)
        else:
            payload[key] = value
    return normalize_module(name, payload, guild)


def set_module_config(state, guild, item: dict, created: dict | None = None) -> tuple[str, str]:
    """Persist a validated native module configuration; avoid redundant writes."""
    name = item["module"]
    guild_id = str(guild.id)
    previous = state.module(guild_id, name)
    settings = resolve_module_settings(guild, previous, item, created)
    if previous == settings:
        return "skipped", f"{MODULES[name]['title']} est déjà configuré ainsi."
    state.set_module(guild_id, name, settings)
    if state.module(guild_id, name) != settings:
        raise ValueError("La nouvelle configuration n'a pas été conservée ; réessaie.")
    return "done", (f"{MODULES[name]['title']} configuré et enregistré. "
                    "Fonctionnement pendant la connexion du bot, avec les permissions Discord requises.")


PERMISSION_REQUEST = re.compile(
    r"\b(?:autoris\w*|interdi\w*|refus\w*|cach\w*|masqu\w*|"
    r"priv\w*|visible|invisible|ecri\w*|lectur\w*|"
    r"connect\w*|voi[rs]|rejoind\w*)\b", re.I)


def explicit_permission_intent(prompt: str) -> bool:
    """Do not let a model make up grants from a generic cleanup request."""
    from planner import norm
    phrase = norm(prompt)
    mentions_role = bool(re.search(r"\b(?:roles?|membres?|everyone)\b", phrase))
    mentions_channel = bool(re.search(r"\b(?:salons?|channels?|canaux?|vocaux?)\b", phrase))
    return mentions_role and mentions_channel and bool(PERMISSION_REQUEST.search(phrase))


def permission_action_is_authorized(prompt: str, item: dict) -> bool:
    """Check each AI-chosen permission against the actual request.

    An instruction to allow viewing cannot silently grant posting too.
    Unclear combinations should use the explicit guided permission form.
    """
    from planner import norm
    phrase = norm(prompt)
    if not explicit_permission_intent(prompt):
        return False
    # Named targets must be present in the user's own sentence. Contextual
    # pronouns and guesses are not sufficient to change access rights.
    if not all(norm(item[key].lstrip("#@")) in phrase for key in ("role", "channel")):
        return False
    view_terms = re.search(r"\b(?:voi[rs]|visible|invisible|visibilite|masqu\w*|cach\w*|prive\w*)\b", phrase)
    participate_terms = re.search(r"\b(?:ecri\w*|messages?|rejoind\w*|connect\w*|parl\w*|particip\w*)\b", phrase)
    positive = re.search(r"\b(?:autoris\w*|perme\w*|ouvre\w*|accord\w*)\b", phrase)
    negative = re.search(r"\b(?:interdi\w*|refus\w*|bloqu\w*|masqu\w*|cach\w*|prive\w*|invisible)\b", phrase)
    restore = re.search(r"\b(?:herit\w*|defaut|reinitialis\w*|retabl\w*)\b", phrase)
    for key, requested in (("view", view_terms), ("participate", participate_terms)):
        value = item[key]
        if value == "keep":
            continue
        if not requested:
            return False
        if value == "allow" and not positive:
            return False
        if value == "deny" and not negative:
            return False
        if value == "inherit" and not restore:
            return False
    return True


def direct_permission_plan(prompt: str) -> list[dict]:
    """Parse narrow, unambiguous access instructions even without Ollama.

    The verb, operation, role and channel must all be explicit.  A broad
    request such as 'gère les rôles' returns no permissions at all.
    """
    from planner import clean_name, validate_actions
    phrase = prompt.strip().rstrip(". !?")
    m = re.fullmatch(
        r"(?P<verb>autorise|autoriser|interdis|interdire|refuse|refuser)\s+"
        r"(?:au\s+|le\s+|pour\s+le\s+)?r[oô]le\s+(?P<role>.+?)\s+"
        r"(?:[àa]|de|d')\s*(?P<operation>voir|[ée]crire|envoyer\s+des\s+messages|rejoindre)\s+"
        r"(?:dans\s+|sur\s+|au\s+|le\s+)?(?:le\s+)?salon\s+(?P<channel>.+)",
        phrase, re.I)
    if not m:
        return []
    operation = m.group("operation").casefold()
    slot = "view" if operation == "voir" else "participate"
    action = {"type": "set_role_access", "channel": clean_name(m.group("channel")),
              "role": clean_name(m.group("role")), "view": "keep", "participate": "keep"}
    action[slot] = "allow" if m.group("verb").casefold().startswith("autoris") else "deny"
    return validate_actions([action])
