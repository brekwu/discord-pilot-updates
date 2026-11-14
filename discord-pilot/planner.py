"""Turn French requests into constrained, inspectable Discord operations."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


ACTION_TYPES = {
    "create_category", "create_text_channel", "create_voice_channel",
    "create_role", "rename_channel", "rename_role", "set_topic",
    "send_message", "make_private", "delete_channel", "delete_role",
}

ACTION_LABELS = {
    "create_category": "Créer la catégorie",
    "create_text_channel": "Créer le salon textuel",
    "create_voice_channel": "Créer le salon vocal",
    "create_role": "Créer le rôle",
    "rename_channel": "Renommer le salon",
    "rename_role": "Renommer le rôle",
    "set_topic": "Modifier la description du salon",
    "send_message": "Publier un message",
    "make_private": "Rendre le salon privé",
    "delete_channel": "Supprimer le salon",
    "delete_role": "Supprimer le rôle",
}

DANGEROUS_ACTIONS = {"delete_channel", "delete_role"}

FIELDS = {
    "create_category": ("name",),
    "create_text_channel": ("name",),
    "create_voice_channel": ("name",),
    "create_role": ("name",),
    "rename_channel": ("name", "new_name"),
    "rename_role": ("name", "new_name"),
    "set_topic": ("name", "topic"),
    "send_message": ("channel", "content"),
    "make_private": ("name", "role"),
    "delete_channel": ("name",),
    "delete_role": ("name",),
}

OPTIONAL = {
    "create_text_channel": ("category", "topic"),
    "create_voice_channel": ("category",),
    "create_role": ("color",),
}


def compact(value: str) -> str:
    return " ".join(value.strip().split())


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch)).strip()


def clean_name(value: str) -> str:
    value = compact(value.strip("`'\"“”«»#•- "))
    return re.sub(r"[.!?]+$", "", value).strip()


def split_names(raw: str) -> list[str]:
    raw = re.sub(r"\s+(?:et|ainsi que)\s+", ",", raw, flags=re.I)
    raw = raw.replace(" / ", ",")
    return [name for piece in raw.split(",") if (name := clean_name(piece))]


def action(action_type: str, **kwargs: str) -> dict[str, str]:
    return {"type": action_type, **kwargs}


def validate_actions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value or len(value) > 40:
        raise ValueError("Le plan doit contenir entre 1 et 40 actions.")
    verified = []
    for item in value:
        if not isinstance(item, dict) or item.get("type") not in ACTION_TYPES:
            raise ValueError("Type d'action inconnu ou interdit.")
        kind = item["type"]
        allowed = {"type", *FIELDS[kind], *OPTIONAL.get(kind, ())}
        if set(item) - allowed:
            raise ValueError(f"Champs non autorisés dans {kind}.")
        fields = {}
        for key in FIELDS[kind]:
            val = item.get(key)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"Le champ {key} est requis pour {kind}.")
            fields[key] = compact(val)
        for key in OPTIONAL.get(kind, ()):
            if key in item:
                if not isinstance(item[key], str) or not item[key].strip():
                    raise ValueError(f"Champ optionnel {key} invalide.")
                fields[key] = compact(item[key])
        if kind == "send_message" and len(fields["content"]) > 1800:
            raise ValueError("Le message dépasse la limite de 1 800 caractères.")
        if kind != "send_message" and any(len(v) > 900 for v in fields.values()):
            raise ValueError("Valeur trop longue.")
        if "name" in fields and len(fields["name"]) > 100:
            raise ValueError("Nom limité à 100 caractères.")
        if "new_name" in fields and len(fields["new_name"]) > 100:
            raise ValueError("Nom limité à 100 caractères.")
        verified.append({"type": kind, **fields})
    return verified


def parse_ollama_response(text: str) -> list[dict[str, str]]:
    actions, _question = parse_ollama_decision(text)
    return validate_actions(actions)


def parse_ollama_decision(text: str) -> tuple[list[dict[str, str]], str | None]:
    """Allow a local model to request missing information without guessing it."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if isinstance(result, dict):
        question = result.get("question")
        actions = result.get("actions", [])
        if actions:
            return validate_actions(actions), None
        if isinstance(question, str) and 5 <= len(question.strip()) <= 300:
            return [], question.strip()
        return [], None
    return validate_actions(result), None


