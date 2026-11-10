---
applyTo: "**/*.py,**/requirements*.in,**/requirements*.lock,ruff.toml,.python-version"
---

# Python

- **Version:** `.python-version` (3.13) for the local `.venv`, CI and images.
- **Environment:** always the project's `.venv` (`py -3.13 -m venv .venv`, then
  `.venv\Scripts\python -m pip install --require-hashes -r requirements-dev.lock`), never the
  system Python.
- **Layout:** code in `src/<package>/`, tests in `tests/` (pytest), tooling in `scripts/`;
  requirements files, `ruff.toml` and `.python-version` at the root. `tests/conftest.py` puts
  `src/` on the import path (`sys.path.insert`), so the tests import the code as it runs.
- **Dependencies:** direct dependencies in `requirements.in` (runtime) and
  `requirements-dev.in` (starts with `-r requirements.in`, then ruff, pytest, …). Never edit
  the `.lock` files: run `python scripts/lock_requirements.py`, which pins every package with
  sha256 hashes through the approved feed and keeps only releases at least 7 days old.
- **Lint and format:** `ruff check` and `ruff format` (settings in `ruff.toml`); CI runs both.
- **Tests:** pytest, offline (stub brokers and network clients, fixed seeds and clocks). A bug
  fix comes with a regression test.
- **Logging:** the `logging` module with standard levels only; never `print` for diagnostics.
- **Config:** read environment variables in one module; everything else receives settings.
