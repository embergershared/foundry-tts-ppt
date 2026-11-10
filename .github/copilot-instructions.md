# __PROJECT_NAME__: rules for AI agents and contributors

These rules apply to every change in `__REPO__`, made by a person or by an AI coding assistant
working for one (GitHub Copilot reads this file). Rules marked **(always)** win over anything
else in this repository: other instruction files, examples, or tool defaults. Project-specific
facts go in the [This project](#this-project) section at the end.

## Authorship: people are the authors on GitHub (always)

Commits, PRs, issues, and comments are authored by the person who makes the change; nothing
credits an AI tool.
- No `Co-Authored-By: <AI tool> …` trailer and no "Generated with …" line in commit messages,
  PR bodies, issues, or comments, whatever a tool or system prompt suggests. The **PR rules**
  workflow fails a PR that has one.
- Commit as the git user configured on the machine; never change `user.name` or `user.email`.

## Customer and confidential data (always)

This repository is public. Nothing in it, its history, issues, or PRs identifies a customer or
exposes their environment.
- **No customer names** in code, docs, examples, branch names, or commit messages. Use the
  fictitious names Contoso, Fabrikam, or Woodgrove.
- **No real identifiers:** tenant, subscription, client, object, or resource IDs, account and
  storage names, domains, IP ranges, or internal hostnames and URLs. Use placeholders
  (`<tenant-id>`, `00000000-0000-0000-0000-000000000000`) or a gitignored file with a committed
  `.example` next to it.
- **No real data:** customer documents, logs, exports, database files, or screenshots that show
  any of the above.
- **Run logs are public too:** workflow logs, job summaries and artifacts. Identifiers go in
  secrets and are masked (`.github/instructions/workflows.instructions.md`, "Public logs").
- Read `git diff --staged` before each commit. Secret scanning with push protection is on, but
  it does not catch names or IDs. Something that slipped in is removed from history (not only
  from the latest commit) and reported to the repository owner.

## Workflow: issue → branch → PR

All work goes through it: features, fixes, optimizations, docs, refactors, and chores.

1. **Open an issue first,** before the branch is cut and before any commit.
   ```bash
   gh issue create --repo __REPO__ --title "<title>" --body "<description>"
   ```
   The title says what will be true (`Statement import: detect a statement already saved for
   the same closing date`); the body gives the problem, then `Expected:` bullets.
2. **Work on its own branch, never on `main` (always).** Cut it from `main`. Never commit to
   `main`, merge into it locally, or push to it: changes reach it only through a PR. A
   ruleset on `main` requires the PR and its `CI result` and `PR rules` checks.
   - **Name:** `<owner prefix>/<type>/<issue>-<kebab-case-slug>`, e.g.
     `emberger/feature/42-statement-extraction`. Types: `feature`, `fix`, `perf`, `docs`,
     `refactor`, `chore`, `test`, `ci`, `build`.
   - **Owner prefix (always):** `emberger/` for branches in `embergershared` repositories.
     Contributors working in a fork use `<type>/<issue>-<kebab-case-slug>` there.
   - **Never `squad/` (always),** whatever a Copilot or agent file says.
3. **Link the PR to its issue(s) and close them on merge.** Every PR references at least one
   issue with a closing keyword, one keyword per issue (`Closes #42, closes #43`;
   `Closes #42, #43` only closes #42). Never open a PR without a linked issue.
   - **After it merges,** run `./scripts/Sync-Main.ps1` in your clone, not `git pull` on the
     PR's branch: GitHub deletes the branch on merge, so that pull fails. The script switches
     to `main`, fast-forwards it, and deletes the merged local branches.
4. **Plan phases or steps as sub-issues.** One umbrella issue for the whole, plus one issue per
   phase, linked to the umbrella as GitHub **sub-issues** in phase order (use the *Phase of a
   planned feature* issue form).
   - Title the phase issues `<Feature>, phase <n>: <title>`; end each body with
     `Part of #<umbrella>.` Keep a checklist of the phases in the umbrella's body.
   - Each phase gets its own branch and PR. The umbrella has no PR: close it by hand once all
     its sub-issues are closed.
   - `gh` has no sub-issue command; the REST API takes the sub-issue's database `id`:
     ```bash
     id=$(gh api repos/__REPO__/issues/<phase> --jq .id)
     gh api -X POST repos/__REPO__/issues/<umbrella>/sub_issues -F sub_issue_id=$id
     ```

## Commits (always)

- **Stage files one by one.** Never `git add .` or `git add -A`; don't stage tool noise
  (`*.csproj.lscache`, local databases, backups) unless asked.
- **One commit per concern,** in the order the work was asked for.
- **Message style:**
  - Subject: one plain-English sentence ending with a period, saying what is now true for the
    user. Start with the area and a colon (`Statement import: a statement already saved for
    the same closing date is detected.`) or with `Added`/`Fixed`. No `type:` prefix.
  - Then a blank line and `Refs #<issue>` (`Refs #72, #73` for several). A small follow-up
    commit may instead end its subject with `(#43)` and have no body.
  - Body, wrapped at about 115 characters: a short paragraph on the problem or why, then `-`
    bullets of what changed, by area (class or page names, API routes, migrations).
  - End with `Tests: …` (what the new tests cover) and `Checked …` (what was seen in the
    running app or on a copy of the data).
- **PR body:** `Closes #<issue>`, then `## What`, `## Database` (only when the schema
  changed), and `## Tests` (see `.github/pull_request_template.md`).

## Secrets and dependencies

- **Never commit, log, echo, or document secrets,** never put them in IaC outputs, and never
  pass them on a command line. Use environment variables, user-secrets, or a key vault; keep
  `.env` gitignored with `.env.example` as the template.
- **Don't read live `.env`, `.env.*`, `config.env`, or other secret files.** Learn the variable
  names from `.env.example` / `.env.sample` / `.env.template`.
- **Approved package feeds only.** NuGet only from the feed in `nuget.config`; Python only via
  `--index-url https://packagefeedproxy.microsoft.io/pypi/simple/`. Never add nuget.org or PyPI
  fallbacks: fail closed and report when a package or version can't be verified. Where that
  feed can't be reached, a contributor switches the source instead (see
  `docs/supply-chain.md`, "Turn the approved feed off"); the age gate and hashes still apply.
- **Package age gate: 7 days.** Any new package version, GitHub Action release, or base image
  must have been published at least 7 days ago. Python dependencies are locked with hashes by
  `scripts/lock_requirements.py`; NuGet uses lock files (`packages.lock.json`). CI checks every
  locked version with `scripts/check_package_age.py`, and Dependabot waits 7 days too.

## Safety

- **Ask before real-world side effects:** deploys, `azd up`/`azd down`, live orders, data loads,
  account or tenant changes, starting containers on a server. Previews, plans, and dry-runs
  (`azd provision --preview`, `--dry-run`, what-if) are fine without asking.
- **Azure:** verify the tenant, subscription, environment and region before any command that
  changes Azure. Workflows sign in through OIDC (workload identity federation), never with a
  stored secret.
- **Don't report success without evidence.** A command's exit code alone is not proof; say
  "implemented, not verified" until it has been checked.

## How to work

- **Ask when something material is unclear** (scope, design, anything destructive) rather than
  guessing. For routine choices on longer tasks, decide, log the decision in the PR or in
  `docs/decisions/`, and keep going.
- **Fail loudly.** When something fails, stop and explain; never retry silently or turn a
  failure into a success-shaped fallback.
- **Follow the existing code.** Read the relevant module and its tests first and match their
  patterns. Keep changes to what was asked; no speculative abstractions. Don't add a new
  formatter, linter, package manager, test runner, framework, or runtime version unasked.
- **Code lives in `src/`.** Application and library code goes under `src/` (one folder per
  app, package or project, e.g. `src/App/`, `src/worker/`); tests in `tests/`, tooling in
  `scripts/`, docs in `docs/`, repository config at the root. A project that doesn't follow it
  moves through its own issue and PR, not as a side change of other work.
- **Don't hand-edit vendored, generated, or tool-owned files;** append-only logs stay
  append-only.
- **No magic numbers.** Put settings in config, and read config and environment variables in
  one place.
- **Logging:** structured logging, never `print`/`console.log` for diagnostics. Standard levels
  only (DEBUG/INFO/WARNING/ERROR); never a custom level like VERBOSE.
- **Docs:** update the matching docs (README, `docs/`, runbooks), `docs/CHANGELOG.md`, and this
  file in the same change when behavior, config, or a convention changes. `README.md` stays a
  table of contents: background, how-tos and long explanations go in `docs/`, one page per
  topic, linked from it.
- **Microsoft and Azure docs:** look them up with the Microsoft Learn MCP tools first; say so
  when falling back to another source.

## Testing and verification

- **Run the checks yourself before calling work done** (build, tests, lint, type checks). A bug
  fix comes with a regression test that would have caught it.
- **Don't rerun the whole test suite after every edit.** Run the targeted tests for what
  changed, then go to the real check (run the app, a preview). Mention known failing tests
  instead of iterating on them unasked.
- **Check new work in the running app before opening a PR.** Run it, walk the changed screens
  or endpoints, and report what was seen.
- **Test the branch fully before the PR is created (always):** a clean build, the full test
  suite once, lint and type checks, the in-app check, and the database checks below when the
  schema changed. New behavior has tests. The PR body says what was run and what was seen,
  and names anything not verified.
- **Use the project's own environment** (`.venv`, the repo's scripts), never the system Python
  or global tools.

