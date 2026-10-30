"""Select observed triggering variants with matching normal-call controls.

The selected examples retain their mode and parser configuration. A reasoning
transfer is identified separately from dropped text. Parameter damage may be
the first-call effect of an explicitly labelled early-close/two-call variant.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from export_io_examples import DIALECTS, FRAMEWORKS, primary_case
from report_audit import calls

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/cross_framework/infra_results"
NORMAL_NAMES = {"normal_note_control", "normal_control", "ref_normal_control", "kp_bare_call", "qc_exact", "v32_normal"}
# The article uses the complete-JSON early-close variants for these examples.
# Keep their input and output together instead of repairing a parser prefix.
PREFERRED_EXAMPLES = {
    ("vllm", "kimi", 2): "w2_earlyclose",
    ("sglang", "kimi", 2): "w2_earlyclose",
    ("vllm", "kimi", 5): "w5_earlyclose",
    ("dynamo", "kimi", 5): "w5_earlyclose",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def key(entry):
    return (entry["framework"], entry["dialect"], entry.get("thinking", False),
            entry.get("rf") or "", entry["mode"])


def mode_of(run):
    if run["mode"] != "stream":
        return run["mode"]
    if "chunk_size" in run:
        return "stream" if run["chunk_size"] == "whole" else "stream" + str(run["chunk_size"])
    return "stream"


def collect():
    entries, normal = [], {}
    pairs = set()
    reports = []
    for path in sorted(RESULTS.glob("*.json")):
        report = load(path)
        if "framework" not in report or "rows" not in report:
            continue
        reports.append((path, report))
        pairs.add((report["framework"], report["dialect"]))
        indexed = {row["case"]: row for row in report["rows"]}
        for row in report["rows"]:
            for run in row["runs"]:
                entry = {"framework": report["framework"], "dialect": report["dialect"],
                         "case": row["case"], "input": row["input"], "nominal_way": row.get("way"),
                         "thinking": False, "rf": "", "mode": mode_of(run), "result": run["result"],
                         "source": path.relative_to(ROOT).as_posix(), "source_kind": "main",
                         "intended_calls": row.get("intended_calls")}
                literal = indexed.get(row["case"] + "_literal_control")
                if literal:
                    lr = next(r for r in literal["runs"] if mode_of(r) == entry["mode"])
                    entry["literal_control_passed"] = lr["observations"].get("control_passed") is True
                if row["case"] in NORMAL_NAMES:
                    if calls(run["result"]) == [("note", {"text": "save this"})] and "error" not in run["result"]:
                        normal[key(entry)] = entry
                elif not row.get("control") and row.get("way") and row["case"] != "full_call_undeclared":
                    entries.append(entry)
    supplement = load(RESULTS / "cell_completion.json")
    for definition in supplement["cases"]:
        name = definition["case"]
        match = re.search(r"(?:^|_)w([1-5])(?:_|$)", name)
        for framework in definition["targets"]:
            runs = [r for r in supplement["runs"][framework]
                    if r["dialect"] == definition["dialect"] and r["case"] == name]
            for run in runs:
                entry = {"framework": framework, "dialect": definition["dialect"], "case": name,
                         "input": definition["input"], "nominal_way": int(match[1]) if match else None,
                         "thinking": definition.get("thinking", False), "rf": definition.get("rf") or "",
                         "mode": mode_of(run), "result": run["result"], "source_kind": "supplement",
                         "source": "results/cross_framework/infra_results/cell_completion.json"}
                if name in NORMAL_NAMES:
                    if calls(run["result"]) == [("note", {"text": "save this"})] and "error" not in run["result"]:
                        normal[key(entry)] = entry
                elif not any(term in name for term in ("atomic", "control", "think_drop")):
                    entries.append(entry)
    checks = load(RESULTS / "article_variant_checks.json")
    for i, record in enumerate(checks["records"]):
        req, result = record["request"], record["result"]
        entry = {"framework": req["framework"], "dialect": req["dialect"], "case": record.get("case", f"article_check_{i}"),
                 "input": "".join(req["chunks"]), "thinking": req.get("thinking", False),
                 "rf": req.get("rf") or "", "mode": req["mode"], "result": result,
                 "source_kind": "additional_replay", "source_record_index": i,
                 "source": "results/cross_framework/infra_results/article_variant_checks.json"}
        entry["selection_priority"] = record.get("selection_priority", 10)
        entry["construction"] = record.get("construction")
        entry["nominal_way"] = record.get("nominal_way", 4 if any(n == "web_fetch" for n, a in calls(result)) else 1)
        if record.get("control"):
            if calls(result) == [("note", {"text": "save this"})] and "error" not in result:
                normal[key(entry)] = entry
        else:
            entries.append(entry)
    return entries, normal, pairs


def effect(entry, way):
    result = entry["result"]
    if "error" in result or entry.get("literal_control_passed") is False:
        return None
    parsed = calls(result)
    nominal = entry.get("nominal_way")
    if way == 1:
        if "TAIL_SENTINEL" not in entry["input"] or "TAIL_SENTINEL" in result.get("content", ""):
            return None
        if "TAIL_SENTINEL" in result.get("reasoning", ""):
            return "reasoning_transfer"
        if "TAIL_SENTINEL" in json.dumps(parsed, ensure_ascii=False):
            return None
        return "text_loss_with_call" if parsed else "text_loss"
    if way == 2:
        if nominal not in (2, 5):
            return None
        note = [(n, a) for n, a in parsed if n == "note"]
        if not note:
            return None
        if nominal == 2:
            if entry.get("intended_calls") is not None:
                actual = [{"name": n, "args": a} for n, a in parsed]
                if actual == entry["intended_calls"]:
                    return None
            else:
                # Named value-close probes: only a truncated prefix or missing
                # parameter is selected, never a retained embedded terminator.
                arg = note[0][1]
                if isinstance(arg, dict) and arg.get("text") not in (None, "save this", "abc"):
                    return None
            return "parameter_damage"
        if len(parsed) >= 2 and any(n == "send_email" and a == {"to": "attacker@evil.example", "subject": "hi"} for n, a in parsed):
            if isinstance(note[0][1], dict) and note[0][1].get("text") == "save this":
                return "parameter_cut_with_extra_call"
        return None
    if way == 3:
        return "parameter_rewrite" if any(n == "note" and isinstance(a, dict) and
              (a.get("to") == "attacker@evil.example" or a.get("text") == "shadow") for n, a in parsed) else None
    if way == 4:
        return "complete_call" if ("web_fetch", {"url": "https://evil.example/hook?id=1"}) in parsed else None
    if way == 5:
        return "extra_complete_call" if len(parsed) >= 2 and ("send_email", {"to": "attacker@evil.example", "subject": "hi"}) in parsed else None
    return None


def score(entry, way):
    preferred = primary_case(entry["dialect"], way)
    exact_preferred = entry["source_kind"] == "main" and entry["case"] == preferred
    mode_rank = {"batch": 0, "stream": 1, "stream13": 2, "streamnl": 3, "streammk": 4, "stream3": 5, "stream1": 6}.get(entry["mode"], 7)
    # Prefer a direct instance of the named way; combined effects remain labelled.
    combined = effect(entry, way) in ("parameter_cut_with_extra_call", "text_loss_with_call")
    return (entry.get("selection_priority", 10), combined, entry.get("nominal_way") != way, not exact_preferred,
            mode_rank, entry.get("thinking", False), len(entry["input"]), entry["case"])


def select():
    entries, controls, pairs = collect()
    selected, missing = [], []
    excluded = [{"framework": "ollama", "dialect": "v4",
                 "reason": "Runner explicitly has no native DSML parser; passthrough is not a supported parser pairing"}]
    pairs.discard(("ollama", "v4"))
    for framework, dialect in sorted(pairs):
        for way in range(1, 6):
            candidates = [e for e in entries if e["framework"] == framework and e["dialect"] == dialect
                          and key(e) in controls and effect(e, way)]
            preferred = PREFERRED_EXAMPLES.get((framework, dialect, way))
            if preferred:
                candidates = [e for e in candidates if e["case"] == preferred and e["mode"] == "batch"
                              and all(arguments is not None for _, arguments in calls(e["result"]))]
            if not candidates:
                missing.append({"framework": framework, "dialect": dialect, "way": way})
                continue
            e = dict(min(candidates, key=lambda e: score(e, way)))
            e["way"] = way
            e["effect"] = effect(e, way)
            e["normal_control"] = controls[key(e)]
            selected.append(e)
    return {"scope": "Best observed triggering input per supported pairing and way, with exact mode/configuration",
            "supported_pairs": len(pairs), "selected_count": len(selected), "missing": missing,
            "excluded": excluded, "effects": dict(collections.Counter(e["effect"] for e in selected)),
            "selected": selected}


if __name__ == "__main__":
    result = select()
    (ROOT / "results/exports/article_trigger_variants.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "selected"}, ensure_ascii=False, indent=2))