SYSTEM_PROMPT = """Tu es l'assistant local Discord Pilot. Tu comprends le français familier, le franglais
(channel = salon, vocal = salon vocal, chan = salon), les fautes de frappe et les demandes en plusieurs phrases.
Tu proposes un plan de configuration Discord, jamais une exécution directe.
Réponds SEULEMENT avec {"actions":[...]}, OU {"actions":[],"question":"..."} si une information
indispensable manque (par exemple « rajoute un channel » sans nom : demande quel nom lui donner).
Ne devine jamais des noms, des messages à publier, des catégories ou des cibles de suppression.
Types autorisés et champs EXACTS :
create_category {type,name}
create_text_channel {type,name,category? ,topic?}
create_voice_channel {type,name,category?}
create_role {type,name,color?} (color: hex #RRGGBB uniquement)
rename_channel {type,name,new_name}
rename_role {type,name,new_name}
set_topic {type,name,topic}
send_message {type,channel,content} (message explicite uniquement)
make_private {type,name,role} (role existant ou à créer; aucun accès pour @everyone)
delete_channel {type,name} (uniquement si demandé explicitement)
delete_role {type,name} (uniquement si demandé explicitement)
Pour les catégories, crée-les avant les salons. Utilise un plan précis, 40 actions maximum.
Ne crée jamais de rôle Administrateur avec des permissions dangereuses et n'ajoute aucun droit d'administrateur.
Si la demande est ambiguë, réponds avec une question claire et courte, sans actions.
Si la demande n'indique aucune action concrète parmi celles-ci, réponds {"actions":[],"question":"Quelle modification précise veux-tu faire ?"}.
Ne propose aucune action implicite en dehors de la demande. Évite les doublons.
"""


def missing_information(prompt: str) -> str | None:
    """Ask a useful follow-up instead of returning a generic invalid request."""
    normalized = norm(prompt).strip(" .!?")
    if re.search(r"\b(?:ajout(?:e|er)?|rajout(?:e|er)?|cre(?:e|er)|fais|mettre|mets)\b", normalized):
        if re.search(r"\b(?:channels?|chan|canal|canaux|salons?)\b(?:\s+(?:texte|textuel|vocal))?(?:\s+dans\s+(?:la\s+)?categorie\s+\S+)?$", normalized):
            return "Quel nom veux-tu donner au salon ? (Exemple : annonces)"
        if re.search(r"\brole\b$", normalized):
            return "Quel nom veux-tu donner au rôle ?"
        if re.search(r"\bcategorie\b$", normalized):
            return "Quel nom veux-tu donner à la catégorie ?"
    return None


