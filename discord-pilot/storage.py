"""Local project history; Windows DPAPI for bot tokens."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4


def data_folder() -> Path:
    override = os.getenv("DISCORD_PILOT_DATA_DIR")
    if override:
        root = Path(override)
    elif sys.platform == "win32":
        root = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "DiscordPilot"
    else:
        root = Path.home() / ".local" / "share" / "discord-pilot"
    root.mkdir(parents=True, exist_ok=True)
    return root


class State:
    def __init__(self, root: Path | None = None):
        self.root = root or data_folder()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "history.json"
        try:
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.state, dict):
                raise ValueError("bad data")
        except (ValueError, OSError):
            self.state = {"plans": [], "aliases": {}}
        self.state.setdefault("plans", [])
        self.state.setdefault("aliases", {})
        self.state.setdefault("automations", {})
        self.state.setdefault("invite_counts", {})
        self.state.setdefault("modules", {})
        self.state.setdefault("xp_stats", {})
        self.state.setdefault("daily_sent", {})
        self.state.setdefault("voice_rooms", {})
        self.state.setdefault("tickets", {})
        self.state.setdefault("ticket_panels", {})
        self.state.setdefault("interactive_events", {})

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as fp:
            json.dump(self.state, fp, indent=2, ensure_ascii=False)
        os.replace(temporary, self.path)

    def add(self, guild_id: str, prompt: str, actions: list[dict], mode: str) -> dict:
        row = {
            "id": uuid4().hex, "guild_id": guild_id, "prompt": prompt,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode, "status": "draft", "actions": actions, "results": [],
        }
        self.state["plans"].insert(0, row)
        self.save()
        return row

    def get(self, plan_id: str) -> dict | None:
        return next((p for p in self.state["plans"] if p["id"] == plan_id), None)

    def history(self, guild_id: str) -> list[dict]:
        return [p for p in self.state["plans"] if p["guild_id"] == guild_id]

    def set_alias(self, guild_id: str, name: str):
        if not name.strip():
            self.state["aliases"].pop(guild_id, None)
        else:
            self.state["aliases"][guild_id] = name.strip()[:70]
        self.save()

    def automation_channel(self, guild_id: str, kind: str) -> str | None:
        return self.state["automations"].get(str(guild_id), {}).get(kind)

    def set_automation(self, guild_id: str, kind: str, channel_id: str) -> bool:
        if kind not in {"welcome", "farewell", "invites"}:
            raise ValueError("Type d'automatisation inconnu.")
        guild = self.state["automations"].setdefault(str(guild_id), {})
        if guild.get(kind) == str(channel_id):
            return False
        guild[kind] = str(channel_id)
        self.save()
        return True

    def increment_invites(self, guild_id: str, inviter_id: str) -> int:
        counts = self.state["invite_counts"].setdefault(str(guild_id), {})
        count = max(0, int(counts.get(str(inviter_id), 0))) + 1
        counts[str(inviter_id)] = count
        self.save()
        return count

    def seed_invite_counts(self, guild_id: str, snapshot: dict) -> None:
        """Start from Discord's visible invite uses, never reduce saved totals.

        Deleted/expired links and vanity URLs cannot be reconstructed, so
        this is a documented lower bound, not a fabricated historical total.
        """
        observed = {}
        for uses, inviter_id in snapshot.values():
            if inviter_id is not None:
                key = str(inviter_id)
                observed[key] = observed.get(key, 0) + max(0, int(uses))
        counts = self.state["invite_counts"].setdefault(str(guild_id), {})
        changed = False
        for inviter_id, uses in observed.items():
            if uses > int(counts.get(inviter_id, 0)):
                counts[inviter_id] = uses
                changed = True
        if changed:
            self.save()

    def module(self, guild_id: str, name: str) -> dict:
        return self.state["modules"].get(str(guild_id), {}).get(name, {})

    def set_module(self, guild_id: str, name: str, config: dict):
        self.state["modules"].setdefault(str(guild_id), {})[name] = dict(config)
        self.save()

    def record_xp(self, guild_id: str, member_id: str, now: float) -> tuple[int, int, bool]:
        from community_modules import level_for_xp
        users = self.state["xp_stats"].setdefault(str(guild_id), {})
        record = users.setdefault(str(member_id), {"xp": 0, "last_at": 0})
        if now - float(record.get("last_at", 0)) < 60:
            return int(record["xp"]), level_for_xp(int(record["xp"])), False
        previous = level_for_xp(int(record["xp"]))
        record["xp"] = int(record["xp"]) + 10
        record["last_at"] = now
        self.save()
        current = level_for_xp(int(record["xp"]))
        return int(record["xp"]), current, current > previous

    def leaderboard(self, guild_id: str, limit: int = 20) -> list[dict]:
        from community_modules import level_for_xp
        records = self.state["xp_stats"].get(str(guild_id), {})
        top = sorted(records.items(), key=lambda row: -int(row[1].get("xp", 0)))[:limit]
        return [{"member_id": member_id, "xp": int(record.get("xp", 0)),
                 "level": level_for_xp(int(record.get("xp", 0)))} for member_id, record in top]

    def add_interactive_event(self, guild_id: str, row: dict) -> dict:
        records = self.state["interactive_events"].setdefault(str(guild_id), {})
        if len(records) >= 1000:
            raise ValueError("Limite de 1 000 événements par serveur : exporte et nettoie l'historique avant de continuer.")
        event_id = uuid4().hex
        records[event_id] = {"id": event_id, "guild_id": str(guild_id),
                             "status": "open", "announced": False, **row}
        self.save()
        return records[event_id]


if sys.platform == "win32":
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def _protect(data: bytes, encrypt: bool) -> bytes:
        """DPAPI encrypts for the current Windows user; never stores the raw token."""
        dll = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        raw = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        blob = _BLOB(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
        output = _BLOB()
        method = dll.CryptProtectData if encrypt else dll.CryptUnprotectData
        method.restype = wintypes.BOOL
        method.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
        if not method(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(output)):
            raise OSError(ctypes.get_last_error(), "Échec du chiffrement Windows DPAPI")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def save_token(token: str, root: Path):
    if sys.platform != "win32":
        return False
    (root / "bot-token.dpapi").write_bytes(_protect(token.encode("utf-8"), True))
    return True


def load_token(root: Path) -> str | None:
    environment = os.getenv("DISCORD_BOT_TOKEN")
    if environment:
        return environment.strip()
    path = root / "bot-token.dpapi"
    if sys.platform != "win32" or not path.is_file():
        return None
    try:
        return _protect(path.read_bytes(), False).decode("utf-8")
    except (OSError, ValueError, UnicodeError):
        return None


def remove_token(root: Path):
    path = root / "bot-token.dpapi"
    if path.exists():
        path.unlink()
