"""Cross-check the supplied aggregate against complete saved batch records.

Read only source evidence. Writes a separate audit; never edits the aggregate.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_scope import ALLOWED_DIALECTS, DIALECT_LABELS, MODEL_NAMES, input_in_scope, model_in_scope, require_dialect


import collections
import hashlib
import json
from pathlib import Path

from report_audit import observed, calls

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "results/cross_framework/infra_results"
DIALECTS = {name: dialect for dialect, name in DIALECT_LABELS.items()}
WAY_CASES = {"way1_truncate": (1, "wrapper_only"), "way2_damage_call": (2, "invoke_close_in_string"),
             "way3_rewrite_params": (3, "add_parameter"), "way4_synth_call": (4, "full_call_in_prose"),
             "way5_append_call": (5, "extra_call_in_string")}
WAY_CASES.update({"way2_damage": WAY_CASES["way2_damage_call"],
                  "way3_rewrite": WAY_CASES["way3_rewrite_params"],
                  "way4_synth": WAY_CASES["way4_synth_call"],
                  "way5_append": WAY_CASES["way5_append_call"]})


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit():
    aggregate_path = ROOT / "results/exports/five_ways_evidence.json"
    aggregate_bytes = aggregate_path.read_bytes()
    aggregate = json.loads(aggregate_bytes)
    findings, rows, representation_changes = [], [], []
    variants = []
    used_pairs = set()
    from select_article_variants import collect
    candidates, _, _ = collect()

    def canonical(content, reasoning, tool_calls, error=None):
        normalized = []
        for call in tool_calls or []:
            arg = call.get("arguments")
            if isinstance(arg, str):
                try:
                    arg = json.loads(arg)
                except (ValueError, TypeError):
                    arg = {"invalid_json_raw": arg}
            normalized.append({"name": call.get("name"), "arguments": arg})
        return json.dumps({"content": content or "", "reasoning": reasoning or "",
                           "calls": normalized, "error": error or ""}, ensure_ascii=False, sort_keys=True)

    def check_variant(framework, model, label, entry):
        actual_dialect = entry.get("dialect", DIALECTS[model])
        actual_framework = entry.get("source_framework") or framework
        missing_input = not entry.get("input")
        target = canonical(entry.get("output_content"), entry.get("output_reasoning"),
                           entry.get("output_calls"), entry.get("error"))
        matches = []
        content_prefix_match = False
        for candidate in candidates:
            if candidate["framework"] != actual_framework or candidate["dialect"] != actual_dialect:
                continue
            if not missing_input and candidate["input"] != entry["input"]:
                continue
            result = candidate["result"]
            actual = canonical(result.get("content"), result.get("reasoning"), result.get("calls"), result.get("error"))
            if actual == target:
                matches.append(candidate)
            else:
                saved_content, raw_content = entry.get("output_content"), result.get("content", "")
                prefix = (isinstance(saved_content, str) and isinstance(raw_content, str)
                          and len(saved_content) in (100, 120) and len(raw_content) > len(saved_content)
                          and raw_content.startswith(saved_content))
                other_fields_match = canonical("", entry.get("output_reasoning"), entry.get("output_calls"), entry.get("error")) == canonical("", result.get("reasoning"), result.get("calls"), result.get("error"))
                if prefix and other_fields_match:
                    matches.append(candidate)
                    content_prefix_match = True
        record = {"outer_framework": framework, "outer_model": model, "variant_key": label,
                  "actual_framework": actual_framework, "actual_dialect": actual_dialect,
                  "input_missing": missing_input,
                  "dialect_differs_from_outer_model": actual_dialect != DIALECTS[model],
                  "framework_differs_from_outer_framework": actual_framework != framework,
                  "matching_observation_count": len(matches),
                  "output_content_is_truncated_prefix": content_prefix_match,
                  "matching_input_count": len({m["input"] for m in matches}),
                  "matches": [{"source": m["source"], "case": m["case"], "mode": m["mode"]} for m in matches]}
        variants.append(record)
        if missing_input:
            findings.append({"location": f"{framework}/{model}.{label}.input", "issue": "variant_input_missing"})
        if record["dialect_differs_from_outer_model"] or record["framework_differs_from_outer_framework"]:
            findings.append({"location": f"{framework}/{model}.{label}", "issue": "different_actual_parser_scope",
                             "actual_framework": actual_framework, "actual_dialect": actual_dialect})
        if not matches:
            findings.append({"location": f"{framework}/{model}.{label}", "issue": "variant_output_not_matched_to_saved_observation"})

    def compare(location, saved, original):
        if saved == original:
            return
        if isinstance(saved, str) and isinstance(original, str) and original.startswith(saved):
            findings.append({"location": location, "issue": "truncated_prefix",
                             "saved_length": len(saved), "original_length": len(original)})
        else:
            findings.append({"location": location, "issue": "value_mismatch",
                             "saved": saved, "original": original})

    def compare_output(location, record, result, literal=False):
        if str(record.get("output", "")).lower() == "error" or record.get("error"):
            compare(location + ".error", record.get("error") or record.get("detail"), result.get("error"))
            return
        ck, ak = ("content", "calls") if literal else ("output_content", "output_calls")
        compare(location + "." + ck, record.get(ck), result.get("content", ""))
        saved_calls, raw_calls = record.get(ak, []), result.get("calls", [])
        if len(saved_calls) != len(raw_calls):
            findings.append({"location": location + "." + ak, "issue": "call_count_mismatch",
                             "saved_count": len(saved_calls), "original_count": len(raw_calls)})
        for i, (saved, raw) in enumerate(zip(saved_calls, raw_calls)):
            for key in ("name", "arguments"):
                field_location = f"{location}.{ak}[{i}].{key}"
                saved_value, raw_value = saved.get(key), raw.get(key)
                if key == "arguments" and isinstance(saved_value, str) and isinstance(raw_value, (dict, list)):
                    representation_changes.append({"location": field_location,
                                                   "change": "JSON object serialized as a string"})
                    try:
                        if json.loads(saved_value) == raw_value:
                            continue
                    except (ValueError, TypeError):
                        pass
                    compare(field_location, saved_value, json.dumps(raw_value, ensure_ascii=False))
                else:
                    compare(field_location, saved_value, raw_value)

    for framework, models in aggregate.items():
        if framework == "metadata":
            continue
        for model, evidence in models.items():
            dialect = DIALECTS[model]
            pair = f"{framework}/{model}"
            used_pairs.add((framework, dialect))
            full = load(INFRA / f"{framework}_{dialect}.json")
            originals = {r["case"]: r for r in full["rows"]}
            normal = originals["normal_note_control"]
            nr = next(r for r in normal["runs"] if r["mode"] == "batch")
            normal_ok = "error" not in nr["result"] and [
                {"name": n, "args": a} for n, a in calls(nr["result"])] == normal["intended_calls"]
            compare(pair + ".normal_control.input", evidence["normal_control"]["input"], normal["input"])
            compare_output(pair + ".normal_control", evidence["normal_control"], nr["result"])
            for way_key, entry in evidence["ways"].items():
                if "__" in way_key:
                    check_variant(framework, model, way_key, entry)
                    continue
                way, name = WAY_CASES[way_key]
                original = originals[name]
                raw = next(r["result"] for r in original["runs"] if r["mode"] == "batch")
                location = pair + "." + way_key
                evidence_source = (INFRA / f"{framework}_{dialect}.json").relative_to(ROOT).as_posix()
                if entry["input"] != original["input"]:
                    corrected = [c for c in candidates if c["framework"] == framework and c["dialect"] == dialect
                                 and c["mode"] == "batch" and c["input"] == entry["input"]
                                 and c["source_kind"] == "additional_replay"]
                    if corrected:
                        chosen = corrected[-1]
                        original = {"case": chosen["case"], "input": chosen["input"], "way": way,
                                    "intended_calls": None}
                        raw = chosen["result"]
                        name = chosen["case"]
                        evidence_source = chosen["source"]
                compare(location + ".input", entry["input"], original["input"])
                compare_output(location, entry, raw)
                literal_ok = None
                if "literal_control" in entry:
                    control = originals[name + "_literal_control"]
                    cr = next(r for r in control["runs"] if r["mode"] == "batch")
                    literal_ok = cr["observations"].get("control_passed") is True and "error" not in cr["result"]
                    compare_output(location + ".literal_control", entry["literal_control"], cr["result"], literal=True)
                strict = normal_ok and literal_ok is not False and observed(original, raw)
                item = {"framework": framework, "model": model, "dialect": dialect,
                        "way": way, "original_case": name, "normal_control_passed": normal_ok,
                        "evidence_source": evidence_source,
                        "literal_control_passed": literal_ok, "saved_way_achieved": entry["way_achieved"],
                        "article_strict_criterion_met": strict,
                        "input_complete": entry["input"] == original["input"]}
                rows.append(item)
                if entry["way_achieved"] and not strict:
                    reason = ("normal_control_failed" if not normal_ok else
                              "literal_control_failed" if literal_ok is False else
                              "outcome_does_not_meet_article_criterion")
                    findings.append({"location": location + ".way_achieved", "issue": "achievement_flag_requires_qualification",
                                     "reason": reason})
                elif strict and not entry["way_achieved"]:
                    findings.append({"location": location + ".way_achieved", "issue": "achievement_flag_false_under_article_criterion"})
    all_pairs = set()
    for path in INFRA.glob("*.json"):
        record = load(path)
        if "framework" in record and "dialect" in record:
            all_pairs.add((record["framework"], record["dialect"]))
    truncations = [f for f in findings if f["issue"] == "truncated_prefix"]
    summary = {"pairs": len(used_pairs), "way_records": len(rows),
               "variant_records": len(variants),
               "variant_inputs_missing": sum(v["input_missing"] for v in variants),
               "variant_dialect_scope_differences": sum(v["dialect_differs_from_outer_model"] for v in variants),
               "variant_framework_scope_differences": sum(v["framework_differs_from_outer_framework"] for v in variants),
               "variant_outputs_matched_by_actual_scope": sum(v["matching_observation_count"] > 0 for v in variants),
               "variant_output_content_truncations": sum(v["output_content_is_truncated_prefix"] for v in variants),
               "way_record_counts": dict(collections.Counter(r["way"] for r in rows)),
               "complete_input_records": sum(r["input_complete"] for r in rows),
               "truncated_input_records": sum(f["location"].endswith(".input") for f in truncations),
               "other_truncated_fields": sum(not f["location"].endswith(".input") for f in truncations),
               "true_flags_requiring_qualification": sum(f["issue"] == "achievement_flag_requires_qualification" for f in findings),
               "qualification_reasons": dict(collections.Counter(
                   f["reason"] for f in findings if f["issue"] == "achievement_flag_requires_qualification")),
               "argument_representation_changes": len(representation_changes),
               "value_mismatches": sum(f["issue"] in ("value_mismatch", "call_count_mismatch") for f in findings),
               "pairs_absent_from_aggregate": sorted(framework + "/" + dialect for framework, dialect in all_pairs - used_pairs)}
    assert aggregate_bytes == aggregate_path.read_bytes(), "Evidence was updated during the audit; run again"
    return {"scope": "Default-record comparison plus variant provenance/output checks; no HTTP requests or tool execution",
            "aggregate_sha256": hashlib.sha256(aggregate_bytes).hexdigest(),
            "summary": summary, "findings": findings,
            "representation_changes": representation_changes, "records": rows, "variant_records": variants}


if __name__ == "__main__":
    report = audit()
    (ROOT / "results/audits/five_ways_evidence_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
