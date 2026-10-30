"""One-line-per-combo diagnosis: failing controls + outcome shape per key case."""

from __future__ import annotations

import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

KEY = ("wrapper_only", "lone_invoke", "parameter_spelling_in_string",
       "add_parameter", "full_call_in_prose", "extra_call_in_string")


def shape_of(row):
    run = next((x for x in row["runs"] if x["mode"] == "batch"), row["runs"][0])
    res, obs = run["result"], run["observations"]
    calls = res.get("calls", [])
    if "error" in res:
        return "ERROR"
    if obs.get("extra_send_email"):
        return "2calls(email)"
    if any(c.get("name") == "web_fetch" for c in calls):
        return "synth"
    if len(calls) >= 2:
        return "2calls:" + "+".join(sorted({c.get("name") or "?" for c in calls}))
    if len(calls) == 1:
        name = calls[0].get("name") or "?"
        if obs.get("calls_match_intended") is False:
            return f"altered({name})"
        return f"call({name})"
    if obs.get("tail_present_in_delivered_fields") is False:
        return "tail-swallowed"
    return "inert/passthru"


def main():
    for path in sorted((HERE.parents[1] / "results" / "cross_framework" / "infra_results").glob("*.json")):
        if path.name in ("matrix.json", "cross_dialect.json"):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        rows = {x["case"]: x for x in report["rows"]}
        fails = []
        for row in report["rows"]:
            if not row["control"]:
                continue
            states = set()
            for run in row["runs"]:
                obs = run["observations"]
                if "error" in obs or obs.get("control_passed") is False:
                    states.add("err" if "error" in obs else "fail")
            if states:
                fails.append(f"{row['case']}({'+'.join(sorted(states))})")
        shapes = {k.split("_", 1)[1][:16]: shape_of(row) for k in KEY if (row := rows.get(k))}
        print(f"{report['framework'] + '/' + report['dialect']:26} fails={fails[:3]}")
        for key, shape in shapes.items():
            print(f"{'':28} {key:18} {shape}")


if __name__ == "__main__":
    main()
