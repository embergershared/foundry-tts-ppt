---
applyTo: ".github/workflows/**"
---

# GitHub Actions workflows

- **Pin actions by commit SHA** with the version in a comment
  (`actions/checkout@<sha> # v7.0.1`), and only releases at least 7 days old. Dependabot
  (`.github/dependabot.yml`, 7-day cooldown) proposes the bumps.
- **Least privilege:** top-level `permissions: contents: read`; widen per job only.
  `persist-credentials: false` on checkout unless the job pushes.
- **Every job** has `timeout-minutes`. Concurrency: cancel superseded PR runs; never cancel
  runs on `main`, image pushes, deploys or teardowns.
- **Untrusted input** (PR titles, bodies, branch names) goes through `env:`, never straight
  into `run:` with `${{ }}`.
- **GitHub-hosted runners only.** This repository is public: a self-hosted runner would run
  code from fork PRs on that machine.
- **Deploys:** behind a GitHub environment and an on/off repository variable; Azure through
  OIDC (`id-token: write`, `azure/login`), never a client secret.
- **Public logs (always).** Anyone can read a public repository's run logs, job summaries and
  artifacts, and a private one may become public. See `docs/ci-cd.md`, "Public logs".
  - Identifiers (tenant, subscription, client and object IDs, state account and resource
    names) are **secrets** (repository or environment), never variables: a variable is printed
    unmasked, in every step header that has it in its `env`.
  - A job that can print identifiers starts with `./.github/actions/mask-values`, given the
    structured secrets (JSON maps) and any identifier read at run time, so each part of them
    is masked too.
  - Never write a full Terraform plan, what-if or deployment output to `$GITHUB_STEP_SUMMARY`
    or an artifact: the summary shows the counts (`Plan: 2 to add, 0 to change, 0 to
    destroy`), the masked log the rest. A plan file is never uploaded.
  - No `set -x`, `env`/`printenv` dumps, `TF_LOG`, or debug output of a command that prints
    tokens or IDs.
  - Jobs that need secrets or OIDC skip fork PRs
    (`github.event.pull_request.head.repo.full_name == github.repository`): forks get neither.
- **`CI result`** in `ci.yml` is the single check to require: add new CI jobs to its `needs`.
- actionlint (with shellcheck) runs in CI on every workflow change.
