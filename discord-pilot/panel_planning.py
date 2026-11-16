"""Natural-language intent for two opt-in, public Discord panels."""

from __future__ import annotations

import re

from planner import norm, validate_actions


PANEL_ACTIONS = {"tickets": "publish_ticket_panel", "applications": "publish_application_panel"}
PANEL_TERMS = {
    "tickets": r"\btickets?\b",
    "applications": r"\b(?:candidatures?|formulaires?\s+de\s+candidature)\b",
}


def publication_requested(prompt: str, module: str) -> bool:
    text = norm(prompt)
    if module not in PANEL_TERMS or not re.search(PANEL_TERMS[module], text):
        return False
    if re.search(r"\b(?:sans\s+(?:publier|panneau)|ne\s+publie\s+pas|pas\s+encore\s+de\s+panneau)\b", text):
        return False
    return bool(re.search(r"\b(?:publie\w*|poste\w*|affiche\w*|active\w*|"
                          r"lance\w*|installe\w*|ouvre\w*|met\w*\s+en\s+place)\b", text))


def direct_panel_plan(prompt: str) -> list[dict]:
    """Recognize an exact publication command without relying on Ollama."""
    phrase = norm(prompt).strip(" .!?")
    for module, name in PANEL_ACTIONS.items():
        noun = "tickets?" if module == "tickets" else "candidatures?"
        if re.fullmatch(
                rf"(?:publie|publier|poste|poster|affiche|afficher)\s+"
                rf"(?:le\s+)?(?:panneau|formulaire)\s+(?:des?\s+)?{noun}", phrase):
            return validate_actions([{"type": name}])
    return []


def complete_panel_plan(prompt: str, actions: list[dict]) -> list[dict]:
    """Add a visible, reviewable publish action after an explicit activation."""
    result = []
    present = {item["type"] for item in actions}
    for item in actions:
        result.append(item)
        if item["type"] != "configure_module" or item["enabled"] != "true":
            continue
        module = item["module"]
        if module in PANEL_ACTIONS and publication_requested(prompt, module) and \
                PANEL_ACTIONS[module] not in present:
            result.append({"type": PANEL_ACTIONS[module]})
            present.add(PANEL_ACTIONS[module])
    return validate_actions(result)
