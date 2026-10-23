"""CI guard of the public repository (P7-D2 fix D-F5): fail when git tracks a data / DB / key file or a key name.

scripts/build_public_bundle.py copies this file to .github/ci_guard.py; the CI step runs it and its exit code decides:

    python .github/ci_guard.py [--history] [repo]

    exit 0  nothing found
    exit 1  something found (each hit is printed: path and why)
    exit 2  git failed (the guard could not look, so it does not pass)

Paths (the same rule as the bundle .gitignore, fix D-F4): the top-level folders data/, outputs/, logs/; a *.duckdb file
anywhere; a .env or .env.* file anywhere. app/data/* is a normal file and passes.
Key names: an upper-case word + "_API_" + "KEY", or the public data portal key name, in any tracked file (the pattern is
written in two pieces so that this file is not a hit itself).
--history: also every path and every file of every commit reachable from any ref (git log --all / git grep per commit).

Why: the step before was `! git ls-files | grep ...` followed by a second line. GitHub runs bash with -e, and bash does
not stop on a command that starts with `!`, so only the last line decided the step - a data file would have passed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

TOP = ("data", "outputs", "logs")
KEY = re.compile(rb"[A-Z][A-Z0-9]*_API_" + rb"KEY|DATA_GO_KR_" + rb"KEY")


class GitError(RuntimeError):
    pass


def forbidden(path: str) -> str | None:
    """Why a repository path must not be tracked, or None."""
    p = PurePosixPath(path.replace("\\", "/"))
    if p.parts and p.parts[0] in TOP:
        return f"top-level {p.parts[0]}/ folder"
    if p.name.lower().endswith(".duckdb"):
        return "DuckDB file"
    if p.name == ".env" or p.name.startswith(".env."):
        return "key file (.env)"
    return None


def git(repo: Path, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo, capture_output=True)
    if r.returncode not in ok:
        raise GitError(f"git {' '.join(args)} -> exit {r.returncode}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r


def _z(b: bytes) -> list[str]:
    return [x for x in b.decode("utf-8").split("\0") if x]


def check_tree(repo: Path) -> tuple[list[str], int]:
    """The index (what the next commit and the checkout hold): forbidden paths and key names in the files."""
    files = _z(git(repo, "ls-files", "-z").stdout)
    hits = [f"{f}: {why}" for f in files if (why := forbidden(f))]
    for f in files:
        p = repo / f
        if p.is_file() and KEY.search(p.read_bytes()):
            hits.append(f"{f}: key name in the file")
    return hits, len(files)


def check_history(repo: Path) -> tuple[list[str], int]:
    """Every commit reachable from any ref: every path it added or changed, and key names in its tree."""
    revs = git(repo, "rev-list", "--all").stdout.decode("utf-8").split()
    paths = _z(git(repo, "log", "--all", "--name-only", "--format=", "-z").stdout)
    hits = sorted({f"{f}: {why} (history)" for f in paths if (why := forbidden(f))})
    pat = KEY.pattern.decode("ascii")
    for rev in revs:
        r = git(repo, "grep", "-l", "-z", "-E", pat, rev, "--", ".", ok=(0, 1))  # 1 = no match
        hits += [f"{f.split(':', 1)[-1]}: key name (commit {rev[:7]})" for f in _z(r.stdout)]  # git prints <rev>:<path>
    return hits, len(revs)


def main(argv: list[str]) -> int:
    history = "--history" in argv
    rest = [a for a in argv if a != "--history"]
    repo = Path(rest[0]) if rest else Path.cwd()
    try:
        hits, n = check_tree(repo)
        msg = f"{n} tracked files"
        if history:
            h, nr = check_history(repo)
            hits += h
            msg += f", {nr} commits"
    except (GitError, OSError, UnicodeDecodeError) as e:
        print(f"ci_guard: could not check ({e})")
        return 2
    for h in hits:
        print(f"FOUND {h}")
    print(f"ci_guard: {msg} checked, {len(hits)} found")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
