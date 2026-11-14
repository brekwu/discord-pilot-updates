"""Curated, static third-party integrations. No bot token or user OAuth is used here.

An external application's website is an *entry point* to its own Discord
authorization flow. It is never evidence that the application was installed.
"""

from __future__ import annotations

import unicodedata


PROVIDERS = {
    "jockie": {"name": "Jockie Music", "url": "https://www.jockiemusic.com/", "kind": "Musique et blind tests"},
    "lyx": {"name": "Lyx", "url": "https://lyx.lol/", "kind": "Niveaux, rôles, animations"},
    "wick": {"name": "Wick", "url": "https://wickbot.com/", "kind": "Sécurité et anti-raid"},
    "carl": {"name": "Carl-bot", "url": "https://carl.gg/", "kind": "Modération, rôles, flux"},
    "streamcord": {"name": "Streamcord", "url": "https://streamcord.io/", "kind": "Alertes Twitch, YouTube et Kick"},
    "sesh": {"name": "sesh", "url": "https://sesh.fyi/", "kind": "Événements et calendrier"},
    "tickettool": {"name": "Ticket Tool", "url": "https://ticket-tool.app/", "kind": "Support et tickets"},
    "xenon": {"name": "Xenon", "url": "https://xenon.bot/", "kind": "Sauvegardes et modèles"},
    "statbot": {"name": "Statbot", "url": "https://statbot.net/", "kind": "Statistiques serveur"},
}

# The 90 catalogue entries are informational: some require bespoke development
# or a third-party account and are explicitly marked as non-installable.
CATEGORIES = [
    ("Musique et audio", "🎵", [
        "Musique en vocal", "Files d'attente musicales", "Playlists personnalisées",
        "Lecture, pause, suivant et volume", "Radio musicale", "Blind tests musicaux",
        "Soundboard avec sons personnalisés", "Effets sonores sur commande",
        "Synthèse vocale des messages", "Musique d'ambiance en vocal",
    ]),
    ("Niveaux et récompenses", "🏆", [
        "XP pour les messages", "XP en vocal", "Niveaux des membres",
        "Classement général des membres", "Récompenses selon le niveau",
        "Titres et badges personnalisés", "Classement des recruteurs",
        "Récompenses selon les invitations", "Récompenses pour les membres actifs",
        "Succès et trophées", "Récompenses pour les boosts", "Réputation entre membres",
    ]),
    ("Modération et sécurité", "🛡️", [
        "Protection anti-raid", "Protection des comptes suspects", "CAPTCHA à l'arrivée",
        "Détection des comptes récents", "Antispam", "Antipublicité",
        "Détection des liens malveillants", "Filtrage des insultes",
        "Sanctions progressives", "Avertissements", "Bannissements temporaires",
        "Historique des sanctions", "Journal des messages modifiés ou supprimés",
        "Protection contre les destructions massives", "Protection contre les abus de permissions",
        "Signalement des utilisateurs",
    ]),
    ("Gaming et compétitions", "🎮", [
        "Tournois automatiques", "Inscriptions des joueurs et équipes", "Check-in",
        "Brackets", "Annonces de matchs", "Résultats et classements",
        "Classement ELO", "Recherche de coéquipiers", "Recherche d'adversaires",
        "Organisation de scrims", "Statistiques de joueurs",
        "Classements Rocket League, Valorant et Clash of Clans",
        "Création de lobbies", "Récompenses des gagnants", "Calendrier des tournois",
        "Rappels avant les matchs",
    ]),
    ("Animation et divertissement", "🎉", [
        "Giveaways", "Quiz interactifs", "Sondages automatiques",
        "Défis quotidiens", "Questions-réponses", "Mini-jeux", "Devinettes",
        "Économie virtuelle", "Boutique virtuelle", "Roue de la chance fictive",
        "Anniversaires", "Anniversaires d'arrivée", "Messages humoristiques",
        "Citations populaires", "Classement des messages", "Événements programmés",
    ]),
    ("Réseaux sociaux", "📱", [
        "Alertes Twitch", "Nouvelles vidéos YouTube", "Annonces YouTube Shorts",
        "Notifications TikTok", "Notifications Instagram", "Alertes Kick",
        "Publication des nouveaux contenus", "Annonces d'événements",
        "Rôle streamer en direct", "Calendrier des streams",
        "Statistiques des réseaux sociaux", "Flux RSS de sites web",
    ]),
    ("Support et entreprise", "🎫", [
        "Tickets privés", "Modmail", "Formulaires de candidature",
        "FAQ automatique", "Attribution des tickets", "Archivage du support",
        "Satisfaction après ticket", "Sauvegarde et restauration du serveur",
    ]),
]