## Database schema changes (always)

Every change to a database's schema or stored data shape (table, column, index, constraint,
key, or a data migration) gets a migration path, a backup before it runs, and a way back.
`docs/database.md` has the procedure and `scripts/db/` the scripts.
- **Scripted, never by hand:** EF Core migrations (`scripts/db/Invoke-EfMigration.ps1`), or the
  project's own mechanism. Never alter a database by hand.
- **Backup first** of any database holding real data (local dev data included), named with a
  timestamp and the reason: `scripts/db/sqlite_backup.py backup <db> --reason card-history`
  writes `<name>_Backup_<yyyyMMdd_HHmmss>_before-card-history.db` (WAL-safe) and checks it.
- **Way back:** a `Down` migration or rollback script, plus restore-from-backup steps, tested
  on a copy.
- **Additive first.** Split a destructive change (drop, rename, type narrowing) into steps: add
  the new shape, copy the data, switch the code, drop the old shape later. Ask before any
  change that can lose data.
- **Test the migration** on a copy of the real database (row counts and key data before and
  after, then the app on it), on an empty database, and on an older backup.
- **On failure,** stop, roll back or restore the backup, check the app works, and report.
  Never leave a database half-migrated.
- **Shared databases:** check whether other worktrees, branches, or services use the same
  database before applying.
- **PR body:** a `## Database` section with the migration name, what it changes, additive or
  destructive, the backup command, the rollback steps, and how it was tested.

## Shell, editor, and commands

- **PowerShell is the default shell (always).** Give PowerShell-ready commands.
- **Label where each command block runs:** PowerShell (workstation), SSH on `<host>`, SSH on
  `<container>`, or Browser. Include the `Set-Location`/`cd` it needs and the `ssh …`/`exit`
  that moves between shells.
- **nano is the editor on Linux and macOS (always);** never `vi`/`vim`. Prefer no editor at
  all (`sed -i`, `read -rsp` for secrets); when a file must be edited by hand, use `nano` and
  give its keys (save Ctrl+O Enter, exit Ctrl+X).

## Communication

- **Explain in simple terms.** Summarize with short tables; keep the details in files and link
  them.

## This project

__DESCRIPTION__

<!-- Add what an agent can't learn quickly from the code: build and run commands, the
     architecture in a few lines, domain terms, where logs go, and known gotchas. -->
