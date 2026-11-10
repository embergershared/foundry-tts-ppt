# Package feeds and the age gate

Two rules, from the repository rules:
1. **Approved feed only.** NuGet from `nuget.config` (`<clear/>` + packagefeedproxy); Python
   through `https://packagefeedproxy.microsoft.io/pypi/simple/` (the pip configuration of the
   maintainer's machine). Never a nuget.org or PyPI fallback next to it: fail closed. Where the
   feed can't be reached, switch the source instead (see
   [Turn the approved feed off](#turn-the-approved-feed-off)).
2. **7-day age gate.** A package version, GitHub Action release or base image is used only
   once it has been public for at least 7 days.

## How each ecosystem follows them

| Ecosystem | Locked in | Age gate | Integrity |
|---|---|---|---|
| NuGet | `packages.lock.json` per project (`RestorePackagesWithLockFile`), versions in `Directory.Packages.props` | CI: `scripts/check_package_age.py` (nuget.org publish dates) | Lock file content hashes; CI restores in locked mode |
| Python | `requirements*.lock` from `scripts/lock_requirements.py` | At lock time (too-new releases excluded) and in CI | sha256 hashes, checked against PyPI; `pip install --require-hashes` |
| GitHub Actions | commit SHA in each `uses:` | Dependabot `cooldown: default-days: 7` | the SHA |
| Docker base images | digest (`image@sha256:...`) in the Dockerfile or a repository variable | by hand (and Dependabot docker, once enabled) | the digest |

## Update a package

**NuGet** (PowerShell):
```powershell
# 1. Change the version in Directory.Packages.props (a release at least 7 days old)
dotnet restore --force-evaluate     # rewrites the packages.lock.json files
python scripts/check_package_age.py # same check as CI
```

**Python** (PowerShell, project `.venv`):
```powershell
# 1. Change requirements.in / requirements-dev.in (names and ranges, not exact pins)
.venv\Scripts\python scripts/lock_requirements.py   # resolves, excludes too-new releases, hashes
.venv\Scripts\python -m pip install --require-hashes -r requirements-dev.lock
```

## When CI's age gate fails

The job lists each version and its publish date. Pick the previous release (or wait until it
is 7 days old). For an urgent fix that can't wait (a security patch), add one line to
`scripts/package-age-allow.txt` with the reason, in the same PR:
```
nuget:Some.Package==1.2.3  # CVE-2026-1234: fix needed now; remove after 2026-11-02
```

## Running the check locally

`python scripts/check_package_age.py` reads the tracked lock files. Where nuget.org is
blocked, point it at your feed's NuGet registration (its dates are when the feed first cached
each package, so it is stricter):
```powershell
python scripts/check_package_age.py --nuget-registration <your feed's registrations2-semver2/ URL>
```

## Turn the approved feed off

The approved feed, `packagefeedproxy.microsoft.io`, is what the maintainer's Microsoft-managed
machine is allowed to use. Outside such a machine (a customer, a contributor, a fork), it may
not be reachable: switch the source, don't add a second one.

| Ecosystem | Where | Change |
|---|---|---|
| NuGet | `nuget.config` | Replace the `packagefeedproxy` line with `<add key="nuget.org" value="https://api.nuget.org/v3/index.json" />`, or your organization's feed. Keep `<clear />`: one source only. |
| Python | your pip configuration | `pip config unset global.index-url` (or set your organization's index) before `scripts/lock_requirements.py`. The script prints the index it uses. |

The age gate and the hashes don't depend on the feed: the lock files keep the same versions and
hashes whichever source served them (`lock_requirements.py` checks every pin against pypi.org).
In a project's own repository, commit a feed change through its issue and PR, and say why in
the PR; in a fork, keep it local (`git update-index --skip-worktree nuget.config`).
