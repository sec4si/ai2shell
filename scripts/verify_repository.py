"""Read-only publication checks; never executes experiments or model tools.

Checks Python syntax, JSON, Markdown links, upstream snapshot hashes,
evidence checksums, and eligible Git files for accidental secrets/build output.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from data_manifest import MANIFEST, ROOT, collect

sys.path.insert(0, str(ROOT / "probes"))
from study_scope import ALLOWED_DIALECTS, MARKER_KEYS, input_in_scope, model_in_scope

SECRET_PATTERNS = {
    "provider_token": re.compile(r"(?<![\w-])(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "private_gateway": re.compile(r"https?://192\.168\.\d+\.\d+(?::\d+)?"),
}


def scope_errors(value, location):
    """Check subject fields and saved inputs, without editing model outputs."""
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            field = location + "/" + key
            if key in ("dialect", "actual_dialect") and isinstance(child, str):
                if child.split(" ", 1)[0] not in (*ALLOWED_DIALECTS, *MARKER_KEYS):
                    errors.append(f"Out-of-scope dialect: {field}")
            if key in ("model", "outer_model") and isinstance(child, str) and not model_in_scope(child):
                errors.append(f"Out-of-scope model: {field}")
            if key == "input" and isinstance(child, str) and not input_in_scope(child):
                errors.append(f"Out-of-scope mixed input: {field}")
            if key == "chunks" and isinstance(child, list) and all(isinstance(v, str) for v in child):
                if not input_in_scope("".join(child)):
                    errors.append(f"Out-of-scope mixed input: {field}")
            errors.extend(scope_errors(child, field))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(scope_errors(child, f"{location}/{index}"))
    return errors


def candidates():
    if (ROOT / ".git").is_dir():
        result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
                                 "--exclude-standard", "-z"], check=True, capture_output=True)
        return sorted({ROOT / p.decode("utf-8") for p in result.stdout.split(b"\0") if p})
    paths = []
    ignored = {".git", ".local", ".tools", ".venv", ".infra-venv",
               "__pycache__", "build", "target", "archive"}
    for folder, dirs, files in os.walk(ROOT, followlinks=False):
        retained = []
        for name in dirs:
            entry = Path(folder) / name
            if name in ignored or entry.is_symlink():
                continue
            # Windows junctions are reparse points even when is_symlink() is false.
            attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
            if not attributes & 0x400:
                retained.append(name)
        dirs[:] = retained
        paths.extend(Path(folder) / name for name in files)
    return sorted(paths)


def main():
    errors, counts = [], {"python_files": 0, "json_files": 0, "markdown_links": 0, "source_hashes": 0}
    paths = candidates()
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or not path.is_file():
            errors.append(f"Non-file in publication set: {relative}")
            continue
        if any(p in relative.split("/") for p in (".venv", ".infra-venv", ".tools", ".local", "__pycache__")):
            errors.append(f"Local artifact eligible for Git: {relative}")
        if relative.startswith("probes/native/") and ("/target/" in relative or "/build/" in relative or path.suffix in (".exe", ".dll", ".a", ".rlib", ".rmeta")):
            errors.append(f"Native build artifact eligible for Git: {relative}")
        if path.stat().st_size >= 50 * 1024 * 1024:
            errors.append(f"File is at least 50 MiB: {relative}")
        if path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                counts["json_files"] += 1
                if relative.startswith("results/"):
                    errors.extend(scope_errors(data, relative))
            except (ValueError, UnicodeError) as exc:
                errors.append(f"Invalid JSON: {relative}: {exc}")
        if relative.startswith("sources/"):
            continue
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
                counts["python_files"] += 1
            except SyntaxError as exc:
                errors.append(f"Python syntax: {relative}:{exc.lineno}: {exc.msg}")
        if path.suffix in (".py", ".md", ".json", ".txt", ".toml", ".yml", ".yaml", ".log", ".example"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in SECRET_PATTERNS.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    errors.append(f"{label}: {relative}:{line} (value omitted)")
            if path.suffix == ".md":
                for target in re.findall(r"\]\(([^)]+)\)", text):
                    if target.startswith(("http:", "https:", "mailto:", "#", "data:")):
                        continue
                    bare = target.partition("#")[0].strip("<>")
                    if not (path.parent / bare).exists():
                        errors.append(f"Broken Markdown link: {relative} -> {target}")
                    counts["markdown_links"] += 1

    for manifest in sorted((ROOT / "sources").glob("*/snapshot.json")):
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        for name, info in saved.get("files", {}).items():
            expected = info.get("sha256") if isinstance(info, dict) else info
            path = manifest.parent / name
            counts["source_hashes"] += 1
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                errors.append(f"Upstream hash mismatch: {path.relative_to(ROOT).as_posix()}")
    for name in ("results", "impact_results"):
        saved = json.loads((ROOT / f"results/deepseek_vllm/{name}.json").read_text(encoding="utf-8"))
        for relative, expected in saved["source_sha256"].items():
            path = ROOT / "sources/vllm" / relative
            counts["source_hashes"] += 1
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                errors.append(f"Baseline source hash mismatch: {relative}")
    if not MANIFEST.is_file() or json.loads(MANIFEST.read_text(encoding="utf-8")) != collect():
        errors.append("Evidence checksum mismatch; review changes, then run scripts/data_manifest.py --write")
    result = {"ok": not errors, "eligible_git_files": len(paths), **counts, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
