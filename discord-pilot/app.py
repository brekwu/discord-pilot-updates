"""Discord Pilot: localhost-only Discord server configuration studio."""

from __future__ import annotations

import asyncio
import errno
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import webbrowser
from zipfile import BadZipFile

import aiohttp
from aiohttp import web
import discord

from discord_ops import execute_action
from planner import (DANGEROUS_ACTIONS, PRESETS, SYSTEM_PROMPT, description,
                     collapse_old_clarifications, default_creation_plan, local_parse,
                     norm, parse_ollama_decision,
                     validate_actions)
from storage import State, load_token, remove_token, save_token
from updater import (MAX_EXE_SIZE, MAX_ZIP_SIZE, RESTART_UPDATE_CODE, inspect_manifest,
                     inspect_zip, pending_update, read_remote, read_version,
                     require_trusted_url, stage_executable, stage_update)


BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PORT = int(os.getenv("DISCORD_PILOT_PORT", "8765"))
STATE = State()
CSRF = secrets.token_urlsafe(32)
ID_RE = re.compile(r"^\d{17,20}$")
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/brekwu/discord-pilot-updates/main/update.json"


def update_url() -> str:
    return STATE.state.get("update_url") or DEFAULT_UPDATE_URL


class PilotBot(discord.Client):
    def __init__(self, manager):
        super().__init__(intents=discord.Intents(guilds=True))
        self.manager = manager

    async def on_ready(self):
        self.manager.error = None
        self.manager.ready = True
        if self.manager.remember and self.manager.current_token:
            try:
                save_token(self.manager.current_token, STATE.root)
            except OSError:
                self.manager.error = "Connexion réussie, mais impossible de mémoriser le token."


