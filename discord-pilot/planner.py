"""Turn French requests into constrained, inspectable Discord operations."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from integration_catalog import PROVIDERS


ACTION_TYPES = {
    "create_category", "create_text_channel", "create_voice_channel",
    "create_role", "rename_channel", "rename_role", "set_topic",
    "send_message", "make_private", "delete_channel", "delete_role",
    "configure_welcome", "configure_farewell", "configure_invites",
    "suggest_integration",
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
    "configure_welcome": "Activer les messages d'arrivée",
    "configure_farewell": "Activer les messages de départ",
    "configure_invites": "Activer le suivi des invitations",
    "suggest_integration": "Préparer l'autorisation du bot externe",
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
    "configure_welcome": ("channel",),
    "configure_farewell": ("channel",),
    "configure_invites": ("channel",),
    "suggest_integration": ("provider",),
}

OPTIONAL = {
    "create_text_channel": ("category", "topic"),
    "create_voice_channel": ("category",),
    "create_role": ("color",),
}

# Small local models frequently understand the request correctly but use a
# Discord-style verb such as "create_channel" instead of our internal enum.
# Normalize only equivalent operations. Unsupported features (forums, bots,
# permission grants, automations...) must still fail closed.
MODEL_ACTION_ALIASES = {
    "create_channel": "create_text_channel", "add_channel": "create_text_channel",
    "new_channel": "create_text_channel", "create_text": "create_text_channel",
    "add_text_channel": "create_text_channel", "create_textual_channel": "create_text_channel",
    "create_voice": "create_voice_channel", "add_voice_channel": "create_voice_channel",
    "create_voice_room": "create_voice_channel", "create_vocal_channel": "create_voice_channel",
    "add_category": "create_category", "new_category": "create_category",
    "create_channel_category": "create_category",
    "add_role": "create_role", "new_role": "create_role",
    "update_channel_name": "rename_channel", "edit_channel_name": "rename_channel",
    "update_role_name": "rename_role", "edit_role_name": "rename_role",
    "edit_channel_topic": "set_topic", "set_channel_topic": "set_topic",
    "post_message": "send_message", "send_channel_message": "send_message",
    "private_channel": "make_private", "set_channel_private": "make_private",
    "remove_channel": "delete_channel", "remove_role": "delete_role",
    "creer_salon": "create_text_channel", "creer_un_salon": "create_text_channel",
    "creer_salon_textuel": "create_text_channel", "ajouter_salon": "create_text_channel",
    "creer_salon_vocal": "create_voice_channel", "ajouter_vocal": "create_voice_channel",
    "creer_categorie": "create_category", "ajouter_categorie": "create_category",
    "creer_role": "create_role", "ajouter_role": "create_role",
    "envoyer_message": "send_message", "publier_message": "send_message",
    "renommer_salon": "rename_channel", "renommer_role": "rename_role",
    "supprimer_salon": "delete_channel", "supprimer_role": "delete_role",
    "setup_welcome": "configure_welcome", "welcome_messages": "configure_welcome",
    "set_welcome": "configure_welcome", "configurer_bienvenue": "configure_welcome",
    "setup_goodbye": "configure_farewell", "goodbye_messages": "configure_farewell",
    "set_goodbye": "configure_farewell", "configurer_depart": "configure_farewell",
    "invite_tracker": "configure_invites", "track_invites": "configure_invites",
    "setup_invites": "configure_invites", "suivi_invitations": "configure_invites",
}

MODEL_FIELD_ALIASES = {
    "channel_name": "name", "role_name": "name", "category_name": "name",
    "old_name": "name", "target_name": "name", "parent_category": "category",
    "new_channel_name": "new_name", "new_role_name": "new_name",
    "message": "content", "text": "content", "description": "topic",
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


def requested_count(text: str) -> int | None:
    """Honor a precise small quantity without quietly omitting requested rooms."""
    match = re.search(r"\b(deux|trois|quatre|[234])\s+(?:salons?|channels?|canaux|chan|vocaux?|vocals?)\b", norm(text))
    return {"deux": 2, "trois": 3, "quatre": 4, "2": 2, "3": 3, "4": 4}.get(match.group(1)) if match else None


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
        if kind == "suggest_integration" and fields["provider"] not in PROVIDERS:
            raise ValueError("Application externe non référencée dans le catalogue officiel de Discord Pilot.")
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


def normalize_model_actions(value: Any) -> list[dict[str, str]]:
    """Convert common model vocabulary to our strict executable allowlist.

    Conversion is all-or-nothing. Unknown operations or fields cannot be
    silently discarded, because doing so would execute an incomplete plan.
    """
    if not isinstance(value, list):
        return validate_actions(value)
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Chaque action de l'IA doit être un objet JSON.")
        raw_type = item.get("type", item.get("action"))
        if not isinstance(raw_type, str):
            raise ValueError("L'IA n'a pas indiqué le type d'une action.")
        raw_alias = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw_type)
        alias = norm(raw_alias).replace("-", "_").replace(" ", "_")
        kind = MODEL_ACTION_ALIASES.get(alias, alias)
        if kind not in ACTION_TYPES:
            raise ValueError(f"Action non prise en charge par Discord Pilot : « {raw_type[:65]} ».")
        fields = {}
        for key, value in item.items():
            if key in {"type", "action"}:
                continue
            if not isinstance(key, str):
                raise ValueError("Nom de champ d'action invalide.")
            key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()
            if key == "category_name" and kind in {"create_text_channel", "create_voice_channel"}:
                canonical = "category"
            elif key == "role_name" and kind == "make_private":
                canonical = "role"
            elif key == "channel_name" and kind == "send_message":
                canonical = "channel"
            else:
                canonical = MODEL_FIELD_ALIASES.get(key, key)
            if canonical in fields and fields[canonical] != value:
                raise ValueError(f"Deux valeurs contradictoires pour {canonical}.")
            fields[canonical] = value
        channel_type = fields.pop("channel_type", None)
        if channel_type is not None:
            if alias not in {"create_channel", "add_channel", "new_channel", "create_text_channel", "create_voice_channel"}:
                raise ValueError("Le champ channel_type ne convient pas à cette action.")
            if not isinstance(channel_type, str):
                raise ValueError("Le type de salon doit être textuel ou vocal.")
            channel_type = norm(channel_type).strip()
            if channel_type in {"voice", "vocal", "audio", "guild_voice"}:
                new_kind = "create_voice_channel"
            elif channel_type in {"text", "texte", "textuel", "text_channel", "guild_text"}:
                new_kind = "create_text_channel"
            else:
                raise ValueError("Ce type de salon n'est pas pris en charge (textuel ou vocal uniquement).")
            if alias in {"create_text_channel", "create_voice_channel"} and new_kind != kind:
                raise ValueError("Type de salon contradictoire dans la réponse de l'IA.")
            kind = new_kind
        if (kind == "send_message" or kind.startswith("configure_")) and "name" in fields and "channel" not in fields:
            fields["channel"] = fields.pop("name")
        normalized.append({"type": kind, **fields})
    return validate_actions(normalized)


def parse_ollama_response(text: str) -> list[dict[str, str]]:
    actions, _question = parse_ollama_decision(text)
    return validate_actions(actions)


def parse_ollama_decision(text: str) -> tuple[list[dict[str, str]], str | None]:
    """Allow a local model to request missing information without guessing it."""
    text = text.strip()
    text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text, flags=re.I)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if isinstance(result, dict):
        question = result.get("question")
        actions = result.get("actions", result.get("operations", result.get("steps", [])))
        if not actions and ("type" in result or "action" in result):
            actions = [result]
        if actions:
            return normalize_model_actions(actions), None
        if isinstance(question, str) and 5 <= len(question.strip()) <= 300:
            return [], question.strip()
        return [], None
    return normalize_model_actions(result), None


SYSTEM_PROMPT = """Tu es l'assistant local Discord Pilot. Tu comprends le français familier, le franglais
(channel = salon, vocal = salon vocal, chan = salon), les fautes de frappe et les demandes en plusieurs phrases.
Tu proposes un plan de configuration Discord, jamais une exécution directe.
Réponds SEULEMENT avec {"actions":[...]}. L'application prépare un brouillon qui devra être
validé par l'utilisateur : n'entame pas une conversation de questions ou de précisions.
Si le nom d'un NOUVEAU salon manque, propose « nouveau-salon » ; si le nom d'un NOUVEAU
rôle manque, « Nouveau rôle » ; si le nom d'une NOUVELLE catégorie manque, « NOUVELLE CATÉGORIE ».
Ne devine jamais des messages à publier, des éléments à modifier ou des cibles de suppression.
Types autorisés et champs EXACTS :
create_category {type,name}
create_text_channel {type,name,category? ,topic?}
create_voice_channel {type,name,category?}
create_role {type,name,color?} (color: hex #RRGGBB uniquement)
configure_welcome {type,channel} (envoie un message lorsqu'un membre rejoint)
configure_farewell {type,channel} (envoie un message lorsqu'un membre quitte)
configure_invites {type,channel} (annonce chaque invitation attribuable et son compteur)
rename_channel {type,name,new_name}
rename_role {type,name,new_name}
set_topic {type,name,topic}
send_message {type,channel,content} (message explicite uniquement)
make_private {type,name,role} (role existant ou à créer; aucun accès pour @everyone)
delete_channel {type,name} (uniquement si demandé explicitement)
delete_role {type,name} (uniquement si demandé explicitement)
Pour les catégories, crée-les avant les salons. Utilise un plan précis, 40 actions maximum.
Ne crée jamais de rôle Administrateur avec des permissions dangereuses et n'ajoute aucun droit d'administrateur.
Si aucune action concrète sûre n'est possible, réponds {"actions":[]}.
Ne propose aucune action implicite en dehors de la demande. Évite les doublons.
Les trois automatisations exigent que le bot reste connecté et que l'intent Members soit activé.
"""


def community_automation_plan(prompt: str) -> list[dict[str, str]]:
    """Complete, reversible draft for combined joins/leaves/invite requests.

    Never guess an invite attribution, send a message immediately or install
    something on Discord. Only configure listeners on explicit event language.
    """
    normalized = norm(prompt)
    welcome = bool(re.search(r"\bbienvenu\w*\b", normalized) and
                   re.search(r"\b(?:arriv\w*|rejoin\w*|rejoi\w*|entre\w*|nouveau membre)\b", normalized))
    farewell = bool(re.search(r"\b(?:au[ -]revoir|depart\w*|quitt\w*)\b", normalized) and
                    re.search(r"\b(?:quitt\w*|part\b|sort\b|depart\w*)\b", normalized))
    invitations = bool(re.search(r"\binvit\w*\b", normalized) and
                       re.search(r"\b(?:personne\w*|utilisateur\w*|onzieme|premiere|dixieme|11|10|compte\w*)\b", normalized))
    if not any((welcome, farewell, invitations)):
        return []
    if re.search(r"\b(?:supprim\w*|banni\w*|sondage\w*|ticket\w*|musique|paiement\w*)\b", normalized):
        return []  # Do not silently omit unrelated requested features.

    already_welcome = bool(re.search(r"\bsalon\s+bienvenu\w*\b.{0,65}\b(?:deja|existe|cree)\b", normalized))
    welcome_name = "bienvenu" if re.search(r"\bsalon\s+bienvenu\b", normalized) else "bienvenue"
    creation_requested = bool(re.search(r"\b(?:cree\w*|creer|ajout\w*|rajout\w*)\s+(?:(?:un|une|des|les|trois|3)\s+)?salon", normalized))
    actions = []
    if creation_requested:
        if welcome and not already_welcome:
            actions.append(action("create_text_channel", name=welcome_name))
        if farewell:
            actions.append(action("create_text_channel", name="au-revoir"))
        if invitations:
            actions.append(action("create_text_channel", name="invitation"))
    if welcome:
        actions.append(action("configure_welcome", channel=welcome_name))
    if farewell:
        actions.append(action("configure_farewell", channel="au-revoir"))
    if invitations:
        actions.append(action("configure_invites", channel="invitation"))
    return validate_actions(actions)


def missing_information(prompt: str) -> str | None:
    """Ask a useful follow-up instead of returning a generic invalid request."""
    normalized = norm(prompt).strip(" .!?")
    if re.search(r"\b(?:ajout(?:e|er)?|rajout(?:e|er)?|cre(?:e|er)|fais|mettre|mets|veux|voudrais|souhaiterais)\b", normalized):
        if re.search(r"\b(?:channels?|chan|canal|canaux|salons?)\b(?:\s+(?:texte|textuel|vocal))?(?:\s+dans\s+(?:la\s+)?categorie\s+\S+)?$", normalized):
            return "Quel nom veux-tu donner au salon ? (Exemple : annonces)"
        if re.search(r"\brole\b$", normalized):
            return "Quel nom veux-tu donner au rôle ?"
        if re.search(r"\bcategorie\b$", normalized):
            return "Quel nom veux-tu donner à la catégorie ?"
    return None


def collapse_old_clarifications(prompt: str) -> str:
    """Remove obsolete 'Précision :' lines appended by older versions of the UI.

    Prefer the original request if it already names the actions. Otherwise a
    single name supplied in a previous answer can complete a simple creation.
    """
    lines = prompt.splitlines()
    details = [line.split(":", 1)[1].strip() for line in lines
               if re.match(r"^\s*pr[eé]cision\s*:", line, re.I)]
    if not details:
        return prompt.strip()
    original = "\n".join(line for line in lines
                         if not re.match(r"^\s*pr[eé]cision\s*:", line, re.I)).strip()
    if not original:
        return prompt.strip()
    if local_parse(original):
        return original
    if missing_information(original):
        name = clean_name(details[-1])
        if 1 <= len(name) <= 80:
            return f"{original} {name}"
    return original


def default_creation_plan(prompt: str) -> list[dict[str, str]]:
    """For incomplete *creation* requests propose reversible draft defaults."""
    if not missing_information(prompt):
        return []
    normalized = norm(prompt).strip(" .!?")
    if re.search(r"\b(?:channels?|chan|canal|canaux|salons?)\b", normalized):
        category = re.search(r"\bdans\s+(?:la\s+)?cat[eé]gorie\s+(.+)$", prompt, re.I)
        count = requested_count(prompt) or 1
        actions = []
        for index in range(count):
            payload = {"name": "nouveau-salon" if count == 1 else f"nouveau-salon-{index + 1}"}
            if category:
                payload["category"] = clean_name(category.group(1))
            actions.append(action("create_text_channel", **payload))
        return validate_actions(actions)
    if re.search(r"\broles?\b", normalized):
        return validate_actions([action("create_role", name="Nouveau rôle")])
    if re.search(r"\bcategorie\b", normalized):
        return validate_actions([action("create_category", name="NOUVELLE CATÉGORIE")])
    return []


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
    stated_want = bool(re.match(r"(?i)^\s*(?:bonjour[,.!]?\s+|salut[,.!]?\s+|alors\s+|du coup\s+|bon\s+|ok\s+)*(?:je veux|je voudrais|j['’]aimerais|je souhaiterais|tu peux|peux.tu|est.ce que tu peux|pourrais.tu|il faut|il faudrait)\b", prompt))
    # Speech input is conversational: the actual command often follows
    # "je veux", "tu peux me" or "j'aimerais que tu". Strip only these
    # harmless wrappers, never the operation or its target.
    prompt = re.sub(
        r"(?i)^\s*(?:(?:bonjour|salut|alors|du coup|ok|bon)[,.!]?\s+)*"
        r"(?:est.ce que tu peux|tu peux|peux.tu|pourrais.tu|je veux|"
        r"je voudrais|j['’]aimerais|je souhaiterais|il faut|il faudrait)\s+"
        r"(?:(?:que tu|me|m'|nous)\s*)*",
        "", prompt.strip())
    prompt = re.sub(r"(?i)^\s*(?:que tu|me|m')\s+", "", prompt)
    # Semicolons/newlines are unambiguous, unlike commas in role or channel lists.
    prompt = re.sub(r"\s+et\s+(?=(?:cr[eé]e|ajoute|renomme|supprime|rends?|publie|envoie)\b)", "; ", prompt, flags=re.I)
    prompt = re.sub(r"\s+et\s+(?=(?:un|une|des|les)\s+(?:r[oô]les?|salons?|cat[eé]gorie)\b)", "; crée ", prompt, flags=re.I)
    clauses = [c.strip() for c in re.split(r"[;\n]+|\s+\b(?:puis|ensuite|apr[eè]s)\b\s+", prompt, flags=re.I) if c.strip()]
    for clause in clauses:
        clause = clause.strip().strip(".!")
        clause = re.sub(r"(?i)^\s*(?:et\s+)?(?:je veux|je voudrais|j['’]aimerais|tu peux me)\s+", "", clause)
        clause = re.sub(r"(?i)^\s*(?:un autre|une autre)\s+(?=(?:salon|channel|canal|r[oô]le)\b)", "crée un ", clause)
        if (stated_want or results) and re.match(r"(?i)^(?:un|une|des|deux|trois|2|3)\s+(?:salons?|channels?|canal|canaux|chan|vocaux?|vocal|r[oô]le|cat[eé]gorie)\b", clause):
            clause = "crée " + clause
        # These imply additional behavior that the offline interpreter cannot guarantee.
        if re.search(r"\bet\s+(?:lance|programme|active|configure|automatis|connecte|installe|param[eè]tre)\b", clause, re.I):
            return []
        prefix = r"(?:cr[eé]e(?:s|r)?|ajoute|ajouter|rajoute|rajouter|fais|faire|mets|mettre|je veux|il me faut|installe|installer)(?:-moi)?"
        salon_word = r"(?:salons?|channels?|canal|canaux|chan|vocaux?|vocal)"
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
        m = re.match(rf"^(?:{prefix}\s+)(?:(?:un|une|des|les?|la|deux|trois|quatre|2|3|4)\s+)?({salon_word})\s+(?:(vocaux?|vocal|textuels?|textes?)\s+)?(?:(?:nomm[eé]s?|appel[eé]s?|qui s'appelle)\s+)?(.+?)(?:\s+dans\s+(?:la\s+)?cat[eé]gorie\s+(.+))?$", clause, re.I)
        if m:
            kind = "create_voice_channel" if norm(m.group(1)).startswith("voc") or (m.group(2) and norm(m.group(2)).startswith("voc")) else "create_text_channel"
            names = split_names(re.sub(r"(?i)^(?:(?:de|pour)\s+(?:les?|des|la|l')?\s*)", "", m.group(3)).strip())
            count = requested_count(clause)
            if count and len(names) > count:
                return []
            if count and len(names) < count:
                names.extend(f"nouveau-salon-{n}" for n in range(len(names) + 1, count + 1))
            category = clean_name(m.group(4)) if m.group(4) else None
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
    if item["type"] == "suggest_integration":
        return f"{label} : {PROVIDERS[item['provider']]['name']} (validation Discord obligatoire)"
    if item["type"].startswith("configure_"):
        return f"{label} dans #{item['channel']} (bot local connecté requis)"
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
