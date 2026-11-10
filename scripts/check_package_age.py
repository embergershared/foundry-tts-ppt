"""Check every locked package version against the package age gate (default: 7 days).

Reads the lock files tracked in the repository and fails (exit 1) when a locked version was
published less than --min-age-days ago, is yanked (PyPI), or can't be verified:
  - Python: requirements*.lock (pins `name==version` with sha256 hashes), checked on pypi.org:
    upload time of the newest file, yank flag, and the lock's hashes against PyPI's.
  - NuGet: every packages.lock.json (Direct, Transitive and CentralTransitive dependencies),
    checked on the nuget.org registration (publish date).
CI runs it on every push and PR (.github/workflows/ci.yml, job "Package age gate"); it needs
only the standard library and network access to pypi.org and api.nuget.org. Where nuget.org is
blocked, --nuget-registration can point at the approved feed's registration resource instead.
Its publish dates are when the feed first cached each package, never earlier than nuget.org's:
the gate only gets stricter, and fails for packages the feed cached in the last days.

An exception (e.g. an urgent security fix) goes in scripts/package-age-allow.txt, one per line
with a reason:  pypi:requests==2.99.0  # CVE-2026-1234, fix needed before the gate
"""

import argparse
import datetime as dt
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW_FILE = os.path.join("scripts", "package-age-allow.txt")
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")
NUGET_REGISTRATION = "https://api.nuget.org/v3/registration5-gz-semver2"
GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"


def tracked(*patterns: str) -> list[str]:
    """Files tracked by git that match the patterns (also in subfolders)."""
    out = subprocess.run(
        ["git", "ls-files", "--", *patterns], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return sorted({line for line in out.splitlines() if line})


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=30) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
    return json.loads(body)


def python_pins(lock: str) -> dict:
    """{(name, version): set of sha256 hashes} of a requirements lock."""
    pins, current = {}, None
    with open(os.path.join(ROOT, lock), encoding="utf-8") as f:
        for line in f:
            m = PIN.match(line)
            if m:
                current = (m.group(1), m.group(2))
                pins[current] = set()
            elif "--hash=sha256:" in line and current:
                pins[current].add(line.split("--hash=sha256:")[1].split()[0])
    return pins


def nuget_pins(lock: str) -> set:
    """{(id, version)} of the packages (not projects) in a packages.lock.json."""
    with open(os.path.join(ROOT, lock), encoding="utf-8-sig") as f:
        data = json.load(f)
    pins = set()
    for deps in data.get("dependencies", {}).values():
        for name, info in deps.items():
            if info.get("type") != "Project" and info.get("resolved"):
                pins.add((name, info["resolved"]))
    return pins


def check_pypi(pin: tuple, hashes: set) -> dict:
    name, version = pin
    files = fetch_json(f"https://pypi.org/pypi/{name}/{version}/json")["urls"]
    if not files:
        return {"published": None, "problem": "no files on pypi.org"}
    problem = ""
    if any(f.get("yanked") for f in files):
        problem = "yanked"
    elif hashes and not hashes <= {f["digests"]["sha256"] for f in files}:
        problem = "sha256 hashes in the lock are not PyPI's"
    return {"published": max(f["upload_time_iso_8601"] for f in files), "problem": problem}


def check_nuget(pin: tuple, registration: str) -> dict:
    name, version = pin
    leaf = fetch_json(f"{registration.rstrip('/')}/{name.lower()}/{version.lower()}.json")
    published = leaf.get("published", "")
    # nuget.org marks unlisted packages with a 1900 publish date.
    if published.startswith("1900"):
        return {"published": None, "problem": "unlisted on nuget.org"}
    return {"published": published, "problem": ""}


def allowed() -> set:
    path = os.path.join(ROOT, ALLOW_FILE)
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.split("#")[0].strip().lower() for line in f if line.split("#")[0].strip()}


def report(kind: str, pin: tuple, message: str) -> None:
    text = f"{kind} {pin[0]} {pin[1]}: {message}"
    print(f"::error::{text}" if GITHUB else f"FAIL  {text}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-age-days", type=float, default=7)
    ap.add_argument(
        "--nuget-registration",
        default=NUGET_REGISTRATION,
        help="NuGet registration base URL (default: nuget.org)",
    )
    args = ap.parse_args()
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(days=args.min_age_days)
    allow = allowed()

    checks = []  # (kind, pin, function, extra args)
    py_locks, nuget_locks = (
        tracked("requirements*.lock", "**/requirements*.lock"),
        tracked("packages.lock.json", "**/packages.lock.json"),
    )
    for lock in py_locks:
        for pin, hashes in python_pins(lock).items():
            checks.append(("pypi", pin, check_pypi, (pin, hashes)))
    for lock in nuget_locks:
        for pin in sorted(nuget_pins(lock)):
            checks.append(("nuget", pin, check_nuget, (pin, args.nuget_registration)))
    unique = {(kind, pin): (fn, extra) for kind, pin, fn, extra in checks}
    print(f"Lock files : {', '.join(py_locks + nuget_locks) or 'none'}")
    print(f"Gate       : published before {cutoff:%Y-%m-%d %H:%M}Z ({args.min_age_days:g} days)")
    if not unique:
        print("No locked packages to check.")
        return 0

    def run(item):
        (kind, pin), (fn, extra) = item
        try:
            return kind, pin, fn(*extra)
        except (OSError, urllib.error.URLError, KeyError, ValueError) as e:
            return kind, pin, {"published": None, "problem": f"cannot verify ({e})"}

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(run, unique.items()))

    failures = 0
    for kind, pin, result in sorted(results, key=lambda r: (r[0], r[1][0].lower())):
        key = f"{kind}:{pin[0]}=={pin[1]}".lower()
        published = result["published"]
        problem = result["problem"]
        if not problem and published:
            when = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
            if when > cutoff:
                age = (now - when).total_seconds() / 86400
                problem = f"published {when:%Y-%m-%d} ({age:.1f} days ago), newer than the gate"
        if problem and key in allow:
            print(f"ALLOW {kind} {pin[0]} {pin[1]}: {problem} (listed in {ALLOW_FILE})")
        elif problem:
            report(kind, pin, problem)
            failures += 1
    print(f"Checked {len(results)} packages: {failures} failing the gate")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