class BotManager:
    def __init__(self):
        self.bot: PilotBot | None = None
        self.task: asyncio.Task | None = None
        self.current_token: str | None = None
        self.remember = False
        self.ready = False
        self.error: str | None = None

    async def connect(self, token: str, remember: bool):
        if self.task and not self.task.done():
            await self.disconnect(remove_saved=False)
        self.ready = False
        self.error = None
        self.remember = remember
        self.current_token = token
        self.bot = PilotBot(self)
        self.task = asyncio.create_task(self._start(self.bot, token))

    async def _start(self, bot, token: str):
        try:
            await bot.start(token, reconnect=True)
        except discord.LoginFailure:
            self.error = ("Discord a refusé le token. Dans Discord Developer Portal > "
                          "ton application > Bot > Reset Token, copie le nouveau token "
                          "(pas l'Application ID ni le Client Secret).")
        except discord.PrivilegedIntentsRequired:
            self.error = "Le bot exige des intents non disponibles dans sa configuration."
        except (discord.DiscordException, OSError, aiohttp.ClientError) as exc:
            self.error = f"Connexion Discord impossible : {type(exc).__name__}."
        except Exception as exc:
            self.error = f"Erreur du bot : {type(exc).__name__}."
        finally:
            self.ready = False
            self.current_token = None

    async def disconnect(self, remove_saved=True):
        if self.bot and not self.bot.is_closed():
            await self.bot.close()
        if self.task and not self.task.done():
            try:
                await asyncio.wait_for(self.task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task.cancel()
        self.task = None
        self.bot = None
        self.current_token = None
        self.ready = False
        self.error = None
        if remove_saved:
            remove_token(STATE.root)

    def get_guild(self, guild_id: str):
        if not self.ready or not self.bot:
            return None
        return self.bot.get_guild(int(guild_id))


MANAGER = BotManager()
LOCKS: dict[str, asyncio.Lock] = {}
STOP_EVENT: asyncio.Event | None = None
EXIT_FOR_UPDATE = False


def require_id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise web.HTTPBadRequest(text="Identifiant de serveur Discord invalide.")
    return value


async def body_json(request):
    try:
        if request.content_type != "application/json":
            raise ValueError("Content-Type requis : application/json")
        result = await request.json()
        if not isinstance(result, dict):
            raise ValueError("Objet JSON requis")
        return result
    except (ValueError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


@web.middleware
async def local_only(request, handler):
    # A browser on a hostile web page must not configure Discord via localhost.
    if request.host not in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}:
        raise web.HTTPForbidden(text="Adresse locale invalide.")
    if request.method not in {"GET", "HEAD"}:
        origin = request.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
        if origin and origin not in allowed:
            raise web.HTTPForbidden(text="Origine externe refusée.")
        if request.headers.get("X-Pilot-CSRF") != CSRF:
            raise web.HTTPForbidden(text="Protection de session manquante.")
    return await handler(request)


@web.middleware
async def error_to_json(request, handler):
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if request.path.startswith("/api/"):
            return web.json_response({"error": exc.text}, status=exc.status)
        raise
    except (ValueError, KeyError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def home(request):
    return web.FileResponse(BASE / "web" / "index.html", headers={"Cache-Control": "no-store"})


async def asset(request):
    name = request.match_info["name"]
    if name not in {"app.js", "style.css", "updates.css"}:
        raise web.HTTPNotFound()
    return web.FileResponse(BASE / "web" / name, headers={"Cache-Control": "no-store"})


async def api_health(request):
    """Tiny loopback-only probe so a tab can find a restarted server on port +1..+5.

    Never expose the Discord session, CSRF token, pinned guilds or user data
    cross-origin. A public web site receives no CORS permission.
    """
    response = web.json_response({"discord_pilot": True, "version": read_version(BASE)},
                                 headers={"Cache-Control": "no-store"})
    origin = request.headers.get("Origin", "")
    match = re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):([0-9]{1,5})", origin)
    if match and 1 <= int(match.group(1)) <= 65535:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


def guild_summary(guild: discord.Guild):
    return {
        "id": str(guild.id), "name": guild.name,
        "alias": STATE.state["aliases"].get(str(guild.id), ""),
        "icon": str(guild.icon.url) if guild.icon else None,
        "member_count": guild.member_count,
        "channels": sum(1 for c in guild.channels if not isinstance(c, discord.CategoryChannel)),
        "roles": max(0, len(guild.roles) - 1),
    }


async def api_bootstrap(request):
    bot = MANAGER.bot
    guilds = sorted((guild_summary(g) for g in bot.guilds), key=lambda g: g["name"].lower()) if MANAGER.ready and bot else []
    return web.json_response({
        "csrf": CSRF,
        "online": MANAGER.ready, "connecting": bool(MANAGER.task and not MANAGER.task.done() and not MANAGER.ready),
        "error": MANAGER.error,
        "bot": {"name": str(bot.user), "id": str(bot.user.id)} if MANAGER.ready and bot and bot.user else None,
        "guilds": guilds,
        "pinned": STATE.state["aliases"],
        "presets": [{"id": k, "label": v["label"], "description": v["description"]} for k, v in PRESETS.items()],
        "token_saved": (STATE.root / "bot-token.dpapi").exists(),
        "version": read_version(BASE),
        "update_url": update_url(),
        "update_pending": pending_update(STATE.root),
    })


async def api_connect(request):
    data = await body_json(request)
    token = data.get("token", "")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("Colle le token du bot depuis Discord Developer Portal > Bot.")
    if len(token.strip()) > 512:
        raise ValueError("Valeur trop longue : colle uniquement le token du bot.")
    remember = bool(data.get("remember", True))
    await MANAGER.connect(token.strip(), remember)
    return web.json_response({"ok": True, "message": "Connexion en cours…"})


async def api_disconnect(request):
    await MANAGER.disconnect()
    return web.json_response({"ok": True})


async def api_invite(request):
    if not MANAGER.ready or not MANAGER.bot or not MANAGER.bot.user:
        raise ValueError("Connecte d'abord le bot.")
    # No administrator permission requested.
    permissions = discord.Permissions(manage_channels=True, manage_roles=True,
                                      send_messages=True, view_channel=True,
                                      read_message_history=True)
    return web.json_response({
        "url": discord.utils.oauth_url(MANAGER.bot.user.id, permissions=permissions, scopes=("bot",))
    })


async def api_guild(request):
    guild_id = require_id(request.match_info["guild_id"])
    guild = MANAGER.get_guild(guild_id)
    if not guild:
        raise web.HTTPNotFound(text="Serveur inaccessible. Ajoute le bot à ce serveur et reconnecte-le.")
    return web.json_response({
        "guild": guild_summary(guild),
        "categories": [{"id": str(c.id), "name": c.name} for c in guild.categories],
        "channels": [{"id": str(c.id), "name": c.name,
                      "type": "voice" if isinstance(c, discord.VoiceChannel) else
                              "text" if isinstance(c, discord.TextChannel) else "other",
                      "category_id": str(c.category_id) if c.category_id else None} for c in guild.channels],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default()],
        "history_count": len(STATE.history(guild_id)),
    })


