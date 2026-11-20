"""Bounded, auditable handling of long Discord configuration requests.

The model never receives an arbitrarily truncated 50k-character request.
Sections are analyzed independently and an unrecognized actionable section
blocks the entire draft, so an incomplete plan cannot be mistaken for a full
server setup. No Discord mutation happens in this module.
"""

from __future__ import annotations

import re

from planner import MAX_PLAN_ACTIONS, norm, validate_actions


MAX_REQUEST_CHARS = 50_000
MODEL_SECTION_CHARS = 3_600

_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s+|={4,}|[-=]{5,}\s*$|"
    r"(?:[^\w\s:]{1,8}\s*)?(?:cat[eé]gorie|section|p[oô]le|r[oô]les?(?:\s+[àa]\s+cr[eé]er)?|"
    r"contexte|objectif|important|pr[eé]sentation|r[oô]le)\s*[:—-])",
    re.I,
)
_INTENT = re.compile(
    r"\b(?:cr[eé]e\w*|ajoute\w*|rajoute\w*|configur\w*|"
    r"activ\w*|d[eé]sactiv\w*|install\w*|publi\w*|"
    r"envoi\w*|renomm\w*|supprim\w*|d[eé]plac\w*|"
    r"mets?\s+en\s+place|rends?\s+priv[eé]|"
    r"[àa]\s+cr[eé]er|[àa]\s+ajouter|[àa]\s+configurer)\b", re.I)
_STRUCTURED_HEADING = re.compile(r"\b(?:r[oô]les?|salons?|canaux|channels?|cat[eé]gories?)\b", re.I)
_NEGATIVE_ONLY = re.compile(r"^\s*(?:ne\s+|n['’]|pas\s+|aucun\s+|sans\s+)", re.I)
_METADATA_HEADER = re.compile(r"^(?:#{1,6}\s*)?(?:r[oô]le|contexte|objectif|important|pr[eé]sentation)\s*[:：]", re.I)
_DIRECT_COMMAND = re.compile(r"^(?:cr[eé]e\w*|ajoute\w*|configure\w*|active\w*|"
                             r"d[eé]sactive\w*|publie\w*|renomme\w*|supprime\w*)\b", re.I)


def global_protections(prompt: str) -> str:
    """Carry declared preservation rules into every model subsection."""
    lines = []
    for line in prompt.splitlines():
        plain = norm(line)
        if re.search(r"\b(?:ne\s+(?:supprim\w*|modifi\w*|touch\w*|perturb\w*)|"
                     r"sans\s+(?:supprim\w*|modifi\w*)|conserv\w*\s+(?:tous|les))\b", plain):
            value = line.strip()[:300]
            if value not in lines:
                lines.append(value)
        if len(lines) >= 12:
            break
    return "\n".join(lines)


def focused_server_context(context: dict | None, section: str) -> dict:
    """Give small local models relevant real names instead of 120 noisy rooms."""
    if not isinstance(context, dict):
        return {}
    result = {"connected": bool(context.get("connected"))}
    server = context.get("server")
    if isinstance(server, dict):
        output = {"name": server.get("name", "")}
        needle = norm(section).replace("-", " ")

        def mentioned(name: str) -> bool:
            return bool(re.search(r"(?<!\w)" + re.escape(norm(name).replace("-", " ")) + r"(?!\w)", needle))

        for kind, limit in (("categories", 30), ("channels", 35), ("roles", 35)):
            values = server.get(kind, [])
            if isinstance(values, list):
                output[kind] = [item for item in values if
                                isinstance(item, (str, dict)) and
                                (name := item if isinstance(item, str) else item.get("name")) and
                                isinstance(name, str) and mentioned(name)][:limit]
        result["server"] = output
    if re.search(r"\b(?:dernier\w*|pr[eé]c[eé]dent\w*|r[eé]cemment)\b", norm(section)):
        recent = context.get("recent_plans", [])
        if isinstance(recent, list):
            result["recent_plans"] = recent[:2]
    return result


def request_sections(prompt: str, limit: int = MODEL_SECTION_CHARS) -> list[str]:
    """Split on document boundaries, including oversized lines, without loss."""
    if limit < 400:
        raise ValueError("Limite de section trop petite.")
    sections: list[str] = []
    buffer = ""
    for line in prompt.splitlines(keepends=True):
        if buffer and _HEADING.match(line) and len(buffer.strip()) >= 15:
            sections.append(buffer)
            buffer = ""
        while len(line) > limit:
            room = limit - len(buffer)
            if room < 400 and buffer:
                sections.append(buffer)
                buffer = ""
                room = limit
            cut = line.rfind(" ", 0, room + 1)
            if cut < room // 2:
                cut = room
            buffer += line[:cut]
            sections.append(buffer)
            buffer = ""
            line = line[cut:]
        if buffer and len(buffer) + len(line) > limit:
            sections.append(buffer)
            buffer = ""
        buffer += line
    if buffer:
        sections.append(buffer)
    return sections


