"""Explicit opt-in game labels and strict, restart-safe Discord ticket routing."""
from __future__ import annotations

GAME_LABELS = {
    "rocket-league": "Rocket League",
    "valorant": "Valorant",
    "fortnite": "Fortnite",
    "clash-of-clans": "Clash of Clans",
}
GAME_CHANNELS = {
    "rocket-league": "rl",
    "valorant": "valorant",
    "fortnite": "fortnite",
    "clash-of-clans": "coc",
}

def normalize_recruitment_games(value: str) -> str:
    if not isinstance(value, str) or len(value) > 120:
        raise ValueError("Liste de jeux invalide.")
    if not value.strip():
        return ""
    parts = [s.strip().lower() for s in value.split(",")]
    if not parts or any(p not in GAME_LABELS for p in parts) or len(set(parts)) != len(parts):
        raise ValueError(
            "Jeux autorisés : rocket-league, valorant, fortnite, clash-of-clans ; sans doublons."
        )
    return ", ".join(parts)

def enabled_games(cfg: dict) -> list[str]:
    value = cfg.get("recruitment_games", "")
    return [s.strip() for s in value.split(",") if s.strip()] if isinstance(value, str) else []

def ticket_key(owner_id: int, game: str = "") -> str:
    """Prevent duplicate OPEN tickets for the same owner and game."""
    if game and game not in GAME_LABELS:
        raise ValueError("Jeu de recrutement inconnu.")
    return f"{owner_id}:{game}"

def ticket_name(owner_id: int, game: str = "") -> str:
    if game and game not in GAME_CHANNELS:
        raise ValueError("Jeu de recrutement inconnu.")
    return f"recrut-{GAME_CHANNELS[game]}-{str(owner_id)[-6:]}" if game else f"ticket-{str(owner_id)[-6:]}"