# A recommendation is offered only where the named provider is known to
# support that category of capability; other items remain ideas to develop.
FEATURE_PROVIDERS = {
    **{n: "jockie" for n in (1, 2, 3, 4, 5, 6)},
    **{n: "lyx" for n in (11, 12, 13, 14, 15, 18, 19, 21, 55, 65)},
    **{n: "wick" for n in (23, 24, 25, 26, 27, 29, 36, 37)},
    **{n: "carl" for n in (28, 30, 31, 32, 33, 34, 35, 38, 82)},
    **{n: "sesh" for n in (57, 70, 78, 80)},
    **{n: "streamcord" for n in (71, 72, 76)},
    **{n: "statbot" for n in (81,)},
    **{n: "tickettool" for n in (83, 85, 87, 88, 89)},
    **{n: "lyx" for n in (84, 86)},
    **{n: "xenon" for n in (90,)},
}

# Only exact, already implemented native functions are marked available.
# This is not an estimate of how many catalogue ideas are complete.
FEATURE_NATIVE = {
    11: "xp", 13: "xp", 14: "xp", 27: "antispam",
    30: "wordfilter", 35: "audit", 55: "giveaway",
    56: "quiz", 57: "poll", 83: "tickets",
    84: "modmail", 85: "applications",
    15: "level_rewards", 17: "invite_rewards", 18: "invite_rewards",
    32: "warnings", 69: "activity_stats",
}


def all_features() -> list[dict]:
    features = []
    for category, icon, names in CATEGORIES:
        for title in names:
            number = len(features) + 1
            provider_id = FEATURE_PROVIDERS.get(number)
            native_module = FEATURE_NATIVE.get(number)
            features.append({
                "id": f"feature-{number:03d}", "number": number, "title": title,
                "category": category, "icon": icon,
                "provider_id": provider_id,
                "native_module": native_module,
                "availability": "native" if native_module else "external" if provider_id else "planned",
            })
    return features


def catalog() -> dict:
    return {"features": all_features(), "providers": PROVIDERS,
            "disclaimer": "Un lien officiel ne constitue pas une installation. Autorise le bot tiers via Discord."}


def _norm(value: str) -> str:
    decomp = unicodedata.normalize("NFKD", value.lower())
    return "".join(ch for ch in decomp if not unicodedata.combining(ch))


def recommended_providers(prompt: str) -> list[str]:
    """Conservative keyword router for explicitly requested external services.

    Only for prompts that request bots/plugins/services; not a general natural
    language planner (which must never silently ignore unknown extra actions).
    """
    text = _norm(prompt)
    if any(s in text for s in ("salon", "categorie", "supprim", "renomm", "role ", "publie ")):
        return []
    if not any(s in text for s in ("ajout", "instal", "met", "mets", "configure", "integre", "bot", "active", "veux")):
        return []
    triggers = [
        ("jockie", ("musique", "musical", "playlist", "blind test", "radio")),
        ("tickettool", ("ticket", "support", "sav")),
        ("wick", ("anti-raid", "antiraid", "securite", "securise", "captcha", "anti raid")),
        ("carl", ("moderation", "automod", "reaction role", "roles reactions")),
        ("lyx", ("niveau", "xp", "giveaway", "anniversaire", "modmail")),
        ("streamcord", ("twitch", "youtube", "kick", "streamer", "stream", "live")),
        ("sesh", ("calendrier", "evenement", "sondage", "rsvp")),
        ("statbot", ("statistique", "analytics", "analytique")),
        ("xenon", ("sauvegarde", "backup", "restaur")),
    ]
    matches = [provider_id for provider_id, terms in triggers if any(term in text for term in terms)]
    return matches if len(matches) <= 8 else []
