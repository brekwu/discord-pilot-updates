"""Verified, staged updates applied by the launcher after the server shuts down.

An update never touches Discord bot credentials or user project history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import urllib.parse
import urllib.request
from uuid import uuid4
from zipfile import BadZipFile, ZipFile


RESTART_UPDATE_CODE = 26
MAX_ZIP_SIZE = 32 * 1024 * 1024
MAX_EXE_SIZE = 200 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 64 * 1024 * 1024
MAX_MANIFEST_SIZE = 32 * 1024
TRUSTED_HOSTS = {
    "github.com", "raw.githubusercontent.com", "api.github.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com",
}
UPDATABLE = {
    "app.py", "planner.py", "storage.py", "discord_ops.py", "integration_catalog.py", "community_modules.py", "community_interactions.py", "community_support.py", "updater.py", "updater_cli.py",
    "requirements.txt", "version.json", "README.md", "web/index.html", "web/app.js", "web/style.css", "web/updates.css",
    "LANCER_DISCORD_PILOT.bat", "DEMARRER_DISCORD_PILOT.cmd", "demarrer.ps1", "CONSTRUIRE_EXE_WINDOWS.bat",
}
REQUIRED = {
    "app.py", "community_modules.py", "community_interactions.py", "community_support.py", "integration_catalog.py", "updater.py", "updater_cli.py", "version.json", "web/index.html", "web/app.js",
    "web/style.css", "web/updates.css", "demarrer.ps1", "DEMARRER_DISCORD_PILOT.cmd",
}
VERSION_FORMAT = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")


def semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not VERSION_FORMAT.fullmatch(value):
        raise ValueError("Numéro de version invalide (format attendu : 1.2.3).")
    return tuple(int(part) for part in value.split("."))


def read_version(root: Path) -> str:
    return json.loads((root / "version.json").read_text(encoding="utf-8"))["version"]


def require_trusted_url(url: str):
    if not isinstance(url, str) or len(url) > 1200:
        raise ValueError("URL de mise à jour invalide.")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname not in TRUSTED_HOSTS:
        raise ValueError("Utilise une URL HTTPS GitHub ou raw.githubusercontent.com.")
    if parsed.port not in {None, 443} or parsed.fragment:
        raise ValueError("URL de mise à jour invalide.")
    return url


def read_remote(url: str, *, max_bytes: int, timeout: int = 15) -> bytes:
    require_trusted_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "DiscordPilot-Updater/1.0", "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        # Revalidate redirects as an extra guard against untrusted downloads.
        require_trusted_url(response.geturl())
        size = response.headers.get("Content-Length")
        if size and int(size) > max_bytes:
            raise ValueError("Le téléchargement est trop volumineux.")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Le téléchargement dépasse la taille maximale.")
    return data


def inspect_manifest(raw: bytes, installed_version: str) -> dict:
    if len(raw) > MAX_MANIFEST_SIZE:
        raise ValueError("Manifeste trop volumineux.")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Manifeste de mise à jour illisible.") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Format du manifeste incorrect.")
    version = manifest.get("version")
    semver(version)
    url = require_trusted_url(manifest.get("url"))
    digest = manifest.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("Empreinte SHA-256 manquante ou invalide.")
    exe_url = manifest.get("exe_url")
    exe_digest = manifest.get("exe_sha256")
    if exe_url is not None or exe_digest is not None:
        if not isinstance(exe_url, str) or not isinstance(exe_digest, str):
            raise ValueError("Fichier Windows ou empreinte EXE manquant dans le manifeste.")
        require_trusted_url(exe_url)
        if not re.fullmatch(r"[a-fA-F0-9]{64}", exe_digest):
            raise ValueError("Empreinte SHA-256 du programme Windows invalide.")
    return {
        "version": version,
        "url": url,
        "sha256": digest.lower(),
        "exe_url": exe_url,
        "exe_sha256": exe_digest.lower() if exe_digest else None,
        "available": semver(version) > semver(installed_version),
    }


def inspect_zip(raw: bytes, version: str) -> dict[str, bytes]:
    if len(raw) > MAX_ZIP_SIZE:
        raise ValueError("Archive de mise à jour trop volumineuse.")
    output = {}
    total = 0
    try:
        with ZipFile(BytesIO(raw)) as zf:
            all_names = [item.filename.replace("\\", "/") for item in zf.infolist() if not item.is_dir()]
            prefix = "discord-pilot/" if "discord-pilot/version.json" in all_names else ""
            if prefix + "version.json" not in all_names:
                raise ValueError("Fichier version.json absent du ZIP.")
            for info in zf.infolist():
                if info.is_dir():
                    continue
                raw_name = info.filename.replace("\\", "/")
                if not raw_name.startswith(prefix):
                    raise ValueError("Archive contenant un fichier hors du dossier de l'application.")
                name = raw_name[len(prefix):]
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"Chemin non autorisé : {name[:80]}.")
                if name.startswith("tests/") and name.endswith(".py") and len(path.parts) == 2:
                    continue  # Tests delivered in the ZIP, never installed into the app.
                if name not in UPDATABLE:
                    raise ValueError(f"Fichier non autorisé dans la mise à jour : {name[:80]}.")
                if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                    raise ValueError("Les liens symboliques sont interdits dans les mises à jour.")
                total += info.file_size
                if total > MAX_UNCOMPRESSED_SIZE:
                    raise ValueError("Archive décompressée trop volumineuse.")
                if name in output:
                    raise ValueError("Archive contenant un doublon.")
                output[name] = zf.read(info)
    except BadZipFile as exc:
        raise ValueError("Archive ZIP illisible.") from exc
    if not REQUIRED.issubset(output):
        raise ValueError("L'archive ne contient pas tous les fichiers requis.")
    try:
        archive_version = json.loads(output["version.json"])["version"]
    except (ValueError, KeyError, UnicodeError) as exc:
        raise ValueError("Version de l'archive invalide.") from exc
    if semver(archive_version) != semver(version):
        raise ValueError("La version du ZIP ne correspond pas au manifeste.")
    return output


def stage_update(raw: bytes, version: str, data_root: Path, installed_version: str, expected_sha256: str | None = None) -> dict:
    if semver(version) <= semver(installed_version):
        raise ValueError("La version choisie n'est pas plus récente que celle installée.")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != expected_sha256.lower():
        raise ValueError("La vérification de sécurité SHA-256 a échoué : téléchargement refusé.")
    inspect_zip(raw, version)
    updates = data_root / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    tmp = updates / f"staging-{uuid4().hex}.zip"
    tmp.write_bytes(raw)
    os.replace(tmp, updates / "pending.zip")
    pending = {"version": version, "sha256": digest, "created_at": datetime.now(timezone.utc).isoformat()}
    tmp_json = updates / f"pending-{uuid4().hex}.json"
    tmp_json.write_text(json.dumps(pending), encoding="utf-8")
    os.replace(tmp_json, updates / "pending.json")
    return pending


def stage_executable(raw: bytes, version: str, data_root: Path, installed_version: str,
                     expected_sha256: str) -> dict:
    """Stage a signed-by-digest Windows PE download without executing it yet."""
    if semver(version) <= semver(installed_version):
        raise ValueError("La version choisie n'est pas plus récente que celle installée.")
    if len(raw) > MAX_EXE_SIZE or len(raw) < 1024 or not raw.startswith(b"MZ"):
        raise ValueError("Le programme téléchargé n'est pas un EXE Windows valide.")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("La vérification de sécurité SHA-256 de l'exécutable a échoué.")
    updates = data_root / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    temp = updates / f"staging-{uuid4().hex}.exe"
    temp.write_bytes(raw)
    os.replace(temp, updates / "pending.exe")
    pending = {"version": version, "sha256": digest, "format": "exe",
               "created_at": datetime.now(timezone.utc).isoformat()}
    temp_json = updates / f"pending-{uuid4().hex}.json"
    temp_json.write_text(json.dumps(pending), encoding="utf-8")
    os.replace(temp_json, updates / "pending.json")
    return pending


def pending_update(data_root: Path) -> dict | None:
    path = data_root / "updates" / "pending.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def apply_pending(project_root: Path, data_root: Path) -> dict:
    """Called while app.py is STOPPED. Preserve a full backup of changed source files."""
    updates = data_root / "updates"
    manifest = pending_update(data_root)
    if not manifest:
        raise ValueError("Aucune mise à jour en attente.")
    raw = (updates / "pending.zip").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise ValueError("Mise à jour modifiée après validation : installation annulée.")
    files = inspect_zip(raw, manifest["version"])
    if semver(manifest["version"]) <= semver(read_version(project_root)):
        raise ValueError("Version installée déjà égale ou plus récente.")

    backup = updates / "backups" / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:7])
    backup.mkdir(parents=True, exist_ok=False)
    replaced = []
    try:
        # Updating version.json last prevents a half-applied update from appearing complete.
        ordered = sorted(set(files) - {"version.json"}) + ["version.json"]
        for name in ordered:
            original = project_root / name
            if original.is_file() and original.read_bytes() == files[name]:
                continue
            if original.exists():
                dest = backup / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, dest)
            original.parent.mkdir(parents=True, exist_ok=True)
            temp_target = original.with_suffix(original.suffix + ".pilot-new")
            try:
                temp_target.write_bytes(files[name])
                os.replace(temp_target, original)
            finally:
                if temp_target.exists():
                    temp_target.unlink()
            replaced.append(name)
    except Exception:
        for name in reversed(replaced):
            original, backed = project_root / name, backup / name
            if backed.exists():
                shutil.copy2(backed, original)
            elif original.exists():
                original.unlink()
        raise
    (updates / "pending.json").unlink()
    (updates / "pending.zip").unlink()
    return {"version": manifest["version"], "files": len(replaced), "backup": str(backup)}
