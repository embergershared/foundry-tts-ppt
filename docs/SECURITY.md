# Security

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately instead:
**Security → Report a vulnerability** on this repository
([private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)).

Include what you found, how to reproduce it, and what it affects. Leave out real secrets,
customer data, and tenant or subscription IDs: describe them instead.

This is a personal project maintained on a best-effort basis: there is no response-time
commitment, but reports are read and acknowledged.

## Scope

This repository only. A vulnerability in a Microsoft product or service goes to the
[Microsoft Security Response Center](https://msrc.microsoft.com/create-report); one in a
dependency goes to that project.

## What the repository does to stay safe

- Secret scanning with push protection, Dependabot alerts and security updates, and CodeQL.
- Dependencies locked with hashes, from an approved feed, and at least 7 days old
  ([supply-chain.md](supply-chain.md)).
- GitHub Actions pinned by commit SHA, with read-only tokens by default; identifiers kept in
  secrets and masked in the public run logs ([ci-cd.md](ci-cd.md#public-logs)).
