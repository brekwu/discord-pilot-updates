"""Prepare a public, checksum-verified electron-updater feed from a Windows CI ZIP.

Only release binaries are published. The private repository and its sources
remain private. The input URL is ephemeral and never written into the feed.
"""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import zipfile


def fail(message: str) -> None:
    raise SystemExit(message)


def prepare(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail("Invalid version.")

    archive_url = os.environ.get("ADMIN_UPDATE_ARCHIVE_URL", "")
    expected_hash = os.environ.get("ADMIN_UPDATE_ARCHIVE_SHA256", "").lower()
    parsed = urllib.parse.urlparse(archive_url)
    # This URL comes from the authenticated GitHub artifact connector. Never
    # accept an arbitrary download origin or a local/private network address.
    if (parsed.scheme != "https" or not parsed.hostname or
            not parsed.hostname.endswith(".oaiusercontent.com")):
        fail("Only short-lived artifact URLs from oaiusercontent.com are accepted.")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        fail("Invalid artifact SHA256.")

    req = urllib.request.Request(archive_url, headers={"User-Agent": "AdminControl-Publisher/1"})
    digest = hashlib.sha256()
    chunks = []
    total = 0
    with urllib.request.urlopen(req, timeout=90) as response:
        while True:
            data = response.read(1024 * 1024)
            if not data:
                break
            total += len(data)
            if total > 180 * 1024 * 1024:
                fail("Artifact ZIP exceeds the 180 MB safety limit.")
            digest.update(data)
            chunks.append(data)
    if digest.hexdigest() != expected_hash:
        fail("Artifact SHA256 does not match the Windows CI result.")

    name = f"AdminControl-Setup-{version}.exe"
    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        entries = {entry.filename: entry for entry in archive.infolist() if not entry.is_dir()}
        if set(entries) != {name, "latest.yml"}:
            fail("Unexpected artifact files; expected the Windows installer and latest.yml only.")
        installer = archive.read(name)
        manifest = archive.read("latest.yml").decode("utf-8")

    if not installer.startswith(b"MZ"):
        fail("Installer is not a valid Windows PE executable.")
    if not re.search(rf"^version:\s*{re.escape(version)}\s*$", manifest, re.MULTILINE):
        fail("The update manifest version does not match the intended release.")
    sha512 = base64.b64encode(hashlib.sha512(installer).digest()).decode("ascii")
    if not re.search(rf"^sha512:\s*{re.escape(sha512)}\s*$", manifest, re.MULTILINE):
        fail("Installer SHA512 does not match latest.yml.")
    if not re.search(rf"^\s+size:\s*{len(installer)}\s*$", manifest, re.MULTILINE):
        fail("Installer size does not match latest.yml.")

    public_url = ("https://github.com/brekwu/discord-pilot-updates/releases/download/"
                  f"admin-control-v{version}/{name}")
    file_entry = re.compile(rf"^(\s*-\s*url:\s*){re.escape(name)}\s*$", re.MULTILINE)
    path_entry = re.compile(rf"^(path:\s*){re.escape(name)}\s*$", re.MULTILINE)
    manifest, file_count = file_entry.subn(lambda m: m.group(1) + public_url, manifest)
    manifest, path_count = path_entry.subn(lambda m: m.group(1) + public_url, manifest)
    if file_count != 1 or path_count != 1:
        fail("The Windows update manifest has an unexpected structure.")

    output = Path("release")
    output.mkdir(exist_ok=True)
    (output / name).write_bytes(installer)
    (output / "latest.yml").write_text(manifest, encoding="utf-8")
    print(f"Validated {name}, {len(installer)} bytes, SHA512 verified.")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--load-request":
        if os.environ.get("GITHUB_EVENT_NAME") == "push":
            request = json.loads(Path("admin-control/publish-request.json").read_text("utf-8"))
        else:
            request = {
                "version": os.environ.get("INPUT_VERSION", ""),
                "archive_url": os.environ.get("INPUT_ARCHIVE_URL", ""),
                "archive_sha256": os.environ.get("INPUT_ARCHIVE_SHA256", ""),
            }
        values = {
            "ADMIN_CONTROL_VERSION": request["version"],
            "ADMIN_UPDATE_ARCHIVE_URL": request["archive_url"],
            "ADMIN_UPDATE_ARCHIVE_SHA256": request["archive_sha256"],
        }
        # Reject newline / injection into GitHub Actions environment-file syntax.
        if any(not isinstance(v, str) or "\n" in v or "\r" in v for v in values.values()):
            fail("Invalid publication fields.")
        if not re.fullmatch(r"\d+\.\d+\.\d+", values["ADMIN_CONTROL_VERSION"]):
            fail("Invalid requested version.")
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
            for key, value in values.items():
                output.write(f"{key}={value}\n")
        print("Validated publication request.")
    elif len(sys.argv) == 2:
        prepare(sys.argv[1])
    else:
        fail("Usage: publish_admin_control.py VERSION | --load-request")
