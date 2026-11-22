"""Read-only, live Discord verification of the additive Vexora Esport preset.

Does not infer successful execution from a GitHub build or stored plan.
Uses Discord REST reads; creates/modifies/deletes nothing.
"""
from __future__ import annotations

from planner import PRESETS, norm


async def audit_vexora_esport(guild) -> dict:
    target = PRESETS["vexora-esport"]["actions"]
    if guild is None:
        return {"status": "offline", "checked": 0, "expected": len(target),
                "passed": 0, "missing": len(target), "checks": [],
                "detail": "Bot Discord déconnecté du serveur sélectionné."}
    try:
        channels = await guild.fetch_channels()
        roles = await guild.fetch_roles()
    except Exception as exc:
        return {"status": "unverified", "checked": 0, "expected": len(target),
                "passed": 0, "missing": len(target), "checks": [],
                "detail": f"Lecture directe Discord indisponible ({type(exc).__name__})."}
    checks = []
    categories = [c for c in channels if str(getattr(c, "type", "")) == "category"]
    text_channels = [c for c in channels if str(getattr(c, "type", "")) == "text"]
    for item in target:
        kind = item["type"]
        name = item["name"]
        detail = ""
        if kind == "create_category":
            matched = [c for c in categories if norm(c.name) == norm(name)]
            ok = len(matched) == 1
            detail = "Catégorie retrouvée sur Discord." if ok else (
                "Catégorie absente." if not matched else "Catégorie ambiguë : doublons."
            )
        elif kind == "create_role":
            matched = [r for r in roles if norm(r.name) == norm(name)]
            ok = len(matched) == 1
            detail = "Rôle retrouvé sur Discord." if ok else (
                "Rôle absent." if not matched else "Plusieurs rôles portent le même nom."
            )
        elif kind == "create_text_channel":
            parent = [c for c in categories if norm(c.name) == norm(item["category"])]
            matched = [c for c in text_channels if norm(c.name) == norm(name)]
            correct = [c for c in matched if len(parent) == 1 and
                       getattr(c, "category_id", None) == parent[0].id]
            ok = len(correct) == 1 and len(matched) == 1
            detail = "Salon présent dans le bon pôle." if ok else (
                "Catégorie du pôle absente ou ambiguë." if len(parent) != 1
                else "Salon absent." if not matched
                else "Salon présent dans une autre catégorie ou en doublon."
            )
        else:
            ok = False
            detail = "Action non auditée ; refus de valider."
        checks.append({"type": kind, "name": name,
                       "category": item.get("category"), "ok": ok, "detail": detail})
    passed = sum(1 for c in checks if c["ok"])
    return {
        "status": "verified" if passed == len(target) else "incomplete",
        "checked": len(checks), "expected": len(target), "passed": passed,
        "missing": len(target) - passed, "checks": checks,
        "detail": ("Les 56 éléments du modèle sont confirmés par l'API Discord."
                   if passed == len(target) else
                   f"{len(target) - passed} élément(s) absents, ambigus ou mal placés."),
        "note": ("Un audit des rôles et salons ne valide pas les tickets, les permissions "
                 "des candidats ni les interactions utilisateur."),
    }
