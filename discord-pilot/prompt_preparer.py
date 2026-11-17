"""Conservative French request interpreter sitting before the action planner.

This layer may restate a permission ONLY when the user explicitly named both
the target channels and a universal writing restriction.  It does not guess
extra roles, grant permissions, or silently discard additional instructions.
"""

from __future__ import annotations

import re

from planner import clean_name, norm


_ALL_MEMBERS = r"(?:tout\s+le\s+monde|@everyone|tous\s+les\s+utilisateurs)"
_WRITE = r"(?:[eé]crire|envoyer\s+(?:des?\s+)?messages?)"
_END = r"(?:\s+(?:dedans|dans\s+ces\s+salons?|sur\s+ces\s+salons?))?\s*[.!?]*"

_NEGATIVE_WRITING = (
    rf"pour\s+pas\s+que\s+{_ALL_MEMBERS}\s+(?:puisse|puissent|peut|peuvent)\s+{_WRITE}{_END}",
    rf"pour\s+que\s+{_ALL_MEMBERS}\s+ne\s+(?:puisse|puissent|peut|peuvent)\s+pas\s+{_WRITE}{_END}",
    rf"pour\s+(?:emp[eê]cher|interdire)\s+(?:[àa]\s+)?{_ALL_MEMBERS}\s+d['’e]\s*{_WRITE}{_END}",
    rf"afin\s+que\s+personne\s+ne\s+(?:puisse|puisse\s+plus)\s+{_WRITE}{_END}",
    rf"pour\s+que\s+personne\s+ne\s+(?:puisse|puisse\s+plus)\s+{_WRITE}{_END}",
)

_WRITE_FIRST = re.compile(
    rf"^(?:emp[eê]che(?:r)?|interdi(?:s|re))\s+(?:[àa]\s+)?{_ALL_MEMBERS}\s+"
    rf"d['’e]\s*{_WRITE}\s+(?:dans|sur)\s+(?:les?\s+)?salons?\s+(.+?)\s*[.!?]*$",
    re.I,
)

_PREFIX = re.compile(
    r"\b(?:modifi\w*|chang\w*|configur\w*|r[eè]gl\w*|"
    r"param[eé]tr\w*|mets?|mettre|ajust\w*|restr\w*|interdi\w*|emp[eê]ch\w*)\b",
    re.I,
)


def _named_channels(raw: str) -> list[str]:
    # A comma or explicit conjunction separates channels; spaces belong to
    # names, e.g. the existing Discord channel "au revoir".
    names = re.split(r"\s*(?:,|\bet\b|\bainsi\s+que\b)\s*", raw, flags=re.I)
    if not 1 <= len(names) <= 20:
        return []
    cleaned = []
    seen = set()
    for raw_name in names:
        name = clean_name(raw_name.strip().lstrip("#")).strip()
        normalized = norm(name)
        if (not 1 <= len(name) <= 90 or not re.fullmatch(r"[\w\s\-]+", name, re.U)
                or normalized in {"tous", "tout", "les", "salons", "nouveaux"}
                or re.search(r"\b(?:role|roles|salon|salons|permissions|et|puis)\b", normalized)):
            return []
        if normalized not in seen:
            cleaned.append(name)
            seen.add(normalized)
    return cleaned


def _deny_everyone_writing(prompt: str) -> list[str]:
    text = re.sub(r"\s+", " ", prompt).strip()
    # Only one well-delimited instruction can be safely rewritten. Do not
    # lose an unknown instruction after a semicolon or in another sentence.
    if any(marker in text for marker in (";", "\n")):
        return []
    m = re.fullmatch(
        r"(?P<prefix>.*?)\b(?:les?\s+)?salons?\s+"
        r"(?P<names>.+?)\s+(?P<restriction>(?:pour|afin)\s+.+)",
        text, re.I,
    )
    if m and _PREFIX.search(m.group("prefix")):
        restriction = m.group("restriction")
        if any(re.fullmatch(pattern, restriction, re.I) for pattern in _NEGATIVE_WRITING):
            return _named_channels(m.group("names"))
    # Direct form: "Empêche tout le monde d'écrire dans les salons A, B".
    direct = _WRITE_FIRST.fullmatch(text)
    return _named_channels(direct.group(1)) if direct else []


def prepare_prompt(original: str) -> dict:
    """Return an editable reformulation and an explicit provenance label."""
    prompt = original.strip()
    channels = _deny_everyone_writing(prompt)
    if channels:
        canonical = ";\n".join(
            f"Interdis au rôle @everyone d'écrire dans le salon {name}"
            for name in channels
        )
        return {
            "original": prompt,
            "rewritten": canonical,
            "changed": True,
            "source": "interpréteur local contrôlé",
            "explanation": (
                f"{len(channels)} salon(s) ciblé(s). @everyone ne pourra plus y envoyer de messages. "
                "La visibilité des salons et les autres rôles restent inchangés. "
                "Vérifie le brouillon avant toute application."
            ),
        }
    return {
        "original": prompt,
        "rewritten": prompt,
        "changed": False,
        "source": "demande conservée",
        "explanation": (
            "Aucune reformulation suffisamment sûre n'a été trouvée. "
            "Tu peux préciser les salons, les rôles et l'effet souhaité, "
            "ou utiliser Ollama si un modèle local est installé."
        ),
    }
