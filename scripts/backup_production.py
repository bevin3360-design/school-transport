#!/usr/bin/env python3
"""Take an encrypted, verifiable PostgreSQL backup of the live database.

Pipeline: pg_dump (custom format) -> pg_restore --list verification ->
SHA-256 -> GPG AES-256 symmetric encryption -> retention pruning.

The database URL is read from --url-file or STS_BACKUP_DB_URL and is never
printed. The passphrase is read from STS_BACKUP_PASSPHRASE or prompted.

Examples:
  python scripts/backup_production.py --url-file C:/Users/me/sts-backups/db_url.txt
  python scripts/backup_production.py --bundle-repo . --keep 30
  python scripts/backup_production.py --dry-run
"""

import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_OUT = Path.home() / "sts-backups"
DEFAULT_KEEP = 14


class BackupError(RuntimeError):
    pass


def find_tool(name, pg_bin=None):
    if pg_bin:
        candidate = Path(pg_bin) / (name + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            return str(candidate)
        raise BackupError(f"{name} not found in {pg_bin}")
    found = shutil.which(name)
    if not found:
        raise BackupError(
            f"{name} is not on PATH. Install PostgreSQL client tools or pass --pg-bin."
        )
    return found


def read_url(args):
    if args.url_file:
        raw = Path(args.url_file).read_text(encoding="utf-8-sig").strip()
    else:
        raw = os.environ.get("STS_BACKUP_DB_URL", "").strip()
    if not raw:
        raise BackupError(
            "No database URL. Pass --url-file PATH or set STS_BACKUP_DB_URL."
        )
    if "://" not in raw:
        raise BackupError("The database URL file does not contain a connection URL.")
    return raw


def connection_env(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise BackupError("Only postgres:// URLs are supported.")
    env = dict(os.environ)
    env["PGPASSWORD"] = unquote(parsed.password or "")
    env["PGCONNECT_TIMEOUT"] = env.get("PGCONNECT_TIMEOUT", "20")
    env.setdefault("PGSSLMODE", "require")
    params = {
        "host": parsed.hostname or "",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "dbname": unquote(parsed.path.lstrip("/") or ""),
    }
    return env, params, unquote(parsed.password or "")


def scrub(text, secrets):
    for value in secrets:
        if value:
            text = text.replace(value, "***")
    return text


def run(cmd, env, secrets, what):
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        detail = scrub((result.stderr or result.stdout).strip(), secrets)
        raise BackupError(f"{what} failed (exit {result.returncode}): {detail}")
    return scrub(result.stdout or "", secrets)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_passphrase(args):
    if args.passphrase_env:
        value = os.environ.get(args.passphrase_env, "")
        if not value:
            raise BackupError(f"Environment variable {args.passphrase_env} is empty.")
        return value
    value = os.environ.get("STS_BACKUP_PASSPHRASE", "")
    if value:
        return value
    if not sys.stdin.isatty():
        raise BackupError("Set STS_BACKUP_PASSPHRASE for non-interactive encryption.")
    first = getpass.getpass("Backup passphrase: ")
    if first != getpass.getpass("Repeat passphrase: "):
        raise BackupError("Passphrases did not match.")
    if len(first) < 12:
        raise BackupError("Use a passphrase of at least 12 characters.")
    return first


def gpg_encrypt(gpg, source, target, passphrase, secrets):
    cmd = [
        gpg, "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback",
        "--passphrase-fd", "0",
        "--symmetric", "--cipher-algo", "AES256",
        "--s2k-digest-algo", "SHA512", "--s2k-mode", "3",
        "--s2k-count", "65011712",
        "--output", str(target), str(source),
    ]
    result = subprocess.run(cmd, input=passphrase + "\n", text=True,
                            capture_output=True)
    if result.returncode != 0:
        raise BackupError("gpg encryption failed: "
                          + scrub(result.stderr.strip(), secrets))


def write_checksum(path):
    digest = sha256_file(path)
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def prune(out_dir, keep):
    backups = sorted(out_dir.glob("sts-*.dump.gpg"), key=lambda p: p.stat().st_mtime)
    removed = []
    for old in backups[:-keep] if keep > 0 else []:
        for path in (old, old.with_name(old.name + ".sha256"),
                     old.with_suffix("").with_suffix(".json")):
            if path.exists():
                path.unlink()
                removed.append(path.name)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url-file", help="file containing the postgres:// URL")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--pg-bin", help="directory holding pg_dump/pg_restore")
    parser.add_argument("--passphrase-env", default=None,
                        help="env var holding the encryption passphrase")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help=f"backups to retain (default {DEFAULT_KEEP})")
    parser.add_argument("--bundle-repo", metavar="PATH",
                        help="also create an encrypted git bundle of this repo")
    parser.add_argument("--dry-run", action="store_true",
                        help="check tools and paths without connecting")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    pg_dump = find_tool("pg_dump", args.pg_bin)
    pg_restore = find_tool("pg_restore", args.pg_bin)
    gpg = shutil.which("gpg") or shutil.which("gpg.exe")
    if not gpg:
        raise BackupError("gpg is required for encryption and was not found.")

    if args.dry_run:
        print("dry run ok")
        print(f"  pg_dump    {pg_dump}")
        print(f"  pg_restore {pg_restore}")
        print(f"  gpg        {gpg}")
        print(f"  out_dir    {out_dir}")
        return 0

    url = read_url(args)
    env, params, password = connection_env(url)
    secrets = [password]
    passphrase = read_passphrase(args)

    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    archive = out_dir / f"sts-{stamp}.dump.gpg"
    manifest = out_dir / f"sts-{stamp}.json"
    fd, tmp_name = tempfile.mkstemp(prefix="sts-", suffix=".dump", dir=out_dir)
    os.close(fd)
    tmp = Path(tmp_name)

    try:
        dump_cmd = [pg_dump, "--format=custom", "--compress=9",
                    "--no-owner", "--no-privileges",
                    "--host", params["host"], "--port", params["port"],
                    "--username", params["user"], "--dbname", params["dbname"],
                    "--file", str(tmp)]
        run(dump_cmd, env, secrets, "pg_dump")
        if tmp.stat().st_size < 1024:
            raise BackupError("pg_dump produced an empty archive.")

        toc = run([pg_restore, "--list", str(tmp)], env, secrets,
                  "pg_restore --list verification")
        entries = [line for line in toc.splitlines()
                   if line and not line.startswith(";")]
        if not entries or "TABLE DATA" not in toc:
            raise BackupError("Archive verification failed: no table data in TOC.")

        gpg_encrypt(gpg, tmp, archive, passphrase, secrets)
        encrypted_digest = write_checksum(archive)

        record = {
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "database": params["dbname"],
            "host_suffix": params["host"][-10:],
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": encrypted_digest,
            "toc_entries": len(entries),
            "pg_dump": run([pg_dump, "--version"], env, secrets, "pg_dump version").strip(),
            "repo_bundle": None,
        }

        if args.bundle_repo:
            repo = Path(args.bundle_repo).resolve()
            bundle = out_dir / f"sts-repo-{stamp}.bundle"
            run(["git", "-C", str(repo), "bundle", "create", str(bundle),
                 "--all"], dict(os.environ), secrets, "git bundle")
            gpg_encrypt(gpg, bundle, bundle.with_name(bundle.name + ".gpg"),
                        passphrase, secrets)
            write_checksum(bundle.with_name(bundle.name + ".gpg"))
            bundle.unlink()
            record["repo_bundle"] = bundle.name + ".gpg"

        manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    finally:
        if tmp.exists():
            tmp.unlink()

    removed = prune(out_dir, args.keep)
    print(f"backup written: {archive.name} ({record['archive_bytes']} bytes)")
    print(f"sha256: {encrypted_digest}")
    print(f"toc entries verified: {record['toc_entries']}")
    if record["repo_bundle"]:
        print(f"repo bundle: {record['repo_bundle']}")
    if removed:
        print(f"pruned: {', '.join(removed)}")
    print("next: copy these files to offline media, then run restore_backup.py "
          "against a scratch database to prove the archive opens.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BackupError as error:
        print(f"BACKUP FAILED: {error}", file=sys.stderr)
        sys.exit(1)
