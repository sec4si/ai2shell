"""Write or verify a deterministic checksum manifest for published evidence.

Run from any directory. This never runs a parser, model, HTTP call or tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "results/manifest.json"


def collect():
    files = {}
    for path in sorted((ROOT / "results").rglob("*")):
        if not path.is_file() or path == MANIFEST:
            continue
        if path.suffix not in (".json", ".jsonl", ".log"):
            continue
        data = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        kind = ("derived" if "/exports/" in relative or "/audits/" in relative else
                "metadata" if path.parent == ROOT / "results" else "saved_observation")
        files[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "kind": kind}
    return {"format_version": 1,
            "scope": "Checksums attest file integrity, not the validity of experimental success flags.",
            "files": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Explicitly replace results/manifest.json")
    args = parser.parse_args()
    actual = collect()
    if args.write:
        MANIFEST.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        if not MANIFEST.is_file():
            raise SystemExit("Missing results/manifest.json; run scripts/data_manifest.py --write")
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if actual != expected:
            old, new = expected["files"], actual["files"]
            changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))
            raise SystemExit("Evidence manifest mismatch:\n" + "\n".join(changed))
    print(json.dumps({"manifest": MANIFEST.relative_to(ROOT).as_posix(),
                      "files": len(actual["files"]),
                      "bytes": sum(f["bytes"] for f in actual["files"].values()),
                      "action": "written" if args.write else "verified"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
