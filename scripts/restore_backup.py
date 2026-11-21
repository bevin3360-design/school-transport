#!/usr/bin/env python3
"""Prove a backup opens by restoring it into a scratch database.

Decrypts the .gpg archive, checks its SHA-256 sidecar, then restores into the
target database in a single transaction. The target must contain no tables
unless --force is given, so this cannot overwrite a live database by accident.

Examples:
  set STS_RESTORE_DB_URL=postgres://...    (scratch database)
  python scripts/restore_backup.py --backup C:/Users/me/sts-backups/sts-20261121T153000.dump.gpg
"""

import argparse
import getpass
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from backup_production import BackupError, find_tool, scrub


def verify_sidecar(archive):
    sidecar = archive.with_name(archive.name + ".sha256")
    if not sidecar.exists():
        print(f"warning: {sidecar.name} missing; skipping checksum check")
        return
    expected = sidecar.read_text(encoding="ascii").split()[0]
    digest = hashlib.sha256()
    with open(archive, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise BackupError("SHA-256 mismatch: the archive is damaged or altered.")
    print("checksum ok")


def decrypt(gpg, archive, target, passphrase):
    cmd = [gpg, "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback",
           "--passphrase-fd", "0", "--decrypt", "--output", str(target),
           str(archive)]
    result = subprocess.run(cmd, input=passphrase + "\n", text=True,
                            capture_output=True)
    if result.returncode != 0:
        raise BackupError("decryption failed: " + result.stderr.strip())


def psql_scalar(psql, url_env, query):
    result = subprocess.run(
        [psql, "--no-psqlrc", "--tuples-only", "--no-align",
         "--set", "ON_ERROR_STOP=1", "--command", query],
        env=url_env, capture_output=True, text=True)
    if result.returncode != 0:
        raise BackupError("psql failed: " + result.stderr.strip())
    return result.stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backup", required=True, help="path to .dump.gpg")
    parser.add_argument("--target-url", default=None,
                        help="scratch database URL (or STS_RESTORE_DB_URL)")
    parser.add_argument("--pg-bin", help="directory holding pg_restore/psql")
    parser.add_argument("--force", action="store_true",
                        help="restore even if the target already has tables")
    args = parser.parse_args(argv)

    archive = Path(args.backup).expanduser()
    if not archive.is_file():
        raise BackupError(f"{archive} not found")

    raw = (args.target_url or os.environ.get("STS_RESTORE_DB_URL", "")).strip()
    if "://" not in raw:
        raise BackupError("Pass --target-url or set STS_RESTORE_DB_URL.")
    parsed = urlparse(raw)
    env = dict(os.environ)
    env["PGPASSWORD"] = unquote(parsed.password or "")
    env["PGCONNECT_TIMEOUT"] = env.get("PGCONNECT_TIMEOUT", "20")
    env.setdefault("PGSSLMODE", "require")
    secrets = [unquote(parsed.password or "")]

    pg_restore = find_tool("pg_restore", args.pg_bin)
    psql = find_tool("psql", args.pg_bin)
    gpg = shutil.which("gpg") or shutil.which("gpg.exe")
    if not gpg:
        raise BackupError("gpg was not found.")

    verify_sidecar(archive)

    existing = psql_scalar(
        psql, env,
        "select count(*) from information_schema.tables "
        "where table_schema not in ('pg_catalog','information_schema');")
    if existing != "0" and not args.force:
        raise BackupError(
            f"target already has {existing} tables; use an empty scratch "
            "database or pass --force.")

    passphrase = os.environ.get("STS_BACKUP_PASSPHRASE", "")
    if not passphrase:
        if not sys.stdin.isatty():
            raise BackupError("Set STS_BACKUP_PASSPHRASE for decryption.")
        passphrase = getpass.getpass("Backup passphrase: ")

    fd, tmp_name = tempfile.mkstemp(prefix="sts-restore-", suffix=".dump")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        decrypt(gpg, archive, tmp, passphrase)
        toc = subprocess.run([pg_restore, "--list", str(tmp)],
                             capture_output=True, text=True)
        if toc.returncode != 0:
            raise BackupError("archive is not readable: "
                              + scrub(toc.stderr.strip(), secrets))
        result = subprocess.run(
            [pg_restore, "--no-owner", "--no-privileges", "--exit-on-error",
             "--single-transaction",
             "--host", parsed.hostname or "", "--port", str(parsed.port or 5432),
             "--username", unquote(parsed.username or ""),
             "--dbname", unquote(parsed.path.lstrip("/") or ""), str(tmp)],
            env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise BackupError("restore failed: "
                              + scrub(result.stderr.strip(), secrets))
    finally:
        if tmp.exists():
            tmp.unlink()

    tables = psql_scalar(
        psql, env,
        "select count(*) from information_schema.tables "
        "where table_schema='public';")
    print(f"restore ok: {tables} tables in the scratch database")
    print("drill complete. Drop the scratch database once you are satisfied.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BackupError as error:
        print(f"RESTORE FAILED: {error}", file=sys.stderr)
        sys.exit(1)
