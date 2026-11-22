"""Conservative offline plans for complete, explicitly described server workflows.

This does not infer arbitrary Discord administration. It composes operations
already implemented and validated by Discord Pilot, and rejects ambiguous or
partially understood workflows instead of silently dropping user requests.
"""

from __future__ import annotations

import re

from panel_planning import complete_panel_plan, direct_panel_plan
from plan_runtime import direct_permission_plan
from planner import PRESETS, action, local_parse, norm, validate_actions


_VERBS = (r"cr[eé]e\w*|ajoute\w*|rajoute\w*|renomme\w*|supprime\w*|"
          r"active\w*|d[eé]sactive\w*|configure\w*|installe\w*|"
          r"publie\w*|poste\w*|affiche\w*|rends?|rendre|mets|mettre|envoie\w*")
_COMMAND_START = re.compile(rf"(?i)^(?:{_VERBS})\b")
_BOUNDARY = re.compile(rf"(?i)(?:\s*[,;\n]\s*|\s+\b(?:puis|ensuite|apr[eè]s)\b\s+|"
                       rf"\s+\bet\b\s+)(?=(?:{_VERBS})\b)")
_ARTICLE_BOUNDARY = re.compile(
    r"(?i)\s+et\s+(?=(?:un|une|des|deux|trois|2|3)\s+"
    r"(?:salons?|channels?|r[oô]les?|cat[eé]gories?)\b)")


def workflow_clauses(prompt: str) -> list[str]:
    """Split compound instructions without cutting quoted message contents."""
    text = prompt.strip()
    text = re.sub(
        r"(?i)^(?:(?:bonjour|salut|alors|du coup|ok|bon)[,.!]?\s+)*"
        r"(?:je veux|je voudrais|je souhaiterais|j['’]aimerais|tu peux|"
        r"est.ce que tu peux|pourrais.tu|il faut|il faudrait)\s+"
        r"(?:(?:que tu|me|nous)\s+)*", "", text)
    if not text:
        return []
    quotes = {"\"": "\"", "«": "»", "'": "'", "‘": "’"}
    # Mask quoted content before splitting, so commas or "et" in a message
    # cannot be mistaken for another requested operation.
    masked = list(text)
    closing = None
    for i, char in enumerate(text):
        if closing:
            masked[i] = "_"
            if char == closing:
                closing = None
            continue
        if char in quotes and (char != "'" or i == 0 or not text[i - 1].isalpha()):
            closing = quotes[char]
            masked[i] = "_"
    stable = "".join(masked)
    spans = []
    for match in re.finditer(r"[;\n]+", stable):
        spans.append((match.start(), match.end(), ""))
    for regex in (_BOUNDARY, _ARTICLE_BOUNDARY):
        for match in regex.finditer(stable):
            spans.append((match.start(), match.end(), "crée " if regex is _ARTICLE_BOUNDARY else ""))
    spans.sort()
    result = []
    cursor = 0
    prefix = ""
    for start, end, replacement in spans:
        if start < cursor:
            continue
        part = (prefix + text[cursor:start]).strip(" ,;.!\n")
        if part:
            result.append(part)
        cursor = end
        prefix = replacement
    part = (prefix + text[cursor:]).strip(" ,;.!\n")
    if part:
        result.append(part)
    return result


_MODULE_INTENTS = {
    "tickets": re.compile(r"(?i)^(?:active\w*|configure\w*|mets\s+en\s+place|installe\w*)\s+(?:le\s+module\s+|les?\s+)?tickets?(?:\s+interactifs?)?$"),
    "applications": re.compile(r"(?i)^(?:active\w*|configure\w*|mets\s+en\s+place|installe\w*)\s+(?:le\s+module\s+|les?\s+)?(?:candidatures?|formulaires?\s+de\s+candidature)$"),
}


def _unique_name(names: list[str], preferred: list[str]) -> str | None:
    for candidate in preferred:
        selected = [name for name in names if norm(name) == candidate]
        if len(selected) == 1:
            return selected[0]
    return names[0] if len(names) == 1 else None


