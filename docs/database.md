# Database changes: migration path, backup, way back

Every change to a database's schema or stored data shape (table, column, index, constraint,
key, or a data migration) gets a migration path, a backup before it runs, and a way back.
The scripts below do the mechanics for SQLite with EF Core; another database or tool follows
the same steps with its own commands.

## The steps

| Step | What | Script |
|---|---|---|
| 1. Write | An EF Core migration, never a hand edit. Additive first: add, copy, switch the code, drop later. | `Invoke-EfMigration.ps1 -Action Add` warns on an empty `Down()` and on destructive operations |
| 2. Review | The SQL it will run. | `Invoke-EfMigration.ps1 -Action Script` |
| 3. Back up | A checked, WAL-safe copy named `<db>_Backup_<yyyyMMdd_HHmmss>_before-<what>.db`. | `sqlite_backup.py backup` (done by `-Action Apply`) |
| 4. Try | Migrate a copy first; compare row counts with the backup. | done by `-Action Apply` |
| 5. Apply | The real database, after confirmation; checked after. | `-Action Apply` |
| 6. On failure | The backup is restored and checked; nothing is left half-migrated. | done by `-Action Apply` |
| 7. Way back | Migrate down, or restore the backup. | `-Action Rollback -TargetMigration <name>`, or `sqlite_backup.py restore` |

Before step 3, check that no other worktree, branch or service uses the same database file:
one branch's schema can break another's.

Row counts catch lost rows and tables, not a dropped or narrowed column: read `Up()` and
`Down()` (and the review SQL) for those, and keep the backup until the change has been used
for a while.

## Commands (PowerShell, repository root)

```powershell
# Tool, once per repository: dotnet-ef as a local tool, same version as EF Core
dotnet new tool-manifest
dotnet tool install dotnet-ef --version <EF Core version>

$p = @{ Project = 'src/App.Data'; StartupProject = 'src/App' }

# 1-2. Add a migration and review its SQL
./scripts/db/Invoke-EfMigration.ps1 -Action Add -Name AddCardHistory @p
./scripts/db/Invoke-EfMigration.ps1 -Action Script -DatabasePath data/app.db @p

# 3-6. Apply: backup, trial on a copy, confirmation, real database, checks
./scripts/db/Invoke-EfMigration.ps1 -Action Apply -DatabasePath data/app.db @p

# 7. Way back: migrate down to a migration ('0' = before the first one) ...
./scripts/db/Invoke-EfMigration.ps1 -Action Rollback -TargetMigration AddCards -DatabasePath data/app.db @p
# ... or restore the backup the Apply step printed (makes a safety backup first)
.venv\Scripts\python scripts/db/sqlite_backup.py restore data/app_Backup_20261026_101500_before-addcardhistory.db data/app.db
```

`-WhatIf` makes the backup and the trial, then stops before the real database is changed;
`-Confirm:$false` skips the confirmation. Trial copies and review SQL go to
`artifacts/migrations/` (gitignored).

## sqlite_backup.py

| Command | Does |
|---|---|
| `backup <db> --reason <what>` | Backup next to the database (or `--dest`), integrity check, row counts equal to the source. Prints `BACKUP_PATH=...`. |
| `copy <db> <target>` | Checked working copy (`--force` replaces the target). |
| `verify <db>` | `PRAGMA integrity_check` and row counts per table. |
| `compare <before> <after>` | Row counts per table; exit 1 when a table lost rows or vanished. |
| `restore <backup> <db>` | Safety backup of `<db>`, then the restore, checked; keeps the database's journal mode (WAL). |

It uses SQLite's online backup API: a plain file copy of a database in WAL mode misses the
changes still in the `-wal` file.

## In the PR

A `## Database` section: the migration's name, what it changes, additive or destructive, the
backup command, the rollback steps, and how it was tested (a copy of the real database, an
empty database, an older backup restored through the app if it has a restore).