PRESETS = {
    "communaute": {
        "label": "Serveur communauté",
        "description": "Accueil, discussions, vocal et rôles de base",
        "actions": [
            action("create_category", name="ACCUEIL"),
            action("create_text_channel", name="bienvenue", category="ACCUEIL"),
            action("create_text_channel", name="reglement", category="ACCUEIL"),
            action("create_text_channel", name="annonces", category="ACCUEIL"),
            action("create_category", name="COMMUNAUTÉ"),
            action("create_text_channel", name="general", category="COMMUNAUTÉ"),
            action("create_text_channel", name="media", category="COMMUNAUTÉ"),
            action("create_voice_channel", name="Vocal 1", category="COMMUNAUTÉ"),
            action("create_voice_channel", name="Vocal 2", category="COMMUNAUTÉ"),
            action("create_role", name="Membre"),
            action("create_role", name="Modérateur"),
        ],
    },
    "support": {
        "label": "Assistance / SAV",
        "description": "Informations, questions et espace privé équipe",
        "actions": [
            action("create_category", name="INFORMATIONS"),
            action("create_text_channel", name="informations", category="INFORMATIONS"),
            action("create_text_channel", name="faq", category="INFORMATIONS"),
            action("create_category", name="SUPPORT"),
            action("create_text_channel", name="aide-et-support", category="SUPPORT"),
            action("create_text_channel", name="suivi-des-demandes", category="SUPPORT"),
            action("create_role", name="Équipe Support"),
            action("create_text_channel", name="equipe-privee", category="SUPPORT"),
            action("make_private", name="equipe-privee", role="Équipe Support"),
        ],
    },
    "tournoi": {
        "label": "Tournoi esport",
        "description": "Check-in, informations, matchs et vocaux",
        "actions": [
            action("create_category", name="TOURNOI"),
            action("create_text_channel", name="annonces-tournoi", category="TOURNOI"),
            action("create_text_channel", name="reglement-tournoi", category="TOURNOI"),
            action("create_text_channel", name="check-in", category="TOURNOI"),
            action("create_text_channel", name="planning-matchs", category="TOURNOI"),
            action("create_category", name="EQUIPES"),
            action("create_text_channel", name="recherche-equipe", category="EQUIPES"),
            action("create_voice_channel", name="Equipe A", category="EQUIPES"),
            action("create_voice_channel", name="Equipe B", category="EQUIPES"),
            action("create_role", name="Joueur"),
            action("create_role", name="Organisateur"),
        ],
    },
    "entreprise": {
        "label": "Espace entreprise",
        "description": "Actualités, projets et espace réservé à l'équipe",
        "actions": [
            action("create_category", name="ENTREPRISE"),
            action("create_text_channel", name="informations", category="ENTREPRISE"),
            action("create_text_channel", name="annonces", category="ENTREPRISE"),
            action("create_category", name="EQUIPE"),
            action("create_role", name="Collaborateur"),
            action("create_text_channel", name="discussion-interne", category="EQUIPE"),
            action("make_private", name="discussion-interne", role="Collaborateur"),
            action("create_text_channel", name="suivi-projets", category="EQUIPE"),
            action("make_private", name="suivi-projets", role="Collaborateur"),
        ],
    },
}


