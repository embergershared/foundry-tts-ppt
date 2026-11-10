---
applyTo: "**/*.cs,**/*.csproj,**/*.props,**/*.targets,**/*.slnx,**/*.sln"
---

# .NET

- **SDK and target:** `global.json` pins the SDK (10.0.4xx, `rollForward: latestFeature`);
  `Directory.Build.props` sets `net10.0`, nullable, implicit usings, analyzers
  (`latest-recommended`) and code style enforced in the build. A project overrides only what it
  must.
- **Packages:** Central Package Management. Add a version once in `Directory.Packages.props`;
  projects use `<PackageReference Include="..." />` without a version. Restore only from the
  feed in `nuget.config`. A new version must be at least 7 days old.
- **Lock files:** commit every `packages.lock.json`. After changing a package, run
  `dotnet restore --force-evaluate` and commit the updated lock files; CI restores in locked
  mode and fails on a stale lock.
- **Format:** `dotnet format --verify-no-changes` runs in CI; run `dotnet format` before
  committing.
- **Layout:** the solution (`*.slnx`) at the root, projects in `src/<Project>/`, test projects
  in `tests/<Project>.Tests/`.
- **Tests:** xUnit, one test project per production project (`<Project>.Tests`). A bug fix
  comes with a regression test.
- **EF Core migrations:** only through `scripts/db/Invoke-EfMigration.ps1` (backup first, trial
  on a copy, rollback on failure). See `docs/database.md`.
- **Configuration and secrets:** options classes bound once at startup; secrets from
  user-secrets or environment variables, never `appsettings*.json`.
