# CI/CD

All workflows run on GitHub-hosted `ubuntu-latest` runners: the repository is public, so a
self-hosted runner would run code from fork PRs. Actions are pinned by commit SHA (version in a
comment) and bumped by Dependabot after a 7-day cooldown.

| Workflow | When | What |
|---|---|---|
| **CI** (`ci.yml`) | push to `main`, every PR, by hand | Detects the stacks, then runs the jobs below; **`CI result`** sums them up. |
| **PR rules** (`pr-rules.yml`) | PR opened, edited, updated | Branch name, base branch, linked issue, no AI attribution, commit style (warnings). |
| **CodeQL** (default setup, no file) | push to `main`, every PR, weekly | Code scanning of the languages GitHub detects; results in **Security → Code scanning**. |

## CI jobs

| Job | Runs when | Steps |
|---|---|---|
| Detect stacks | always | .NET when a `*.slnx`/`*.sln`/`*.csproj` is tracked; Python when `requirements-dev.lock` or `requirements.lock` is. |
| Workflow lint | always | actionlint (checksum-verified download) with shellcheck on every `run:` script; shellcheck and a self-test of `mask-values` (see [Public logs](#public-logs)). |
| Package age gate | .NET or Python | `scripts/check_package_age.py`: every locked version at least 7 days old (see [supply-chain.md](supply-chain.md)). |
| .NET build and test | .NET | `setup-dotnet` from `global.json`, NuGet cache, restore in locked mode, `dotnet format --verify-no-changes`, Release build, tests with `.trx` results uploaded. |
| Python lint and test | Python | `setup-python` from `.python-version`, `pip install --require-hashes`, `ruff check`, `ruff format --check`, pytest (no tests = warning). |
| **CI result** | always | Fails when any job failed or was cancelled; skipped jobs are fine. The check the ruleset requires. |

PR runs cancel the previous run of the same PR; runs on `main` are never cancelled.

## Public logs

Anyone can read a public repository's run logs, job summaries and artifacts; a private
repository that becomes public shows its past runs too. GitHub masks secrets, and values a
step masks with `::add-mask::`, in the logs and summaries that follow, by matching their text
anywhere (a subscription ID inside a resource ID too). It doesn't mask **variables**: they are
printed as is, in every step header that has them in its `env`.

| Value | Where it goes | Why |
|---|---|---|
| On/off switches, paths (`TF_DEPLOY_ENABLED`, `DOTNET_SOLUTION`) | Repository variable | Nothing to hide |
| Tenant, subscription and client IDs; state resource group and account names | Secret (environment secret when it differs per environment) | Identifies the tenant and its resources |
| Lists of principals (JSON maps of names to object IDs) | Secret, and passed to `mask-values` | GitHub masks the whole JSON only; a step that prints one ID of it would show it |
| Values read at run time (outputs, resource IDs) | `mask-values` before the step that prints them | They are no secret GitHub knows of |

`.github/actions/mask-values` masks each line of its `values`, each GUID inside them, and each
key and string of a JSON document (shorter than `min-length`, 4: not masked). Run it first in
the job, with secrets only: a variable passed to it is printed in its own step header first.
```yaml
- uses: ./.github/actions/mask-values
  with:
    values: ${{ secrets.PROJECT_USER_PRINCIPALS }}
```
CI checks the script with shellcheck and a self-test on fictitious values (**Workflow lint**).

- **Summaries:** counts only for a plan, what-if or deployment (`Plan: 2 to add, 0 to change,
  0 to destroy`); the full plan stays in the masked log. A plan file holds every value
  unmasked: never upload it as an artifact.
- **No dumps:** no `set -x`, `env`, `printenv`, `TF_LOG`, `--debug` output.
- **Fork PRs** get no secrets and no OIDC token: jobs that need them run only when
  `github.event.pull_request.head.repo.full_name == github.repository`.
- **Something leaked:** delete the workflow run (its logs and summaries go with it), then
  rotate what can be rotated.

## Repository settings

`scripts/Initialize-Repo.ps1` sets these on a public repository. To check them later
(PowerShell):
```powershell
gh api repos/<owner>/<repo>/rulesets --jq '.[].name'
gh api repos/<owner>/<repo> --jq .security_and_analysis
gh api repos/<owner>/<repo>/code-scanning/default-setup --jq .state
```

| Setting | Value |
|---|---|
| Ruleset `main` (default branch) | No deletion, no force push, PR required (0 approvals: one maintainer), checks `CI result` and `PR rules` required |
| Secret scanning, push protection | On: a push with a known secret format is refused |
| Dependabot alerts and security updates | On |
| Private vulnerability reporting | On: see [SECURITY.md](SECURITY.md) |
| CodeQL | Default setup |
| Description (About) | The one the script used (`-Description`, or the repository's own) |
| Issues, wiki, merged branches | Issues on, wiki off, branches deleted on merge |
| GitHub Actions | On: added to the organization's selected repositories when needed (see [When GitHub Actions is off](#when-github-actions-is-off)) |

A new CI job is added to the `needs` of `CI result`, never as a separate required check, so the
ruleset doesn't change.

## Repository variables

| Variable | Default | Used by |
|---|---|---|
| `DOTNET_SOLUTION` | shallowest `*.slnx` / `*.sln` / `*.csproj` | CI |

Set one with `gh variable set DOTNET_SOLUTION --body src/App.slnx --repo <owner>/<repo>`.

## Deploys

The template has no deploy workflow: each project's target differs. For Azure, start the
infrastructure from [embergershared/azd-private-starter-template](https://github.com/embergershared/azd-private-starter-template),
and write the deploy workflow this way:
- triggered by a green CI run on `main`, or by hand with a version (rollback);
- behind an on/off repository variable and a GitHub environment (with required reviewers for
  anything beyond a sandbox);
- Azure through OIDC (`id-token: write`, `azure/login`, a federated credential on a user-assigned
  managed identity or app registration), never a client secret; the IDs in secrets and the
  job's identifiers masked (see [Public logs](#public-logs));
- a concurrency group that is never cancelled.

## Private repositories

GitHub Free has no rulesets, required checks, secret scanning or CodeQL for private
repositories. `Initialize-Repo.ps1` says so and skips them. There, the rules still ask for
PRs, and **PR rules** and **CI result** fail visibly on the PR: merge only when both are green.

## When GitHub Actions is off

An organization can run GitHub Actions in selected repositories only (embergershared does). A
repository created from the template isn't on that list, so `Initialize-Repo.ps1` adds it: that
needs the `admin:org` scope on the `gh` token, once per machine. Without it, or when the
owner's policy doesn't allow it, the script warns, skips the CodeQL default setup and creates
the `main` ruleset without its required checks (they would never report, so no PR could be
merged), then opens the PR as usual.

To finish the settings afterwards (PowerShell, workstation):
```powershell
gh auth refresh -h github.com -s admin:org
$repo = '<owner>/<repo>'
$id = gh api "repos/$repo" --jq .id
gh api -X PUT "orgs/$($repo.Split('/')[0])/actions/permissions/repositories/$id"
gh api "repos/$repo/actions/permissions" --jq .enabled
gh api -X PATCH "repos/$repo/code-scanning/default-setup" -f state=configured
```
Then, in the browser: **Settings → Rules → Rulesets → main → Require status checks to pass**,
add `CI result` and `PR rules`, and save.