async def api_alias(request):
    data = await body_json(request)
    guild_id = require_id(data.get("guild_id"))
    name = data.get("alias", "")
    if not isinstance(name, str):
        raise ValueError("Nom invalide")
    STATE.set_alias(guild_id, name)
    return web.json_response({"ok": True})


async def api_history(request):
    guild_id = require_id(request.match_info["guild_id"])
    return web.json_response({"plans": STATE.history(guild_id)})


async def api_export(request):
    guild_id = require_id(request.match_info["guild_id"])
    payload = json.dumps({"guild_id": guild_id, "plans": STATE.history(guild_id)},
                         ensure_ascii=False, indent=2)
    return web.Response(text=payload, content_type="application/json", charset="utf-8",
                        headers={"Content-Disposition": f'attachment; filename="discord-pilot-{guild_id}.json"'})


async def ollama_models():
    timeout = aiohttp.ClientTimeout(total=2)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:11434/api/tags") as response:
                response.raise_for_status()
                data = await response.json()
                return [v["name"] for v in data.get("models", []) if isinstance(v, dict) and v.get("name")]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
        return []


async def api_models(request):
    models = await ollama_models()
    return web.json_response({"available": bool(models), "models": models})


async def api_update_status(request):
    return web.json_response({
        "version": read_version(BASE),
        "url": update_url(),
        "pending": pending_update(STATE.root),
        "installed_via_launcher": bool(getattr(sys, "frozen", False)) or os.getenv("DISCORD_PILOT_LAUNCHER") == "1",
        "standalone_exe": bool(getattr(sys, "frozen", False)),
    })


async def api_update_source(request):
    data = await body_json(request)
    url = data.get("url", "")
    if not isinstance(url, str):
        raise ValueError("Adresse de mise à jour incorrecte.")
    if url.strip():
        require_trusted_url(url.strip())
    if url.strip():
        STATE.state["update_url"] = url.strip()
    else:
        STATE.state.pop("update_url", None)
    STATE.save()
    return web.json_response({"ok": True, "configured": True, "url": update_url()})


async def fetch_update_manifest():
    url = update_url()
    if not url:
        raise ValueError("Aucune source de mises à jour n'est configurée. Ajoute l'URL HTTPS d'un manifeste GitHub.")
    try:
        raw = await asyncio.to_thread(read_remote, url, max_bytes=32768)
        return inspect_manifest(raw, read_version(BASE))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Impossible de contacter la source des mises à jour ({type(exc).__name__}).") from exc


async def api_update_check(request):
    return web.json_response({"update": await fetch_update_manifest()})


async def api_update_download(request):
    manifest = await fetch_update_manifest()
    if not manifest["available"]:
        raise ValueError("Aucune version plus récente n'est disponible.")
    frozen = bool(getattr(sys, "frozen", False))
    if frozen and not manifest.get("exe_url"):
        raise ValueError("La nouvelle version ne contient pas encore de programme Windows autonome.")
    remote_url = manifest["exe_url"] if frozen else manifest["url"]
    try:
        archive = await asyncio.to_thread(read_remote, remote_url,
                                          max_bytes=MAX_EXE_SIZE if frozen else MAX_ZIP_SIZE, timeout=90)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Téléchargement de la mise à jour impossible ({type(exc).__name__}).") from exc
    if frozen:
        pending = stage_executable(archive, manifest["version"], STATE.root,
                                   read_version(BASE), manifest["exe_sha256"])
    else:
        pending = stage_update(archive, manifest["version"], STATE.root, read_version(BASE), manifest["sha256"])
    return web.json_response({"pending": pending})


