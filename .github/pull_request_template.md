Closes #

## What
<!-- The problem or why, in a sentence or two. Then what changed, by area:
- `ClassOrPage`: what it does now.
-->

## Database
<!-- Only when the schema or stored data shape changed; delete this section otherwise.
- Migration: `<name>`: what it changes; additive or destructive.
- Backup: `python scripts/db/sqlite_backup.py backup <db> --reason <what>`
- Rollback: `scripts/db/Invoke-EfMigration.ps1 -Action Rollback -TargetMigration <previous>`, or restore the backup.
- Tested on: a copy of the real database (row counts before/after), an empty database, an older backup.
-->

## Tests
<!-- What was run on this branch and what was seen. Name anything not verified.
- Clean build, full test suite, lint and type checks: ...
- Checked in the running app: ...
-->
