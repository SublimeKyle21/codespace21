#!/usr/bin/env python3
"""Lightweight filesystem scanner with optional local/OpenAI-compatible LLM reporting.

The tool is intentionally self-contained: it uses only Python's standard library and
can run from a single copied file. By default it performs deterministic local
analysis and never sends file contents to any model provider. If --llm is enabled,
only the generated summary/metadata is sent to the configured OpenAI-compatible
chat endpoint.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import fnmatch
import hashlib
import itertools
import json
import mimetypes
import os
import re
import stat
import sys
import textwrap
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

DEFAULT_EXCLUDES = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".DS_Store",
)

TEXT_EXTENSIONS = {
    ".bat",
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".dockerfile",
    ".env",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".log",
    ".lua",
    ".md",
    ".php",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

LANGUAGE_BY_EXTENSION = {
    ".bat": "Batch",
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript JSX",
    ".kt": "Kotlin",
    ".lua": "Lua",
    ".php": "PHP",
    ".pl": "Perl",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sh": "Shell",
    ".sql": "SQL",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript TSX",
}

SECRET_PATTERNS = (
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Private key marker", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "High-entropy assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{16,}['\"]?"
        ),
    ),
)

TODO_PATTERN = re.compile(r"(?m)^\s*(?:#|//|/\*|\*|<!--)?\s*\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
DEFAULT_REPORT_PATH = Path.home() / "codespace21" / "filesystem_audit.md"

DEPENDENCY_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "Dockerfile",
    "docker-compose.yml",
}


@dataclasses.dataclass(frozen=True)
class FileFinding:
    severity: str
    category: str
    path: str
    detail: str


@dataclasses.dataclass
class FileRecord:
    path: str
    size: int
    modified: float
    extension: str
    mime: str
    is_text: bool
    sha256: str | None = None
    lines: int | None = None
    findings: list[FileFinding] = dataclasses.field(default_factory=list)


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num_bytes} B"


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)) or "."
    except ValueError:
        return str(path)


def should_exclude(path: Path, root: Path, patterns: Iterable[str]) -> bool:
    rel = safe_relative(path, root)
    parts = set(path.parts)
    for pattern in patterns:
        if pattern in parts or fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel, pattern):
            return True
    return False


def looks_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    return bool(mime and mime.startswith("text/"))


def read_sample(path: Path, max_bytes: int) -> str:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes)
    except OSError:
        return ""
    if b"\x00" in data:
        return ""
    return data.decode("utf-8", errors="replace")


def file_hash(path: Path, max_size_for_hash: int) -> str | None:
    try:
        if path.stat().st_size > max_size_for_hash:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def analyze_file(path: Path, root: Path, args: argparse.Namespace) -> FileRecord | None:
    try:
        info = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None

    rel = safe_relative(path, root)
    ext = path.suffix.lower() or "[none]"
    mime = mimetypes.guess_type(str(path))[0] or "unknown"
    is_text = looks_text(path)
    record = FileRecord(path=rel, size=info.st_size, modified=info.st_mtime, extension=ext, mime=mime, is_text=is_text)

    if info.st_size >= args.large_file_bytes:
        record.findings.append(
            FileFinding("medium", "large-file", rel, f"Large file consumes {human_size(info.st_size)}.")
        )

    mode = info.st_mode
    if mode & stat.S_IWOTH:
        record.findings.append(
            FileFinding("high", "permissions", rel, "File is world-writable.")
        )

    if path.name in DEPENDENCY_FILES:
        record.findings.append(
            FileFinding("info", "dependency-manifest", rel, "Dependency/build manifest found.")
        )

    if is_text and info.st_size <= args.max_text_bytes:
        sample = read_sample(path, args.max_text_bytes)
        record.lines = sample.count("\n") + (1 if sample and not sample.endswith("\n") else 0)
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(sample):
                record.findings.append(
                    FileFinding("critical", "possible-secret", rel, f"Potential {label} detected; review before sharing.")
                )
        todo_count = len(TODO_PATTERN.findall(sample))
        if todo_count:
            record.findings.append(
                FileFinding("low", "maintenance-marker", rel, f"Contains {todo_count} TODO/FIXME/HACK marker(s).")
            )
    elif is_text:
        record.findings.append(
            FileFinding("low", "skipped-content", rel, f"Text content scan skipped above {human_size(args.max_text_bytes)}.")
        )

    if args.hash:
        record.sha256 = file_hash(path, args.max_hash_bytes)
    return record


def iter_files(root: Path, excludes: Iterable[str]) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if not should_exclude(current_path / d, root, excludes)]
        for filename in files:
            file_path = current_path / filename
            if not should_exclude(file_path, root, excludes):
                yield file_path


def scan(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    excludes = tuple(DEFAULT_EXCLUDES) + tuple(args.exclude or ())
    path_iter = iter_files(root, excludes)
    if args.limit:
        path_iter = itertools.islice(path_iter, args.limit)

    records: list[FileRecord] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for record in executor.map(lambda path: analyze_file(path, root, args), path_iter):
            if record:
                records.append(record)

    records.sort(key=lambda item: item.path)
    findings = [finding for record in records for finding in record.findings]
    severity_counts = Counter(finding.severity for finding in findings)
    ext_counts = Counter(record.extension for record in records)
    language_counts = Counter(
        LANGUAGE_BY_EXTENSION[record.extension]
        for record in records
        if record.extension in LANGUAGE_BY_EXTENSION
    )
    duplicate_groups: list[dict[str, Any]] = []
    if args.hash:
        by_hash: dict[str, list[FileRecord]] = defaultdict(list)
        for record in records:
            if record.sha256:
                by_hash[record.sha256].append(record)
        for digest, group in by_hash.items():
            if len(group) > 1:
                duplicate_groups.append(
                    {
                        "sha256": digest,
                        "size": group[0].size,
                        "paths": [record.path for record in group],
                    }
                )
                findings.append(
                    FileFinding("low", "duplicate-content", group[0].path, f"{len(group)} files share identical content.")
                )
    duplicate_groups.sort(key=lambda group: (-len(group["paths"]), -group["size"]))

    total_size = sum(record.size for record in records)
    oldest = min((record.modified for record in records), default=None)
    newest = max((record.modified for record in records), default=None)
    result = {
        "root": str(root),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duration_seconds": round(time.time() - started, 3),
        "limits": {
            "max_text_bytes": args.max_text_bytes,
            "large_file_bytes": args.large_file_bytes,
            "hashed": args.hash,
            "max_hash_bytes": args.max_hash_bytes if args.hash else None,
            "excluded": excludes,
        },
        "summary": {
            "files_scanned": len(records),
            "directories_seen": sum(1 for _ in root.rglob("*") if _.is_dir()) if args.count_dirs else None,
            "total_size_bytes": total_size,
            "total_size_human": human_size(total_size),
            "oldest_modified": dt.datetime.fromtimestamp(oldest, dt.timezone.utc).isoformat() if oldest else None,
            "newest_modified": dt.datetime.fromtimestamp(newest, dt.timezone.utc).isoformat() if newest else None,
            "findings_by_severity": dict(severity_counts),
            "top_extensions": ext_counts.most_common(12),
            "top_languages": language_counts.most_common(12),
        },
        "findings": [dataclasses.asdict(finding) for finding in sorted(findings, key=finding_sort_key)],
        "largest_files": [file_record_to_dict(record) for record in sorted(records, key=lambda item: item.size, reverse=True)[: args.top]],
        "duplicate_groups": duplicate_groups[: args.top],
    }
    return result


def finding_sort_key(finding: FileFinding) -> tuple[int, str, str]:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return (order.get(finding.severity, 9), finding.category, finding.path)


def file_record_to_dict(record: FileRecord) -> dict[str, Any]:
    return {
        "path": record.path,
        "size_bytes": record.size,
        "size_human": human_size(record.size),
        "modified": dt.datetime.fromtimestamp(record.modified, dt.timezone.utc).isoformat(),
        "extension": record.extension,
        "mime": record.mime,
        "lines": record.lines,
        "sha256": record.sha256,
    }


def render_markdown(report: dict[str, Any], llm_summary: str | None = None) -> str:
    summary = report["summary"]
    lines = [
        f"# Filesystem AI Audit Report",
        "",
        f"**Root:** `{report['root']}`",
        f"**Generated:** {report['generated_at']}",
        f"**Duration:** {report['duration_seconds']}s",
        "",
        "## Executive Summary",
        "",
        f"- Files scanned: **{summary['files_scanned']}**",
        f"- Total size: **{summary['total_size_human']}**",
        f"- Newest modified file timestamp: `{summary['newest_modified']}`",
        f"- Oldest modified file timestamp: `{summary['oldest_modified']}`",
        f"- Findings by severity: `{summary['findings_by_severity']}`",
    ]
    if llm_summary:
        lines.extend(["", "## AI Narrative", "", llm_summary.strip()])

    lines.extend(["", "## Top Languages", ""])
    if summary["top_languages"]:
        for language, count in summary["top_languages"]:
            lines.append(f"- {language}: {count} file(s)")
    else:
        lines.append("- No source language signatures detected.")

    lines.extend(["", "## Top Extensions", ""])
    for ext, count in summary["top_extensions"]:
        lines.append(f"- `{ext}`: {count} file(s)")

    lines.extend(["", "## Findings", ""])
    if report["findings"]:
        for finding in report["findings"][:50]:
            lines.append(
                f"- **{finding['severity'].upper()}** `{finding['category']}` in `{finding['path']}` — {finding['detail']}"
            )
        if len(report["findings"]) > 50:
            lines.append(f"- … {len(report['findings']) - 50} additional finding(s) omitted from Markdown view.")
    else:
        lines.append("- No notable findings detected with the enabled checks.")

    lines.extend(["", "## Largest Files", ""])
    for record in report["largest_files"]:
        lines.append(f"- `{record['path']}` — {record['size_human']} — modified {record['modified']}")

    if report["duplicate_groups"]:
        lines.extend(["", "## Duplicate Content", ""])
        for group in report["duplicate_groups"]:
            lines.append(f"- {len(group['paths'])} files, {human_size(group['size'])}: `{', '.join(group['paths'][:5])}`")

    lines.extend(
        [
            "",
            "## Privacy Notes",
            "",
            "- Local scanning uses deterministic rules and reads only bounded text samples for content checks.",
            "- LLM mode sends report metadata and findings, not raw file bodies, to the configured endpoint.",
        ]
    )
    return "\n".join(lines) + "\n"


def request_llm_summary(report: dict[str, Any], args: argparse.Namespace) -> str:
    endpoint = args.llm_endpoint or os.getenv("FS_AI_LLM_ENDPOINT") or "http://localhost:11434/v1/chat/completions"
    model = args.llm_model or os.getenv("FS_AI_LLM_MODEL") or "llama3.2"
    api_key = args.llm_api_key or os.getenv("FS_AI_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "ollama"
    compact_report = {
        "root": report["root"],
        "summary": report["summary"],
        "findings": report["findings"][: args.llm_finding_limit],
        "largest_files": report["largest_files"][: args.top],
        "duplicate_groups": report["duplicate_groups"][: args.top],
    }
    prompt = (
        "You are a concise filesystem audit assistant. Explain the most important risks, "
        "maintenance concerns, and next actions from this JSON report. Do not claim to have "
        "read raw file contents.\n\n"
        + json.dumps(compact_report, indent=2)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return a practical audit summary with prioritized bullets."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.llm_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return f"LLM summary unavailable: {exc}"
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return "LLM summary unavailable: endpoint returned an unexpected response shape."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-contained filesystem scanner with optional OpenAI-compatible LLM reporting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python fs_ai_auditor.py /home/me/project --output report.md
              python fs_ai_auditor.py . --json report.json --hash
              python fs_ai_auditor.py /mnt/drive --llm --llm-model llama3.2
              FS_AI_LLM_ENDPOINT=https://api.openai.com/v1/chat/completions \\
                FS_AI_LLM_MODEL=gpt-4.1-mini OPENAI_API_KEY=... \\
                python fs_ai_auditor.py . --llm
            """
        ),
    )
    parser.add_argument("root", nargs="?", default=".", help="Filesystem root to scan (default: current directory).")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT_PATH),
        help=f"Markdown report path (default: {DEFAULT_REPORT_PATH}).",
    )
    parser.add_argument("--json", dest="json_output", help="Optional JSON report path.")
    parser.add_argument("--exclude", action="append", default=[], help="Additional glob/name to exclude; may be repeated.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum files to scan after exclusions (0 = unlimited).")
    parser.add_argument("--top", type=int, default=15, help="Number of largest/duplicate groups to show.")
    parser.add_argument("--workers", type=int, default=min(32, (os.cpu_count() or 2) + 4), help="Concurrent file workers.")
    parser.add_argument("--max-text-bytes", type=int, default=512 * 1024, help="Maximum bytes read from each text file.")
    parser.add_argument("--large-file-bytes", type=int, default=50 * 1024 * 1024, help="Large file finding threshold.")
    parser.add_argument("--hash", action="store_true", help="Enable SHA-256 hashing for duplicate detection.")
    parser.add_argument("--max-hash-bytes", type=int, default=250 * 1024 * 1024, help="Skip hashing files above this size.")
    parser.add_argument("--count-dirs", action="store_true", help="Count directories in summary; disabled by default for speed.")
    parser.add_argument("--llm", action="store_true", help="Ask an OpenAI-compatible chat endpoint to summarize the local report.")
    parser.add_argument("--llm-endpoint", help="Chat completions endpoint; defaults to FS_AI_LLM_ENDPOINT or local Ollama.")
    parser.add_argument("--llm-model", help="Model name; defaults to FS_AI_LLM_MODEL or llama3.2.")
    parser.add_argument("--llm-api-key", help="API key; defaults to FS_AI_LLM_API_KEY, OPENAI_API_KEY, or 'ollama'.")
    parser.add_argument("--llm-timeout", type=int, default=60, help="LLM request timeout in seconds.")
    parser.add_argument("--llm-finding-limit", type=int, default=40, help="Maximum findings included in LLM prompt.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"Root does not exist: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"Root must be a directory: {root}", file=sys.stderr)
        return 2

    report = scan(root, args)
    llm_summary = request_llm_summary(report, args) if args.llm else None
    markdown = render_markdown(report, llm_summary)

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"Markdown report written to {output}")

    if args.json_output:
        json_output = Path(args.json_output).expanduser()
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report written to {json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