def local_parse(prompt: str) -> list[dict[str, str]]:
    """Deterministic, intentionally narrow offline parser. No guessing."""
    results: list[dict[str, str]] = []
    # Semicolons/newlines are unambiguous, unlike commas in role or channel lists.
    prompt = re.sub(r"\s+et\s+(?=(?:cr[eé]e|ajoute|renomme|supprime|rends?|publie|envoie)\b)", "; ", prompt, flags=re.I)
    prompt = re.sub(r"\s+et\s+(?=(?:un|une|des|les)\s+(?:r[oô]les?|salons?|cat[eé]gorie)\b)", "; crée ", prompt, flags=re.I)
    clauses = [c.strip() for c in re.split(r"[;\n]+|\s+\bpuis\b\s+", prompt, flags=re.I) if c.strip()]
    for clause in clauses:
        clause = clause.strip().strip(".!")
        # These imply additional behavior that the offline interpreter cannot guarantee.
        if re.search(r"\bet\s+(?:lance|programme|active|configure|automatis|connecte|installe|param[eè]tre)\b", clause, re.I):
            return []
        prefix = r"(?:cr[eé]e|cr[eé]er|ajoute|ajouter|rajoute|rajouter|fais|faire|mets|mettre|je veux|il me faut|installe|installer)(?:-moi)?"
        salon_word = r"(?:salons?|channels?|canal|canaux|chan)"
        # Editing commands must precede the generic "salon" extractor.
        m = re.search(rf"\b(?:renomme|renommer)\s+(?:le\s+)?{salon_word}\s+(.+?)\s+(?:en|par)\s+(.+)$", clause, re.I)
        if m:
            results.append(action("rename_channel", name=clean_name(m.group(1)), new_name=clean_name(m.group(2))))
            continue
        m = re.search(r"\b(?:renomme|renommer)\s+(?:le\s+)?r[oô]le\s+(.+?)\s+(?:en|par)\s+(.+)$", clause, re.I)
        if m:
            results.append(action("rename_role", name=clean_name(m.group(1)), new_name=clean_name(m.group(2))))
            continue
        m = re.search(r"\b(?:envoie|envoyer|publie|publier|poste|poster)\s+[«\"'](.+?)[»\"']\s+(?:dans|sur)\s+(?:le\s+salon\s+)?#?([\w\-]+)", clause, re.I)
        if m:
            results.append(action("send_message", channel=m.group(2), content=m.group(1)))
            continue
        m = re.search(rf"\b(?:rend|rends|rendre|mets|mettre)\s+(?:le\s+)?{salon_word}\s+([\w\-]+)\s+priv[eé]\s+(?:pour|au|[aà])\s+(?:le\s+)?r[oô]le\s+(.+)$", clause, re.I)
        if m:
            results.append(action("make_private", name=clean_name(m.group(1)), role=clean_name(m.group(2))))
            continue
        m = re.search(rf"\b(?:supprime|supprimer)\s+(?:le\s+)?({salon_word}|r[oô]le)\s+(.+)$", clause, re.I)
        if m:
            results.append(action("delete_role" if norm(m.group(1)) == "role" else "delete_channel", name=clean_name(m.group(2))))
            continue
        # Category + attached channel names in one clause.
        m = re.match(rf"^(?:{prefix}\s+)(?:(?:une?|la)\s+)?cat[eé]gorie\s+[«\"']?(.+?)[»\"']?\s+avec\s+(?:les?\s+)?{salon_word}\s+(.+)$", clause, re.I)
        if m:
            category = clean_name(m.group(1))
            names = split_names(m.group(2))
            if category and names:
                results.append(action("create_category", name=category))
                results.extend(action("create_text_channel", name=n, category=category) for n in names)
                continue
        m = re.match(rf"^(?:{prefix}\s+)(?:(?:une?|la)\s+)?cat[eé]gorie\s+(?:nomm[eé]e?\s+|appel[eé]e?\s+)?(.+)$", clause, re.I)
        if m:
            name = clean_name(m.group(1))
            if name and not re.search(r"\s+et\s+(?:un|une|des|les)\b|,\s*(?:cr[eé]e|ajoute)\b", name, re.I):
                results.append(action("create_category", name=name))
                continue
        m = re.match(rf"^(?:{prefix}\s+)(?:les?|des|un)\s+r[oô]les?\s+(?:nomm[eé]s?\s+|appel[eé]s?\s+)?(.+)$", clause, re.I)
        if m:
            names = split_names(m.group(1))
            results.extend(action("create_role", name=n) for n in names)
            continue
        m = re.match(rf"^(?:{prefix}\s+)(?:(?:un|une|des|les?|la)\s+)?{salon_word}\s+(?:(vocaux?|vocal|textuels?|textes?)\s+)?(?:(?:nomm[eé]|appel[eé]|qui s'appelle)\s+)?(.+?)(?:\s+dans\s+(?:la\s+)?cat[eé]gorie\s+(.+))?$", clause, re.I)
        if m:
            kind = "create_voice_channel" if m.group(1) and norm(m.group(1)).startswith("voc") else "create_text_channel"
            names = split_names(m.group(2))
            category = clean_name(m.group(3)) if m.group(3) else None
            for name in names:
                payload = {"name": name}
                if category:
                    payload["category"] = category
                results.append(action(kind, **payload))
            continue
        # An unrecognized clause invalidates the whole offline plan: no silent omissions.
        return []
    return validate_actions(results) if results else []


def description(item: dict[str, str]) -> str:
    label = ACTION_LABELS[item["type"]]
    if item["type"] == "send_message":
        return f"{label} dans #{item['channel']} : {item['content'][:80]}"
    if item["type"] == "make_private":
        return f"{label} #{item['name']} pour @{item['role']}"
    text = f"{label} « {item['name']} »"
    if "new_name" in item:
        text += f" → « {item['new_name']} »"
    if "category" in item:
        text += f" dans {item['category']}"
    return text
