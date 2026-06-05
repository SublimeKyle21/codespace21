# Lightweight Filesystem AI Auditor

This repository includes a self-contained Python command-line tool, `fs_ai_auditor.py`, that can be copied onto almost any machine with Python 3.9+ and launched without installing dependencies.

It scans a filesystem root, analyzes metadata and bounded text samples, and produces Markdown/JSON reports. It can also call any OpenAI-compatible chat-completions endpoint, including local Ollama-compatible endpoints, to generate an AI narrative over the local report.

## Quick start

```bash
python fs_ai_auditor.py /path/to/scan --output audit.md
```

Optional JSON output and duplicate detection:

```bash
python fs_ai_auditor.py . --json audit.json --hash
```

Optional local LLM summary through an OpenAI-compatible endpoint:

```bash
python fs_ai_auditor.py . --llm --llm-endpoint http://localhost:11434/v1/chat/completions --llm-model llama3.2
```

Optional hosted OpenAI-compatible endpoint:

```bash
FS_AI_LLM_ENDPOINT=https://api.openai.com/v1/chat/completions \
FS_AI_LLM_MODEL=gpt-4.1-mini \
OPENAI_API_KEY=your_key \
python fs_ai_auditor.py . --llm
```

## What it reports

- File counts, total size, extension mix, and language signatures.
- Large files, dependency/build manifests, world-writable files, and duplicate content when hashing is enabled.
- Possible secrets using conservative regex checks for tokens, private-key markers, and high-entropy credential assignments.
- Maintenance markers such as `TODO`, `FIXME`, `HACK`, and `XXX`.
- Largest files and optional duplicate groups.

## Privacy model

- Default mode is fully local and deterministic.
- The scanner reads only bounded samples from text-like files for content checks.
- LLM mode sends report metadata and findings, not raw file bodies, to the configured endpoint.
- Use `--exclude` to prevent scanning sensitive folders, and review generated reports before sharing them.

## Useful options

```text
--exclude PATTERN        Add an exclusion by name or glob; repeat as needed.
--limit N               Stop after N candidate files for fast sampling.
--hash                  Compute SHA-256 hashes for duplicate detection.
--max-text-bytes N      Maximum bytes read from each text file.
--large-file-bytes N    Threshold for large-file findings.
--json PATH             Write machine-readable report JSON.
--llm                   Request an AI narrative from an OpenAI-compatible chat endpoint.
```

The tool intentionally depends only on the Python standard library so it is easy to launch on desktops, servers, removable drives, containers, and embedded Linux systems that have Python available.
