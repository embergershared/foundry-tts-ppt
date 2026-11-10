# What the template contains

New embergershared repositories start from
[embergershared/repo-template](https://github.com/embergershared/repo-template). It brings the
rules, tools, CI/CD and security settings shared by the projects, so each project doesn't
re-create them. Most of these projects are public: the template assumes it.

## Start a project

1. On GitHub: **embergershared/repo-template → Use this template → Create a new repository**
   (owner `embergershared`, public).
2. Clone it, then in its folder (PowerShell):
   ```powershell
   ./scripts/Initialize-Repo.ps1 -Description '<one line about the project>' -Stacks dotnet,python
   ```
   `-Stacks dotnet` or `-Stacks python` removes the other stack's files. `-WhatIf` shows what
   would change; `-SkipGitHub` only edits the files.
   The script replaces the placeholders `__PROJECT_NAME__`, `__REPO__`, `__DESCRIPTION__` and
   `__YEAR__` (this file keeps them), sets the repository (description, issues on, wiki off,
   branches deleted on merge, label `phase`, GitHub Actions) and, when it is public, its
   security features and the `main` ruleset (see [ci-cd.md](ci-cd.md#repository-settings)). Where the
   organization runs Actions in selected repositories only, it adds the repository to that list,
   which needs the `admin:org` scope (`gh auth refresh -h github.com -s admin:org`); without it,
   it skips what needs Actions and says how to finish (see
   [ci-cd.md](ci-cd.md#when-github-actions-is-off)). Then it opens issue
   *Initialize the repository from repo-template*, commits on
   `emberger/chore/<issue>-initialize-from-template`, opens the PR, and switches back to `main`.
3. Merge that PR once its checks are green, run `./scripts/Sync-Main.ps1` (see
   [After every PR merges](#after-every-pr-merges)), then see [After the first PR](#after-the-first-pr).

## After every PR merges

GitHub deletes a PR's branch when it merges. The local branch then tracks a ref that no longer
exists, and a plain `git pull` on it fails ("Your configuration specifies to merge with the ref
… but no such ref was fetched"). Run instead (PowerShell, in the repository's folder):
```powershell
./scripts/Sync-Main.ps1
```
It fetches with prune, switches to `main` and fast-forwards it, and deletes the local branches
whose remote branch is gone and that are merged. A gone branch that isn't merged (PR closed, or
squash-merged) is kept and named: check it, then `git branch -D <name>`.

## Files

| Path | What it does |
|---|---|
| `.github/copilot-instructions.md` | **The rules** for people and AI coding assistants: authorship, customer data, issue → branch → PR, branch names, commits, secrets, feeds and age gate, safety, testing, database migrations, PowerShell, nano. Ends with a *This project* section to fill in. |
| `.github/instructions/*.instructions.md` | Copilot rules per file type: .NET, Python, workflows. |
| `.github/workflows/ci.yml` | Build, lint, test (.NET and Python, auto-detected), workflow lint, package age gate, one `CI result` check. |
| `.github/actions/mask-values/` | Masks identifiers, the GUIDs inside them and the parts of a JSON secret in a job's logs and summary (see [ci-cd.md](ci-cd.md#public-logs)). |
| `.github/workflows/pr-rules.yml` | Branch name (no owner prefix from a fork), base branch, linked issue, no AI attribution, commit style warnings. |
| `.github/dependabot.yml` | GitHub Actions updates with a 7-day cooldown, weekly (daily in the template); NuGet and Docker ready to uncomment. |
| `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/` | PR body (What, Database, Tests) and issue forms (feature, bug, phase). |
| `README.md` | Project page: the description, the "personal project, not an official Microsoft product" note, then a table of contents of the pages. Nothing else goes there. |
| `docs/getting-started.md` | Build, run and test the project locally (to fill in). |
| `docs/SECURITY.md`, `docs/SUPPORT.md`, `docs/CONTRIBUTING.md`, `docs/CODE_OF_CONDUCT.md` | Private vulnerability reporting, as-is support, how to contribute, Contributor Covenant. GitHub finds them in `docs/` as it does at the root. |
| `.editorconfig`, `.gitattributes`, `.gitignore`, `.dockerignore` | Editor rules, line endings (LF for Linux files), ignored secrets/databases/build output. |
| `global.json`, `Directory.Build.props`, `Directory.Packages.props`, `nuget.config` | .NET 10 SDK, `net10.0`, analyzers, lock files, central package versions, approved feed only. |
| `.python-version`, `ruff.toml` | Python 3.13 and ruff settings. |
| `scripts/lock_requirements.py` | `requirements*.in` → hash-locked `requirements*.lock`, through the approved feed, 7-day gate. |
| `scripts/check_package_age.py` | CI gate: every locked NuGet/PyPI version is at least 7 days old. |
| `scripts/db/sqlite_backup.py` | WAL-safe SQLite backup, copy, verify, compare, restore. |
| `scripts/db/Invoke-EfMigration.ps1` | EF Core migrations: backup, trial on a copy, apply, restore on failure, rollback. |
| `scripts/Initialize-Repo.ps1` | One-time setup of a new repository (removes itself). |
| `scripts/Sync-Main.ps1` | After a PR merges: back on an up-to-date `main`, merged local branches deleted. |
| `docs/` | Every other page: CI/CD, public logs and repository settings, supply chain (and how to turn the approved feed off), database, decisions (ADR template). |
| `docs/CHANGELOG.md`, `LICENSE` | Keep a Changelog; MIT (stays at the root, where GitHub reads the license). |

The template has no agent-tool configuration beyond Copilot's instruction files: anything a
maintainer's own tools need stays in that maintainer's user settings, not in the repository.

## Add a stack

Code goes under `src/`, tests under `tests/`, tooling under `scripts/` and docs under `docs/`
(the rule is in `.github/copilot-instructions.md`, *How to work*).

- **.NET:** `dotnet new sln --format slnx` at the root, add projects under `src/<Name>/`
  without `TargetFramework` or package versions (they come from `Directory.Build.props` /
  `Directory.Packages.props`), add `<PackageVersion>` lines, `dotnet restore`, commit the
  `packages.lock.json` files. Tests: `tests/<Name>.Tests/` projects with xUnit. CI builds the
  shallowest `*.slnx`/`*.sln` (or set the repository variable `DOTNET_SOLUTION`).
- **Python:** code under `src/<package>/`, tests under `tests/` (with a `conftest.py` that puts
  `src/` on the import path); `requirements.in` (runtime) and `requirements-dev.in`
  (`-r requirements.in`, then `ruff`, `pytest`) at the root, then in the project's `.venv`:
  ```powershell
  py -3.13 -m venv .venv
  .venv\Scripts\python -m pip install uv
  .venv\Scripts\python scripts/lock_requirements.py
  .venv\Scripts\python -m pip install --require-hashes -r requirements-dev.lock
  ```
  CI runs ruff and pytest once `requirements-dev.lock` (or `requirements.lock`) is committed.
- **Azure infrastructure:** start from
  [embergershared/azd-private-starter-template](https://github.com/embergershared/azd-private-starter-template)
  and deploy through OIDC (see [ci-cd.md](ci-cd.md#deploys)).

## After the first PR

- **Dependabot:** uncomment the `nuget` / `docker` blocks the project needs.
- **CodeQL:** once the project has code, check **Security → Code scanning** lists its
  languages (default setup picks them up on the next scan).
- Fill in `docs/getting-started.md` and the *This project* section of
  `.github/copilot-instructions.md`.

## Keep the template's pins current

Dependabot checks a repository as soon as `.github/dependabot.yml` lands in it, so a new
repository gets an update PR for every action release that has cleared the 7-day cooldown but
is not yet pinned in the template. To avoid that, the template's Dependabot checks **daily**
(the `# template:start` block, which `Initialize-Repo.ps1` turns into weekly on Monday):
merge its PRs as soon as their checks are green, before creating a repository from it.

## Keep projects in step with the template

The template only copies files once. When it improves, port the change to existing projects
through an issue and PR in each.
