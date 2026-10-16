"""Offline engineering-document checks. Never contacts devices or paid services."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "SECURITY.md", "CHANGELOG.md",
    "docs/ENGINEERING_STANDARD.md", "docs/ARCHITECTURE.md",
    "docs/DECISIONS.md", "docs/VALIDATION.md", "docs/ROADMAP.md",
    "docs/RELEASING.md",
]
TEXT = {".md", ".py", ".h", ".ino", ".cpp", ".js", ".mjs", ".json",
        ".yml", ".yaml", ".txt", ".csv", ".html", ".css", ".bat", ".ini"}
# Limited preflight, not a complete security audit.
PATTERNS = [
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"\bIGAA[A-Za-z0-9]{40,}"),
    re.compile(r"""(?im)^\s*(?:const\s+char\s*\*\s*)?(?:[A-Za-z_]*(?:api_key|app_secret|password|wifi_pass|secret_key|access_token))\s*=\s*["'](?!(?:YOUR_|REPLACE_|EXAMPLE_|PLACEHOLDER|<))[^"'\r\n]{4,}["']"""),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
HTML = re.compile(r"(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]", re.I)
FENCE = chr(96) * 3


def paths():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True, check=True,
    )
    return sorted(set(p for p in result.stdout.decode("utf-8").split("\0") if p))


def main():
    errors = []
    links = 0
    files = paths()
    for required in REQUIRED:
        path = ROOT / required
        if not path.is_file() or len(path.read_text(encoding="utf-8").strip()) < 100:
            errors.append("Missing/substantively empty document: " + required)
    for name in files:
        path = ROOT / name
        if path.name in {".env", "secrets.h", "credentials.h"}:
            errors.append("Private configuration must not be tracked: " + name)
        if not path.is_file() or path.suffix.lower() not in TEXT:
            continue
        content = path.read_text(encoding="utf-8-sig")
        for pattern in PATTERNS:
            if pattern.search(content):
                errors.append("Possible sensitive value; inspect privately: " + name)
                break
        if path.suffix.lower() != ".md":
            continue
        fences = re.findall(r"^\s*(" + re.escape(chr(96)) + r"{3,}|~{3,})", content, re.M)
        if len(fences) % 2:
            errors.append("Unbalanced code fence: " + name)
        prose = re.sub(re.escape(FENCE) + r".*?" + re.escape(FENCE), "", content, flags=re.S)
        targets = [m.group(1).strip("<>") for m in LINK.finditer(prose)]
        targets += HTML.findall(prose)
        for target in targets:
            if urlsplit(target).scheme or target.startswith(("#", "//")):
                continue
            local = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not local:
                continue
            resolved = (path.parent / local).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or not resolved.exists():
                errors.append("Missing/outside-root link in " + name + ": " + local)
            else:
                links += 1
    arch = ROOT / "docs/ARCHITECTURE.md"
    if arch.is_file() and FENCE + "mermaid" not in arch.read_text(encoding="utf-8"):
        errors.append("Architecture diagram missing")
    for required in REQUIRED:
        if required == "README.md":
            continue
        path = ROOT / required
        if path.exists() and re.search(r"[\u0600-\u06ff]", path.read_text(encoding="utf-8")):
            errors.append("New public technical document is not English: " + required)
    if errors:
        for error in errors:
            print("FAIL: " + error)
        raise SystemExit(1)
    print("PASS: " + str(len(REQUIRED)) + " required documents; " + str(links)
          + " existing local links; bounded credential-pattern preflight.")
    print("Not a hardware test, full secret audit, external-link check or Markdown renderer.")


if __name__ == "__main__":
    main()
