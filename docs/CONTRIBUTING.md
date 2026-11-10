# Contributing

Thank you for helping. The full rules, for people and AI coding assistants alike, are in
[.github/copilot-instructions.md](../.github/copilot-instructions.md); this is the short version.

1. **Open an issue first** that says what will be true when it is done, so we agree on it
   before you write code.
2. **Fork the repository and branch** from `main` as `<type>/<issue>-<kebab-case-slug>`, e.g.
   `fix/57-retry-on-throttle`. Types: `feature`, `fix`, `perf`, `docs`, `refactor`, `chore`,
   `test`, `ci`, `build`.
3. **Commit** one concern per commit. Subject: one sentence ending with a period that says what
   is now true (`Statement import: a statement already saved for the same closing date is
   detected.`); then a blank line and `Refs #<issue>`.
4. **Run the checks** before you open the PR: build, tests, lint (see
   [getting-started.md](getting-started.md)).
5. **Open the PR** against `main`, with `Closes #<issue>` and the sections of the PR template.
   The **CI result** and **PR rules** checks must be green.

## Never commit

- Secrets, keys, connection strings, or `.env` files (use `.env.example` for the names).
- Customer names, tenant, subscription or resource IDs, internal hostnames or URLs, or real
  data. Use Contoso, Fabrikam or Woodgrove, and placeholders such as `<tenant-id>`.

## Authorship

You are the author of your commits. Don't add AI co-author trailers or "Generated with"
lines; the PR rules check refuses them.

## License

By contributing, you agree that your contribution is licensed under the
[MIT license](../LICENSE) of this repository.

Please follow the [code of conduct](CODE_OF_CONDUCT.md).
