"""Tests of the CI guard (P7-D2 fix D-F5; copied to tests/test_ci_guard.py by scripts/build_public_bundle.py, run on
ubuntu and windows by CI; the private repository runs the same tests through tests/test_p7d2.py).

Each case is a throw-away git repository: the files are added to the index (and committed for the history cases), then
the guard runs as CI runs it (a new Python process) and its exit code is compared.
    pass: a tree like the public repository (app/data/* is a normal file)
    fail: data/x.csv, outputs/a.xlsx, logs/a.log, x.duckdb, .env, sub/.env, a key name in a file; a data file that was
          committed and removed again (history); not a git repository (exit 2, never 0)
    the CI workflow has no `!` command line and runs the guard
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "app" / "Home.py").exists())   # tests/ (public) or docs/ci/
GUARD = next(p for p in (ROOT / ".github" / "ci_guard.py", ROOT / "docs" / "ci" / "ci_guard.py") if p.exists())
WORKFLOW = next(p for p in (ROOT / ".github" / "workflows" / "ci.yml", ROOT / "docs" / "ci" / "public-ci.yml") if p.exists())
KEY_TEXT = "DART" + "_API_" + "KEY=abc"          # written in pieces: this file must not be a hit itself
NORMAL = {"README.md": "# x\n", "app/Home.py": "x = 1\n", "app/data/meta.json": "{}\n", "app/public/index.json": "[]\n",
          "src/data_tools.py": "y = 2\n", "docs/demo/a.png": "png\n", ".github/workflows/ci.yml": "name: ci\n"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=repo, check=True,
                   capture_output=True)


def _repo(tmp: Path, files: dict[str, str]) -> Path:
    repo = tmp / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-f", "-A")             # -f: a global .gitignore of the machine must not hide the fake files
    return repo


def _guard(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GUARD), *args, str(repo)], capture_output=True, text=True)


def test_normal_tree_passes(tmp_path):
    r = _guard(_repo(tmp_path, NORMAL), "--history")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 found" in r.stdout


@pytest.mark.parametrize("rel,text", [
    ("data/x.csv", "a\n"), ("outputs/a.xlsx", "x\n"), ("logs/a.log", "x\n"), ("x.duckdb", "x\n"),
    ("sub/deep/y.DUCKDB", "x\n"), (".env", "x\n"), ("sub/.env", "x\n"), (".env.local", "x\n"),
    ("src/settings.py", KEY_TEXT + "\n"), ("app/data/notes.txt", "DATA_GO_KR" + "_KEY\n"),
])
def test_forbidden_file_fails(tmp_path, rel, text):
    r = _guard(_repo(tmp_path, {**NORMAL, rel: text}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"FOUND {rel}" in r.stdout


def test_removed_file_fails_on_history(tmp_path):
    repo = _repo(tmp_path, {**NORMAL, "data/x.csv": "a\n"})
    _git(repo, "commit", "-q", "-m", "a")
    _git(repo, "rm", "-q", "data/x.csv")
    _git(repo, "commit", "-q", "-m", "b")
    assert _guard(repo).returncode == 0                       # the tree is clean now
    r = _guard(repo, "--history")
    assert r.returncode == 1 and "data/x.csv" in r.stdout, r.stdout


def test_key_name_in_old_commit_fails_on_history(tmp_path):
    repo = _repo(tmp_path, {**NORMAL, "src/settings.py": KEY_TEXT + "\n"})
    _git(repo, "commit", "-q", "-m", "a")
    (repo / "src" / "settings.py").write_text("z = 0\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "b")
    assert _guard(repo).returncode == 0
    r = _guard(repo, "--history")
    assert r.returncode == 1 and "src/settings.py: key name" in r.stdout, r.stdout


def test_not_a_repository_does_not_pass(tmp_path):
    r = _guard(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr


def test_workflow_runs_the_guard_and_has_no_bang_line():
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    assert not [x for x in lines if x.strip().startswith("! ")]          # bash -e does not stop on a `!` command
    assert any("ci_guard.py --history" in x for x in lines)