async def api_update_import(request):
    if getattr(sys, "frozen", False):
        raise ValueError("L'exécutable autonome utilise le bouton Télécharger pour récupérer les mises à jour Windows vérifiées.")
    if not request.content_type.startswith("multipart/"):
        raise ValueError("Sélectionne un fichier ZIP de mise à jour.")
    reader = await request.multipart()
    part = await reader.next()
    if not part or part.name != "file":
        raise ValueError("Fichier ZIP absent.")
    chunks = bytearray()
    while True:
        piece = await part.read_chunk(size=65536)
        if not piece:
            break
        chunks.extend(piece)
        if len(chunks) > MAX_ZIP_SIZE:
            raise ValueError("Fichier ZIP trop volumineux.")
    # Validation occurs before anything can be applied.
    raw = bytes(chunks)
    try:
        from zipfile import ZipFile
        from io import BytesIO
        with ZipFile(BytesIO(raw)) as zf:
            path = "discord-pilot/version.json" if "discord-pilot/version.json" in zf.namelist() else "version.json"
            version = json.loads(zf.read(path))["version"]
    except (ValueError, KeyError, OSError, BadZipFile) as exc:
        raise ValueError("Le ZIP ne contient pas de version valide.") from exc
    pending = stage_update(raw, version, STATE.root, read_version(BASE))
    return web.json_response({"pending": pending})


async def api_update_apply(request):
    global EXIT_FOR_UPDATE
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen and os.getenv("DISCORD_PILOT_LAUNCHER") != "1":
        raise ValueError("Pour installer sans retélécharger, relance Discord Pilot via DEMARRER_DISCORD_PILOT.cmd.")
    pending = pending_update(STATE.root)
    if not pending:
        raise ValueError("Aucune mise à jour vérifiée en attente d'installation.")
    if frozen and pending.get("format") != "exe":
        raise ValueError("Cette archive est destinée à l'ancien lanceur. Télécharge la version Windows via MAJ.")
    if not frozen and pending.get("format") == "exe":
        raise ValueError("Cette mise à jour est destinée à l'exécutable Windows autonome.")
    if any(p["status"] in {"queued", "running"} for p in STATE.state["plans"]):
        raise ValueError("Une modification Discord est en cours : attends sa fin avant de mettre à jour.")
    if STOP_EVENT is None:
        raise ValueError("Le redémarrage automatique n'est pas disponible.")
    if EXIT_FOR_UPDATE:
        raise ValueError("Une mise à jour est déjà en cours d'installation.")
    # Start the external updater *before* taking the HTTP server down. If
    # PowerShell cannot be spawned, keep this instance alive and report it.
    if frozen:
        try:
            launch_frozen_updater()
        except (OSError, RuntimeError) as exc:
            raise ValueError("Impossible de préparer le redémarrage automatique : "
                             f"{type(exc).__name__}. Le programme reste ouvert.") from exc
    EXIT_FOR_UPDATE = True
    asyncio.get_running_loop().call_later(1.25, STOP_EVENT.set)
    return web.json_response({"ok": True, "restarting": True, "target_version": pending["version"]})


async def ollama_plan(prompt: str, model: str) -> tuple[list[dict], str | None]:
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("http://127.0.0.1:11434/api/chat", json={
            "model": model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}],
        }) as response:
            if response.status >= 400:
                raise ValueError(f"Ollama ne peut pas utiliser le modèle « {model} » (HTTP {response.status}).")
            data = await response.json()
    return parse_ollama_decision(data["message"]["content"])


async def api_plan(request):
    data = await body_json(request)
    guild_id = require_id(data.get("guild_id"))
    raw_prompt = data.get("prompt", "")
    if not isinstance(raw_prompt, str) or not 3 <= len(raw_prompt.strip()) <= 4000:
        raise ValueError("Décris ta demande (3 à 4 000 caractères).")
    prompt = collapse_old_clarifications(raw_prompt)
    mode = data.get("mode", "auto")
    if mode not in {"auto", "local", "ollama"}:
        raise ValueError("Mode d'interprétation inconnu.")
    # An explicit, understood command must go straight to a draft. Never let
    # an optional model turn it into a repeated clarification dialog.
    actions = local_parse(prompt) or default_creation_plan(prompt)
    used = "local"
    if not actions and mode != "local":
        models = await ollama_models()
        if mode == "ollama" and not models:
            raise ValueError("Ollama n'est pas démarré ou aucun modèle n'est installé.")
        if models:
            chosen = data.get("model") or models[0]
            if chosen not in models:
                raise ValueError("Le modèle demandé n'est pas installé dans Ollama.")
            try:
                actions, _question = await ollama_plan(prompt, chosen)
                used = f"ollama:{chosen}"
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(f"Erreur de génération Ollama : {type(exc).__name__}. Réessaie.") from exc
    if not actions:
        raise ValueError("Je ne peux pas proposer d'action sûre pour cette demande. Décris les changements souhaités en une phrase (par exemple « Crée deux salons bienvenue et au-revoir »).")
    if any(a["type"] in DANGEROUS_ACTIONS for a in actions) and not re.search(r"\b(?:supprim\w*|effac\w*|retir\w*|delete|enlev\w*)\b", norm(prompt)):
        raise ValueError("Suppression non demandée explicitement : aucune action lancée.")
    plan = STATE.add(guild_id, prompt.strip(), actions, used)
    return web.json_response({"plan": plan})


