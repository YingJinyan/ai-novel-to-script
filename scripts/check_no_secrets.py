"""Fail when tracked files contain common secret material."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILENAMES = {".env", ".env.local", ".env.production", ".env.development"}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}\b"),
    "populated Qiniu key": re.compile(
        r"QINIU_AI_API_KEY\s*=\s*[\"']?[A-Za-z0-9._-]{16,}[\"']?"
    ),
}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    ).decode("utf-8")
    return [ROOT / item for item in output.split("\0") if item]


def main() -> int:
    problems: list[str] = []
    for path in tracked_files():
        if path.name in FORBIDDEN_FILENAMES:
            problems.append(f"tracked secret file: {path.relative_to(ROOT)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{label}: {path.relative_to(ROOT)}")

    if problems:
        print("Potential secrets found:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("No tracked secret material detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
