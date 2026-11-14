"""Validation and deterministic formatting for interactive Discord events."""

from __future__ import annotations

from datetime import datetime, timezone
import re


OPTION_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")
MAX_EVENT_MINUTES = 7 * 24 * 60


def validate_event(kind: str, data: dict, guild) -> dict:
    if kind not in {"poll", "giveaway"} or not isinstance(data, dict):
        raise ValueError("Type d'événement inconnu.")
    expected = {"channel_id", "minutes", "question", "options"} if kind == "poll" else {
        "channel_id", "minutes", "prize"}
    if set(data) != expected:
        raise ValueError("Il manque un champ ou un paramètre inconnu est présent.")
    channel_id = data["channel_id"]
    if not isinstance(channel_id, str) or not re.fullmatch(r"[0-9]{17,20}", channel_id):
        raise ValueError("Salon Discord invalide.")
    channel = guild.get_channel(int(channel_id))
    if channel is None or str(getattr(channel, "type", "")) != "text":
        raise ValueError("Le salon textuel doit appartenir au serveur sélectionné.")
    minutes = data["minutes"]
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= MAX_EVENT_MINUTES:
        raise ValueError("Durée requise : 1 à 10 080 minutes (7 jours).")
    result = {"type": kind, "channel_id": channel_id, "minutes": minutes}
    if kind == "poll":
        question, options = data["question"], data["options"]
        if not isinstance(question, str) or not 3 <= len(question.strip()) <= 200:
            raise ValueError("Question requise : 3 à 200 caractères.")
        if (not isinstance(options, list) or not 2 <= len(options) <= 9
                or any(not isinstance(option, str) or not 1 <= len(option.strip()) <= 90 for option in options)):
            raise ValueError("Le sondage nécessite 2 à 9 réponses (90 caractères maximum chacune).")
        answers = [option.strip() for option in options]
        if len(set(option.casefold() for option in answers)) != len(answers):
            raise ValueError("Les réponses doivent être différentes.")
        result.update(question=question.strip(), options=answers)
    else:
        prize = data["prize"]
        if not isinstance(prize, str) or not 2 <= len(prize.strip()) <= 200:
            raise ValueError("Indique un lot de 2 à 200 caractères.")
        result["prize"] = prize.strip()
    return result


def poll_summary(question: str, options: list[str], votes: list[int]) -> str:
    if len(options) != len(votes) or not 1 <= len(options) <= len(OPTION_EMOJIS):
        raise ValueError("Résultats du sondage incohérents.")
    maximum = max(votes)
    leaders = [options[i] for i, count in enumerate(votes) if count == maximum]
    lines = [f"{OPTION_EMOJIS[i]} {option} : **{votes[i]}** vote(s)"
             for i, option in enumerate(options)]
    title = "Égalité" if len(leaders) > 1 else "Gagnant"
    conclusion = f"{title} : **{', '.join(leaders)}**" if maximum else "Aucun vote enregistré."
    return f"📊 **Sondage terminé : {question}**\n" + "\n".join(lines) + "\n" + conclusion


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