async def api_preset(request):
    data = await body_json(request)
    guild_id = require_id(data.get("guild_id"))
    preset_id = data.get("preset_id")
    if preset_id not in PRESETS:
        raise ValueError("Modèle inconnu.")
    template = PRESETS[preset_id]
    plan = STATE.add(guild_id, f"Modèle : {template['label']}",
                     validate_actions(template["actions"]), f"preset:{preset_id}")
    return web.json_response({"plan": plan})


async def run_plan(plan, guild):
    async with LOCKS.setdefault(plan["guild_id"], asyncio.Lock()):
        plan["status"] = "running"
        STATE.save()
        for index, item in enumerate(plan["actions"]):
            try:
                status, detail = await execute_action(guild, item)
                row = {"index": index, "status": status, "detail": detail,
                       "description": description(item)}
            except discord.Forbidden:
                row = {"index": index, "status": "failed", "detail": "Permissions Discord insuffisantes pour cette action.",
                       "description": description(item)}
            except discord.HTTPException as exc:
                row = {"index": index, "status": "failed", "detail": f"Discord a refusé l'action (HTTP {exc.status}).",
                       "description": description(item)}
            except (ValueError, TypeError, AttributeError) as exc:
                row = {"index": index, "status": "failed", "detail": str(exc),
                       "description": description(item)}
            except Exception as exc:
                row = {"index": index, "status": "failed", "detail": f"Erreur inattendue : {type(exc).__name__}.",
                       "description": description(item)}
            plan["results"].append(row)
            STATE.save()
        failures = sum(1 for r in plan["results"] if r["status"] == "failed")
        plan["status"] = "failed" if failures == len(plan["results"]) else "partial" if failures else "completed"
        STATE.save()


async def api_execute(request):
    if EXIT_FOR_UPDATE:
        raise ValueError("Mise à jour en cours : attends le redémarrage avant de lancer des actions Discord.")
    data = await body_json(request)
    plan_id = request.match_info["plan_id"]
    plan = STATE.get(plan_id)
    if not plan:
        raise web.HTTPNotFound(text="Plan introuvable.")
    if plan["status"] != "draft":
        raise ValueError("Ce plan est déjà lancé ou terminé. Pour réessayer, crée un nouveau plan.")
    guild = MANAGER.get_guild(plan["guild_id"])
    if guild is None:
        raise ValueError("Bot déconnecté ou absent du serveur. Aucune action envoyée.")
    if any(a["type"] in DANGEROUS_ACTIONS for a in plan["actions"]):
        if data.get("confirm_delete_name") != guild.name:
            raise ValueError("Suppression : saisis exactement le nom du serveur pour confirmer.")
    plan["status"] = "queued"
    STATE.save()
    asyncio.create_task(run_plan(plan, guild))
    return web.json_response({"ok": True, "status": "queued"})


async def on_shutdown(app):
    await MANAGER.disconnect(remove_saved=False)


def build_app():
    app = web.Application(middlewares=[error_to_json, local_only], client_max_size=MAX_ZIP_SIZE + 1024 * 256)
    app.router.add_get("/", home)
    app.router.add_get("/assets/{name}", asset)
    app.router.add_get("/api/bootstrap", api_bootstrap)
    app.router.add_get("/api/health", api_health)
    app.router.add_post("/api/connect", api_connect)
    app.router.add_post("/api/disconnect", api_disconnect)
    app.router.add_get("/api/invite", api_invite)
    app.router.add_get("/api/guild/{guild_id}", api_guild)
    app.router.add_post("/api/alias", api_alias)
    app.router.add_get("/api/history/{guild_id}", api_history)
    app.router.add_get("/api/export/{guild_id}", api_export)
    app.router.add_get("/api/models", api_models)
    app.router.add_post("/api/plan", api_plan)
    app.router.add_post("/api/preset", api_preset)
    app.router.add_post("/api/execute/{plan_id}", api_execute)
    app.router.add_get("/api/update/status", api_update_status)
    app.router.add_post("/api/update/source", api_update_source)
    app.router.add_post("/api/update/check", api_update_check)
    app.router.add_post("/api/update/download", api_update_download)
    app.router.add_post("/api/update/import", api_update_import)
    app.router.add_post("/api/update/apply", api_update_apply)
    app.on_shutdown.append(on_shutdown)
    return app