def actionable_section(text: str) -> bool:
    """Reject unknown instructions, but ignore obviously descriptive metadata."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    if _METADATA_HEADER.match(norm(lines[0])):
        # The project's background, role assignment and negative rules are
        # context, not individual Discord operations.
        return any(_DIRECT_COMMAND.match(norm(line.lstrip("-*• "))) for line in lines[1:])
    for line in lines:
        plain = norm(re.sub(r"^[#*•\-\s\d.]+", "", line))
        if _NEGATIVE_ONLY.match(plain):
            continue
        if _INTENT.search(plain):
            return True
    heading = norm(lines[0])
    has_bullets = any(re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line) for line in lines[1:])
    return bool(has_bullets and _STRUCTURED_HEADING.search(heading))


def merge_actions(parts: list[list[dict]]) -> list[dict]:
    """Exact deduplication for repeated creations, no deduplication of messages.

    Creation order is normalized within pure creation plans. For mixed plans,
    the user's order is retained, and the existing executor remains fail-closed.
    """
    combined: list[dict] = []
    seen: set[tuple] = set()
    for part in parts:
        for item in part:
            kind = item["type"]
            key = (kind, norm(item.get("name", "")), norm(item.get("category", "")))
            if kind in {"create_category", "create_text_channel", "create_voice_channel", "create_role"}:
                if key in seen:
                    continue
                seen.add(key)
            combined.append(item)
            if len(combined) > MAX_PLAN_ACTIONS:
                raise ValueError(f"La demande dépasse {MAX_PLAN_ACTIONS} actions Discord. Découpe-la en plusieurs plans.")
    if combined and all(item["type"].startswith("create_") for item in combined):
        priority = {"create_category": 0, "create_role": 1, "create_text_channel": 2, "create_voice_channel": 2}
        combined.sort(key=lambda item: priority[item["type"]])
    return validate_actions(combined) if combined else []


_DECORATION = r"(?:[^\w\s:]{1,8}\s*)?"
_ROLE_HEADER = re.compile(
    rf"^(?:#{{1,6}}\s*)?{_DECORATION}r[oô]les?"
    r"(?:\s+(?:[àa]\s+cr[eé]er|discord|esport))?\s*[:：]?$", re.I)
_CATEGORY_HEADER = re.compile(
    rf"^(?:#{{1,6}}\s*)?{_DECORATION}cat[eé]gorie\s*[:：—-]\s*(.+)$", re.I)
_CHANNEL_HEADER = re.compile(
    rf"^(?:#{{1,6}}\s*)?{_DECORATION}(?:salons?|channels?)"
    r"(?:\s+(?:textuels?|vocaux?|vocals?))?\s*[:：]?$", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")


def structured_creation_plan(prompt: str) -> list[dict]:
    """Purely additive, explicit Markdown specs need no model.

    Deliberately strict: unknown lines, permissions, automation or prose
    invalidate this fast path and are delegated to the normal planner.
    """
    mode = None
    category = None
    channel_kind = "create_text_channel"
    actions = []
    for raw in prompt.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"[=-]{4,}", line):
            continue
        if _ROLE_HEADER.fullmatch(line):
            mode = "roles"
            continue
        match = _CATEGORY_HEADER.fullmatch(line)
        if match:
            category = match.group(1).strip().strip("`* ")
            if not category or len(category) > 100:
                return []
            actions.append({"type": "create_category", "name": category})
            mode = "channels"
            channel_kind = "create_text_channel"
            continue
        if _CHANNEL_HEADER.fullmatch(line) and category:
            mode = "channels"
            channel_kind = ("create_voice_channel" if re.search(r"\b(?:vocaux?|vocals?)\b", line, re.I)
                            else "create_text_channel")
            continue
        item = _BULLET.fullmatch(line)
        if not item or mode not in {"roles", "channels"}:
            return []
        name = item.group(1).strip().strip("`* ")
        if mode == "channels":
            name = name.lstrip("#").strip()
            kind = "create_voice_channel" if name.lower().startswith("vocal :") else channel_kind
            if name.lower().startswith("vocal :"):
                name = name.split(":", 1)[1].strip()
            actions.append({"type": kind, "name": name, "category": category})
        else:
            actions.append({"type": "create_role", "name": name})
        if not name or len(name) > 100 or len(actions) > MAX_PLAN_ACTIONS:
            return []
    return merge_actions([actions]) if actions else []


def deletion_is_authorized(prompt: str) -> bool:
    """A negative instruction is never a license for model-produced deletion."""
    plain = norm(prompt)
    if re.search(r"\b(?:ne\s+supprim\w*\s+(?:aucun|pas)|sans\s+(?:aucune?\s+)?suppression|"
                 r"ne\s+supprim\w*\s+ni|conserve\w*\s+(?:tous|les)\s+(?:salons|roles))\b", plain):
        return False
    return bool(re.search(r"\b(?:supprime|supprimer|efface|effacer|delete)\s+"
                          r"(?:le|la|les|un|une|des)\s+(?:salons?|r[oô]les?|channels?)\b", plain))
