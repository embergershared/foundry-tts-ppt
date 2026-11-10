"""Back up, check, compare and restore SQLite databases safely (WAL included).

A plain file copy of a SQLite database in WAL mode misses the changes still in the -wal file;
this script uses SQLite's online backup API instead, which copies a consistent snapshot even
while an app has the database open.

  backup  <db> --reason <what>   <name>_Backup_<yyyyMMdd_HHmmss>_before-<what>.db next to the
                                 database (or in --dest), then integrity check and row counts
  copy    <db> <target>          a working copy (e.g. to try a migration on), checked the same way
  verify  <db>                   integrity check and row count per table
  compare <before> <after>       row counts per table; fails when a table lost rows or vanished
                                 (EF Core's __EFMigrations* bookkeeping tables are left out)
  restore <backup> <db>          backs up <db> first (reason before-restore), then restores the
                                 backup into it and checks it

Exit code 0 = OK, 1 = a check failed, 2 = usage error. Standard library only: run it with the
project's Python (.venv), e.g.
    .venv\\Scripts\\python scripts/db/sqlite_backup.py backup data/app.db --reason card-history
"""

import argparse
import contextlib
import datetime as dt
import os
import re
import sqlite3
import sys


def connect(path: str, readonly: bool = True) -> contextlib.closing:
    """A connection closed on exit (sqlite3's own context manager only commits)."""
    if readonly:
        uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro"
        return contextlib.closing(sqlite3.connect(uri, uri=True))
    return contextlib.closing(sqlite3.connect(path))


def tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def row_counts(path: str) -> dict[str, int]:
    with connect(path) as con:
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables(con)}


def integrity(path: str) -> str:
    with connect(path) as con:
        return con.execute("PRAGMA integrity_check").fetchone()[0]


def snapshot(source: str, target: str) -> None:
    """Copy source into target with the online backup API (WAL-safe)."""
    with connect(source) as src, connect(target, readonly=False) as dst:
        src.backup(dst)
        # A single self-contained file: rollback journal instead of WAL, so opening the copy
        # later leaves no -wal / -shm files next to it.
        dst.execute("PRAGMA journal_mode=DELETE")


def check(path: str, expected: dict[str, int] | None = None) -> bool:
    result = integrity(path)
    counts = row_counts(path)
    print(f"  integrity_check: {result}")
    print(f"  tables: {len(counts)}, rows: {sum(counts.values())}")
    ok = result == "ok"
    if expected is not None and counts != expected:
        print("  row counts differ from the source:")
        for t in sorted(set(counts) | set(expected)):
            if counts.get(t) != expected.get(t):
                print(f"    {t}: source {expected.get(t)}, copy {counts.get(t)}")
        ok = False
    return ok


def backup_path(db: str, reason: str, dest: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")
    if not slug:
        sys.exit("--reason must contain letters or digits")
    if not slug.startswith("before-"):
        slug = f"before-{slug}"
    stem, ext = os.path.splitext(os.path.basename(db))
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(
        dest or os.path.dirname(os.path.abspath(db)), f"{stem}_Backup_{stamp}_{slug}{ext or '.db'}"
    )


def require(path: str) -> None:
    if not os.path.isfile(path):
        print(f"No database at {path}")
        sys.exit(2)


def cmd_backup(args) -> int:
    require(args.db)
    if args.dest:
        os.makedirs(args.dest, exist_ok=True)
    target = backup_path(args.db, args.reason, args.dest)
    print(f"Backup {args.db}\n    -> {target}")
    snapshot(args.db, target)
    ok = check(target, row_counts(args.db))
    print("Backup OK" if ok else "BACKUP FAILED the checks: don't change the database")
    print(f"BACKUP_PATH={target}")
    return 0 if ok else 1


def cmd_copy(args) -> int:
    require(args.db)
    if os.path.exists(args.target) and not args.force:
        print(f"{args.target} exists (--force to replace it)")
        return 2
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(args.target + suffix):
            os.remove(args.target + suffix)
    print(f"Copy {args.db}\n  -> {args.target}")
    snapshot(args.db, args.target)
    ok = check(args.target, row_counts(args.db))
    print("Copy OK" if ok else "COPY FAILED the checks")
    return 0 if ok else 1


def cmd_verify(args) -> int:
    require(args.db)
    print(f"Verify {args.db}")
    ok = check(args.db)
    for table, count in row_counts(args.db).items():
        print(f"    {table}: {count}")
    return 0 if ok else 1


def cmd_compare(args) -> int:
    require(args.before)
    require(args.after)
    ignored = set(args.ignore)
    before = {t: n for t, n in row_counts(args.before).items() if t not in ignored}
    after = {t: n for t, n in row_counts(args.after).items() if t not in ignored}
    print(f"{'table':40} {'before':>10} {'after':>10}")
    lost = []
    for t in sorted(set(before) | set(after)):
        b, a = before.get(t), after.get(t)
        if b is None:
            mark = "  (new)"
        elif a is None:
            mark = "  <- table gone"
        elif a < b:
            mark = "  <- rows lost"
        else:
            mark = "  (rows added)" if a > b else ""
        if "<-" in mark:
            lost.append(t)
        print(f"{t:40} {'' if b is None else b:>10} {'' if a is None else a:>10}{mark}")
    if lost:
        print(f"DATA LOSS in: {', '.join(lost)}")
        return 1
    print("No table lost rows")
    return 0


def cmd_restore(args) -> int:
    require(args.backup)
    print(f"Check the backup {args.backup}")
    if integrity(args.backup) != "ok":
        print("The backup fails its integrity check: nothing restored")
        return 1
    if os.path.isfile(args.db) and not args.no_safety_backup:
        safety = backup_path(args.db, "restore", None)
        print(f"Safety backup of the current database -> {safety}")
        snapshot(args.db, safety)
    print("Make sure no app has the database open while it is restored.")
    print(f"Restore {args.backup}\n     -> {args.db}")
    expected = row_counts(args.backup)
    with connect(args.db, readonly=False) as dst:
        mode = dst.execute("PRAGMA journal_mode").fetchone()[0]
        with connect(args.backup) as src:
            src.backup(dst)
        dst.execute(f"PRAGMA journal_mode={mode}")  # the app's own mode (e.g. WAL) again
    ok = check(args.db, expected)
    print("Restore OK" if ok else "RESTORE FAILED the checks")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("backup", help="timestamped, checked backup next to the database")
    p.add_argument("db")
    p.add_argument("--reason", required=True, help="what comes next, e.g. card-history")
    p.add_argument("--dest", help="folder for the backup (default: the database's folder)")
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("copy", help="checked working copy")
    p.add_argument("db")
    p.add_argument("target")
    p.add_argument("--force", action="store_true", help="replace an existing target")
    p.set_defaults(fn=cmd_copy)
    p = sub.add_parser("verify", help="integrity check and row counts")
    p.add_argument("db")
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("compare", help="row counts before and after; fails on data loss")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument(
        "--ignore",
        nargs="*",
        default=["__EFMigrationsHistory", "__EFMigrationsLock"],
        help="tables left out (default: EF Core's migration bookkeeping)",
    )
    p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("restore", help="restore a backup into the database")
    p.add_argument("backup")
    p.add_argument("db")
    p.add_argument(
        "--no-safety-backup", action="store_true", help="don't back up the current database first"
    )
    p.set_defaults(fn=cmd_restore)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