async def start_local_site(runner: web.AppRunner, preferred_port: int) -> tuple[web.TCPSite, int]:
    """Bind localhost, trying nearby ports if an older instance owns the default."""
    if os.getenv("DISCORD_PILOT_RESTART_PROBE") == "1":
        # Give the previous instance a moment to release the exact URL used by
        # the open browser tab before trying another port.
        for _ in range(20):
            site = web.TCPSite(runner, host="127.0.0.1", port=preferred_port)
            try:
                await site.start()
                return site, runner.addresses[-1][1]
            except OSError as exc:
                if exc.errno not in {errno.EADDRINUSE, 10048} and getattr(exc, "winerror", None) != 10048:
                    raise
                await asyncio.sleep(0.25)
    candidates = [preferred_port]
    candidates.extend(range(preferred_port + 1, min(preferred_port + 5, 65535) + 1))
    candidates.append(0)  # Last resort: ask Windows to select a free local port.
    for candidate in candidates:
        site = web.TCPSite(runner, host="127.0.0.1", port=candidate)
        try:
            await site.start()
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, 10048} and getattr(exc, "winerror", None) != 10048:
                raise
            continue
        actual_port = runner.addresses[-1][1]
        return site, actual_port
    raise RuntimeError("Aucun port local disponible pour Discord Pilot.")


async def start_app():
    global PORT, STOP_EVENT, EXIT_FOR_UPDATE
    STOP_EVENT = asyncio.Event()
    EXIT_FOR_UPDATE = False
    app = build_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site, actual_port = await start_local_site(runner, PORT)
    except Exception:
        await runner.cleanup()
        raise
    if actual_port != PORT:
        print(f"Port {PORT} déjà occupé : utilisation du port {actual_port}.", flush=True)
    PORT = actual_port  # Keep the localhost/CSRF checks aligned with the real socket.
    print(f"Discord Pilot : http://127.0.0.1:{PORT}", flush=True)
    if os.getenv("DISCORD_PILOT_RESTART_PROBE") == "1":
        try:
            with (STATE.root / "updater.log").open("a", encoding="utf-8") as log:
                log.write(f"Demarrage nouvelle instance : PID={os.getpid()}, port={PORT}\n")
        except OSError:
            pass
    saved = load_token(STATE.root)
    if saved:
        await MANAGER.connect(saved, remember=False)
    if os.getenv("DISCORD_PILOT_NO_BROWSER") != "1":
        asyncio.get_running_loop().call_later(1, webbrowser.open, f"http://127.0.0.1:{PORT}")
    try:
        await STOP_EVENT.wait()
    finally:
        await runner.cleanup()
    if EXIT_FOR_UPDATE:
        if getattr(sys, "frozen", False):
            return
        raise SystemExit(RESTART_UPDATE_CODE)


def launch_frozen_updater():
    """Start a detached local helper; it waits for this EXE to exit before replacement."""
    if sys.platform != "win32":
        raise RuntimeError("La mise à jour de l'exécutable nécessite Windows.")
    pending = pending_update(STATE.root)
    if not pending or pending.get("format") != "exe":
        raise ValueError("Mise à jour Windows manquante.")
    folder = STATE.root / "updates"
    source = BASE / "frozen_updater.ps1"
    helper = folder / "frozen_updater.ps1"
    shutil.copy2(source, helper)
    command = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(helper), "-ExePath", sys.executable,
               "-PendingPath", str(folder / "pending.exe"),
               "-ExpectedHash", pending["sha256"], "-DataRoot", str(STATE.root),
               "-ParentPid", str(os.getpid()), "-Port", str(PORT),
               "-TargetVersion", pending["version"]]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)


def main():
    try:
        asyncio.run(start_app())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
