"""Aggregate infra_results/*.json into a five-way achievement matrix.

A way counts as achieved for a framework x dialect when the matching probe
case shows the expected deviation from the intended call (or swallowed tail),
while the paired literal control passes. Stream/batch agreement is reported
per row. Output: infra_results/matrix.json plus a printed table.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[1] / "results" / "cross_framework" / "infra_results"

WAY_CASES = {
    1: ("wrapper_only", "empty_wrapper", "quoted_wrapper"),
    2: ("lone_invoke", "parameter_close_in_string", "invoke_close_in_string"),
    3: ("overwrite_parameter", "add_parameter", "parameter_spelling_in_string"),
    4: ("full_call_in_prose", "full_call_in_code_block", "full_call_without_suffix"),
    5: ("extra_call_in_string", "extra_call_balanced", "extra_zero_arg_in_string"),
}


def achieved(case, run):
    obs = run["observations"]
    if "error" in obs:
        return None
    way, name = case.get("way"), case["case"]
    if way == 1:
        return obs.get("tail_present_in_delivered_fields") is False
    if way == 4:
        return obs.get("call_count", 0) >= 1
    if way == 5:
        return bool(obs.get("extra_send_email"))
    # Ways 2 and 3: the intended call must have been altered.
    return obs.get("calls_match_intended") is False and obs.get("control_passed", True) is not False


def main():
    matrix = {}
    for path in sorted(RESULTS.glob("*.json")):
        if path.name in ("matrix.json", "cross_dialect.json"):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if not all(key in report for key in ("framework", "dialect", "rows")):
            continue
        framework, dialect = report["framework"], report["dialect"]
        rows = {row["case"]: row for row in report["rows"]}
        errors = []
        entry = {"ways": {}, "cases": {}}
        controls_ok = all(
            run["observations"].get("control_passed", True)
            for row in report["rows"] if row["control"]
            for run in row["runs"] if "error" not in run["observations"]
        )
        for way, names in WAY_CASES.items():
            hits, total = [], 0
            for name in names:
                row = rows.get(name)
                if not row:
                    continue
                total += 1
                states = {achieved(row, run) for run in row["runs"]}
                if True in states:
                    hits.append(name)
                    mixed = len(states) > 1
                entry["cases"][name] = {
                    "achieved": True in states,
                    "mixed_across_modes": len(states) > 1,
                    "errors": sum(1 for run in row["runs"] if "error" in run["observations"]),
                }
                for run in row["runs"]:
                    if "error" in run["observations"]:
                        errors.append((name, run["observations"]["error"]))
            entry["ways"][str(way)] = {"achieved_cases": hits, "cases_present": total}
        entry["controls_passed"] = controls_ok
        entry["stream_batch_disagreements"] = sum(
            0 if row["normalized_results_agree"] else 1 for row in report["rows"]
        )
        if errors:
            entry["sample_errors"] = errors[:4]
        matrix[f"{framework}/{dialect}"] = entry

    (RESULTS / "matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{'framework/dialect':28} ctrl  w1  w2  w3  w4  w5  stream≠batch")
    for key, entry in matrix.items():
        flags = []
        for way in range(1, 6):
            info = entry["ways"].get(str(way), {})
            flags.append("Y" if info.get("achieved_cases") else ("-" if info.get("cases_present") else "."))
        print(f"{key:28} {'ok ' if entry['controls_passed'] else 'FAIL'}   {'   '.join(flags)}   {entry['stream_batch_disagreements']}")


if __name__ == "__main__":
    main()