def _module_action(module: str, actions: list[dict]) -> dict | None:
    channels = [item["name"] for item in actions if item["type"] == "create_text_channel"]
    categories = [item["name"] for item in actions if item["type"] == "create_category"]
    roles = [item["name"] for item in actions if item["type"] == "create_role"]
    if module == "tickets":
        panel = _unique_name(channels, ["tickets", "ticket", "ouvrir-un-ticket", "support"])
        category = _unique_name(categories, ["support", "tickets", "ticket"])
        if not panel or not category:
            return None
        result = action("configure_module", module="tickets", enabled="true",
                        panel_channel_id=panel, category_id=category)
        role = _unique_name(roles, ["support", "staff", "equipe support", "moderateur"])
        if role:
            result["staff_role_id"] = role
        return result
    if module == "applications":
        private_channels = [item["name"] for item in actions if item["type"] == "make_private"]
        panel = _unique_name([name for name in channels if name not in private_channels],
                             ["candidatures", "candidature", "recrutement", "postuler"])
        review = _unique_name(private_channels, ["validation", "validation-candidatures", "staff-candidatures"])
        if not panel or not review or panel == review:
            return None
        result = action("configure_module", module="applications", enabled="true",
                        panel_channel_id=panel, staff_channel_id=review)
        role = _unique_name(roles, ["rh", "recruteur", "staff", "moderateur"])
        if role:
            result["staff_role_id"] = role
        return result
    return None


def guided_workflow_plan(prompt: str) -> list[dict]:
    """Build a multi-step ticket/application workflow from explicit resources.

    Requiring resources in the request is intentional: the bot must never
    silently guess which existing salon is public or staff-only.
    """
    clauses = workflow_clauses(prompt)
    if not any(_MODULE_INTENTS[k].fullmatch(norm(clause)) for clause in clauses
               for k in _MODULE_INTENTS):
        return []
    actions = []
    for clause in clauses:
        mode = next((name for name, regex in _MODULE_INTENTS.items()
                     if regex.fullmatch(norm(clause))), None)
        if mode:
            config = _module_action(mode, actions)
            if not config:
                return []
            actions.append(config)
            continue
        parsed = direct_panel_plan(clause) or direct_permission_plan(clause) or local_parse(clause)
        if not parsed:
            return []
        actions.extend(parsed)
        if len(actions) > 40:
            return []
    # An explicit publication command may have been split from activation.
    # complete_panel_plan checks the user's original intent and deduplicates.
    return complete_panel_plan(prompt, validate_actions(actions))


def server_preset_plan(prompt: str) -> list[dict]:
    """Allow choosing existing audited templates by natural-language request."""
    phrase = norm(prompt).strip(" .!?")
    # Named Vexora Esport means the four-game organization, never generic tournoi.
    if re.fullmatch(
        r"(?:cree|creer|prepare|preparer|configure|configurer|mets en place|installer?|"
        r"initialise|initialiser)\s+(?:un|une|le|la)?\s*"
        r"(?:serveur|structure|modele)\s+(?:de\s+|pour\s+)?"
        r"vexora[-\s]+(?:e[-\s]*)?sports?",
        phrase,
    ):
        return validate_actions(PRESETS["vexora-esport"]["actions"])
    match = re.fullmatch(
        r"(?:cree|creer|prepare|preparer|configure|configurer|mets en place|installer?|initialise|initialiser)\s+"
        r"(?:un|une|le|la)?\s*(?:serveur|structure|modele)\s+"
        r"(?:de\s+type\s+|pour\s+)?(communaute|communautaire|tournoi|esport|entreprise|support|sav)", phrase)
    if not match:
        return []
    kind = {"communautaire": "communaute", "esport": "tournoi", "sav": "support"}.get(match.group(1), match.group(1))
    return validate_actions(PRESETS[kind]["actions"])


def batch_module_plan(prompt: str) -> list[dict]:
    """Exact activation/deactivation of multiple no-parameter native modules."""
    phrase = norm(prompt).strip(" .!?")
    match = re.fullmatch(r"(active(?:r)?|desactive(?:r)?)\s+(.+)", phrase)
    if not match:
        return []
    raw = re.split(r"\s*(?:,|\bet\b|\bpuis\b)\s*", match.group(2))
    if len(raw) < 2:
        return []
    aliases = {
        "xp": "xp", "les xp": "xp", "l xp": "xp", "les niveaux": "xp", "le classement xp": "xp",
        "l antispam": "antispam", "antispam": "antispam", "l anti spam": "antispam", "anti spam": "antispam",
        "anti liens": "antilinks", "l anti liens": "antilinks", "le filtre de liens": "antilinks",
        "les statistiques": "activity_stats", "statistiques": "activity_stats", "les stats": "activity_stats",
        "le classement des messages": "activity_stats", "les statistiques des messages": "activity_stats",
    }
    modules = [aliases.get(item.strip()) for item in raw]
    if any(module is None for module in modules):
        return []
    seen = set()
    enabled = "false" if match.group(1).startswith("desactive") else "true"
    actions = []
    for module in modules:
        if module not in seen:
            actions.append(action("set_module", module=module, enabled=enabled))
            seen.add(module)
    return validate_actions(actions)
