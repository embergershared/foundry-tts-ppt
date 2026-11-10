"""Lock requirements*.in into requirements*.lock: exact pins, sha256 hashes, 7-day age gate.

Each requirements<suffix>.in at the repository root is resolved into requirements<suffix>.lock
(requirements.in -> requirements.lock, requirements-dev.in -> requirements-dev.lock). The
.venv, CI and images install a lock with `pip install --require-hashes -r <lock>`: every
package, direct or indirect, at an exact version with its sha256 hashes. A lock is resolved
for every platform (Windows workstations, Linux CI runners and images; platform-only packages
carry a marker) and the Python of .python-version:

    uv pip compile requirements.in --generate-hashes --universal --python-version <.python-version>

through the index this computer's pip uses (PIP_INDEX_URL, else the pip configuration, which
points at the approved feed https://packagefeedproxy.microsoft.io/pypi/simple/). Then each
pinned release is checked on pypi.org, the source of truth (a proxy may lack upload dates or
yank flags):
  - at least --min-age-days old (default 7: every file uploaded 7 days ago or earlier);
  - not yanked;
  - same sha256 hashes as PyPI.
A release that is too new or yanked is excluded (`name<version` or `name!=version`) and the
locks resolved again. md5 hashes, which a proxy lists next to sha256 and pip refuses in
--hash, are removed. Finally every package named in a .in file must be pinned in its lock.

Needs uv (`pip install uv` into the project's .venv) and access to pypi.org
(`--skip-pypi-check` skips the checks above, with a warning). Run from the repository root
with the project's environment:
    .venv\\Scripts\\python scripts/lock_requirements.py
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRONG = ("sha256", "sha384", "sha512")  # the only algorithms pip's --hash accepts
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)")
COMMAND = "python scripts/lock_requirements.py"


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_version() -> str:
    with open(os.path.join(ROOT, ".python-version"), encoding="utf-8") as f:
        return f.read().strip()


def pip_index() -> tuple[str, str]:
    """(index URL, where it came from); ("", ...) = public PyPI."""
    if os.environ.get("PIP_INDEX_URL"):
        return os.environ["PIP_INDEX_URL"], "PIP_INDEX_URL environment variable"
    try:  # `pip config list` reads every pip.ini / pip.conf (`config get` misses global files)
        listed = subprocess.run(
            [sys.executable, "-m", "pip", "config", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        listed = ""
    m = re.search(r"^([\w:.-]+)\.index-url='([^']+)'", listed, flags=re.M)
    if m:
        return m.group(2), f"pip configuration ({m.group(1)}.index-url)"
    return "", "no pip index configured"


def uv_command() -> list[str]:
    if shutil.which("uv"):
        return ["uv"]
    probe = subprocess.run([sys.executable, "-m", "uv", "--version"], capture_output=True)
    if probe.returncode == 0:
        return [sys.executable, "-m", "uv"]
    sys.exit("uv not found: install it into the project's .venv (pip install uv) and run again")


def tidy(text: str) -> str:
    """Drop md5 hashes (keeping the line continuations right) and the temporary -c notes."""
    out, hashes, notes = [], [], None

    def flush():
        nonlocal notes
        kept = [h.rstrip(" \\") for h in hashes if h.split("--hash=")[1].split(":")[0] in STRONG]
        out.extend(h + (" \\" if i < len(kept) - 1 else "") for i, h in enumerate(kept))
        hashes.clear()
        if notes is not None:  # "# via" + "#   <source>" lines
            notes = [n for n in notes if not n.startswith("-c ")]
            if len(notes) == 1:
                out.append(f"    # via {notes[0]}")
            elif notes:
                out.extend(["    # via"] + [f"    #   {n}" for n in notes])
            notes = None

    for line in text.splitlines():
        if line.strip().startswith("--hash="):
            hashes.append(line)
        elif line == "    # via":
            flush()
            notes = []
        elif notes is not None and line.startswith("    #   "):
            notes.append(line[len("    #   ") :])
        elif line.startswith("    # via -c "):
            flush()
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out) + "\n"


def pins_of(text: str) -> dict:
    """{(name, version): set of sha256 hashes} of a lock."""
    pins, current = {}, None
    for line in text.splitlines():
        m = PIN.match(line)
        if m:
            current = (m.group(1), m.group(2))
            pins[current] = set()
        elif "--hash=sha256:" in line and current:
            pins[current].add(line.split("--hash=sha256:")[1].split()[0])
    return pins


def pypi_release(pin: tuple[str, str]) -> dict:
    """Upload time of the newest file, yank flag and sha256 hashes of one release on pypi.org."""
    name, version = pin
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as r:
        files = json.load(r)["urls"]
    return {
        "uploaded": max(f["upload_time_iso_8601"] for f in files),
        "yanked": any(f.get("yanked") for f in files),
        "sha256": {f["digests"]["sha256"] for f in files},
    }


def compile_lock(
    uv: list[str],
    source: str,
    target: list[str],
    index_args: list[str],
    excludes: list[str],
    tmp: str,
) -> str | None:
    """One `uv pip compile` with the exclusions as constraints; the tidied lock text, or None."""
    exclude_file = os.path.join(tmp, "excludes.txt")
    with open(exclude_file, "w", encoding="utf-8") as f:
        f.write("".join(e + "\n" for e in excludes))
    out = os.path.join(tmp, "out.lock")
    cmd = uv + [
        "pip",
        "compile",
        source,
        "-o",
        out,
        "--quiet",
        "--generate-hashes",
        "-c",
        exclude_file,
        "--custom-compile-command",
        COMMAND,
    ]
    if subprocess.run(cmd + target + index_args, cwd=ROOT).returncode:
        return None
    with open(out, encoding="utf-8") as f:
        return tidy(f.read())


def exclusions(pins: dict, known: dict, cutoff: str) -> list[str]:
    """Constraints that exclude the pinned releases that are yanked or too new on pypi.org."""
    todo = [p for p in pins if p not in known]
    with ThreadPoolExecutor(8) as ex:
        known.update(zip(todo, ex.map(pypi_release, todo), strict=True))
    rules = []
    for name, version in pins:
        release = known[(name, version)]
        too_new = release["uploaded"] >= cutoff
        reason = "yanked" if release["yanked"] else "too new" if too_new else ""
        if reason:
            rule = f"{name}!={version}" if reason == "yanked" else f"{name}<{version}"
            print(
                f"  excluded {name} {version} ({reason}, "
                f"uploaded {release['uploaded'][:10]}): {rule}"
            )
            rules.append(rule)
    return rules


def wanted_packages(source: str) -> set[str]:
    """Package names a .in file asks for, following its -r includes."""
    names = set()
    with open(os.path.join(ROOT, source), encoding="utf-8") as f:
        for raw in f:
            line = raw.split(" #")[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("-r ", "--requirement ")):
                names |= wanted_packages(line.split(None, 1)[1])
            elif not line.startswith("-"):
                names.add(norm(re.split(r"[<>=!~\[;\s@]", line, maxsplit=1)[0]))
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--min-age-days",
        type=float,
        default=7,
        help="pin only releases whose files are at least this many days old",
    )
    ap.add_argument(
        "--skip-pypi-check",
        action="store_true",
        help="no age / yank / hash check on pypi.org (not recommended)",
    )
    args = ap.parse_args()

    sources = sorted(
        os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "requirements*.in"))
    )
    if not sources:
        print("No requirements*.in at the repository root: nothing to lock")
        return 1
    uv = uv_command()
    target = ["--python-version", python_version(), "--universal"]
    index, origin = pip_index()
    index_args = ["--index-url", index] if index else []
    now = dt.datetime.now(dt.UTC)
    cutoff = (now - dt.timedelta(days=args.min_age_days)).strftime("%Y-%m-%dT%H:%M:%S")
    shown = re.sub(r"//[^/@]+@", "//***@", index) if index else "public PyPI"
    print(f"Package index: {shown}  ({origin})")
    print(f"Target       : Python {target[1]}, every platform (universal)")
    print(
        "Checks       : "
        + (
            "SKIPPED (--skip-pypi-check)"
            if args.skip_pypi_check
            else f"on pypi.org, files uploaded before {cutoff}Z, not yanked, same sha256"
        )
    )

    excludes, known, results = [], {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(10):
            results.clear()
            for source in sources:
                text = compile_lock(uv, source, target, index_args, excludes, tmp)
                if text is None:
                    print(f"uv pip compile failed for {source} (see above): no lock refreshed")
                    return 1
                results[source] = text
            if args.skip_pypi_check:
                break
            pins = {p: h for text in results.values() for p, h in pins_of(text).items()}
            try:
                new = exclusions(pins, known, cutoff)
            except OSError as e:
                print(f"cannot read pypi.org ({e}): no lock refreshed (--skip-pypi-check to skip)")
                return 1
            if not new:
                break
            excludes += new
        else:
            print("no acceptable resolution after 10 rounds: no lock refreshed")
            return 1

    problems = []
    for source, text in results.items():
        pins = pins_of(text)
        if not args.skip_pypi_check:
            problems += [
                f"{n}=={v}: sha256 hashes differ from PyPI's"
                for (n, v), h in pins.items()
                if h != known[(n, v)]["sha256"]
            ]
        pinned = {norm(n) for n, _ in pins}
        problems += [
            f"{name} from {source} is not pinned"
            for name in sorted(wanted_packages(source) - pinned)
        ]
        problems += [f"{n}=={v} has no sha256 hash" for (n, v), h in pins.items() if not h]
    for p in problems:
        print(f"PROBLEM: {p}")
    if problems:
        print("no lock refreshed")
        return 1
    for source, text in results.items():
        lock = source[: -len(".in")] + ".lock"
        with open(os.path.join(ROOT, lock), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"{lock}: {len(pins_of(text))} packages pinned with sha256 hashes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
