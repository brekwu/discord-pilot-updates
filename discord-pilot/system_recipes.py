"""Conservative end-to-end blueprints for existing interactive Discord modules.

Only named resources are provisioned. The plans remain drafts until manually
approved, and panels work only while the local Discord bot is connected.
"""
from __future__ import annotations

import re
from planner import clean_name, norm, validate_actions


def recipe_kind(prompt: str) -> str | None:
    text = norm(prompt)
    if not re.search(r"\b(?:systeme|workflow|dispositif|installation)\b", text):
        return None
    if not re.search(r"\b(?:cree\w*|mets?\s+en\s+place|installe\w*|configure\w*|prepare\w*)\b", text):
        return None
    if re.search(r"\b(?:tickets?|assistance|support)\b", text):
        return "tickets"
    if re.search(r"\b(?:candidatures?|recrutement|postuler)\b", text):
        return "applications"
    return None


def _field(prompt: str, patterns: tuple[str, ...]) -> str | None:
    for expression in patterns:
        match = re.search(expression, prompt, re.I)
        if match:
            name = clean_name(match.group(1).strip())
            # Do not treat a whole sentence as a channel/role name.
            if name and len(name) <= 100 and not re.search(r"\b(?:et|puis|ensuite|avec|pour)\b", name, re.I):
                return name
    return None


def recipe_plan(prompt: str) -> tuple[list[dict], str | None] | None:
    """Return (complete draft, question) if this is an interactive system request.

    No names are inferred: missing mandatory names lead to a single concise
    explanation rather than a partially installed system.
    """
    kind = recipe_kind(prompt)
    if kind is None:
        return None
    panel = _field(prompt, (
        r"(?:salon\s+(?:public\s+|du\s+)?(?:panneau|boutons?)|panneau\s+dans\s+le\s+salon)\s*[:=]?\s*#?([\wÀ-ÿ-]+)",
        r"\bdans\s+(?:le\s+salon\s+)?#([\wÀ-ÿ-]+)",
    ))
    role = _field(prompt, (
        r"\br[oô]le\s+(?:staff|support|recruteur|responsable)\s*[:=]\s*@?([^,;\.\n]+)",
        r"\br[oô]le\s*[:=]\s*@?([^,;\.\n]+)",
    ))
    if kind == "tickets":
        category = _field(prompt, (
            r"\bcat[eé]gorie\s+(?:des\s+)?tickets?\s*[:=]\s*([^,;\.\n]+)",
            r"\bcat[eé]gorie\s*[:=]?\s*([^,;\.\n]+)",
        ))
        if not all((panel, category, role)):
            return [], ("Pour créer le système complet de tickets avec bouton, précise : "
                        "salon du panneau : #assistance, catégorie : TICKETS, rôle staff : Support. "
                        "Aucune modification n'a été effectuée.")
        actions = [
            {"type": "create_category", "name": category},
            {"type": "create_role", "name": role},
            {"type": "create_text_channel", "name": panel, "category": category},
            {"type": "configure_module", "module": "tickets", "enabled": "true",
             "panel_channel_id": panel, "category_id": category, "staff_role_id": role},
            {"type": "publish_ticket_panel"},
        ]
    else:
        review = _field(prompt, (
            r"(?:salon\s+(?:priv[eé]\s+|du\s+)?(?:suivi|staff|validation|candidatures?\s+priv[eé]es?))\s*[:=]?\s*#?([\wÀ-ÿ-]+)",
            r"\bsuivi\s+dans\s+(?:le\s+salon\s+)?#([\wÀ-ÿ-]+)",
        ))
        category = _field(prompt, (r"\bcat[eé]gorie\s*[:=]?\s*([^,;\.\n]+)",))
        if not all((panel, review, role)):
            return [], ("Pour créer le système complet de candidatures avec bouton, précise : "
                        "salon du panneau : #postuler, salon de suivi : #candidatures-staff, "
                        "rôle staff : Recruteur. Aucune modification n'a été effectuée.")
        if norm(panel) == norm(review):
            return [], "Le panneau public et le salon privé de suivi doivent être différents."
        actions = []
        if category:
            actions.append({"type": "create_category", "name": category})
        actions.extend([
            {"type": "create_role", "name": role},
            {"type": "create_text_channel", "name": panel, **({"category": category} if category else {})},
            {"type": "create_private_text_channel", "name": review, "role": role,
             **({"category": category} if category else {})},
            {"type": "configure_module", "module": "applications", "enabled": "true",
             "panel_channel_id": panel, "staff_channel_id": review, "staff_role_id": role},
            {"type": "publish_application_panel"},
        ])
    return validate_actions(actions), None


def recipe_publication_authorized(prompt: str, action_type: str) -> bool:
    wanted = recipe_kind(prompt)
    return (wanted == "tickets" and action_type == "publish_ticket_panel" or
            wanted == "applications" and action_type == "publish_application_panel") and bool(
        re.search(r"\b(?:boutons?|interactif|complet)\b", norm(prompt)))
