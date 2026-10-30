"""Shared scope for published observations and experiment entry points."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MODELS = json.loads((ROOT / "specs/study_scope.json").read_text(encoding="utf-8"))["models"]
DIALECT_LABELS = {item["dialect"]: item["name"] for item in MODELS}
ALLOWED_DIALECTS = tuple(DIALECT_LABELS)
MODEL_NAMES = tuple(DIALECT_LABELS.values())
MARKER_KEYS = tuple(item["marker_key"] for item in MODELS)


def input_in_scope(text):
    """Exclude old mixed inputs rather than changing their recorded meaning."""
    return not any(marker in text for marker in (
        "<｜DSML｜function_calls>", "</｜DSML｜function_calls>", "<｜tool▁"))


def model_in_scope(model):
    normalized = model.lower().replace("_", "-")
    if normalized in {name.lower() for name in MODEL_NAMES}:
        return True
    if re.match(r"^deepseek-v4(?:[.-]1)?-(?:flash|pro)(?:-|$)", normalized):
        return True
    return normalized.startswith(("kimi-k2-", "kimi-k3-", "qwen-"))


def require_dialect(dialect):
    if dialect not in ALLOWED_DIALECTS:
        raise ValueError(f"Dialect is outside specs/study_scope.json: {dialect}")
