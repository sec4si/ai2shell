"""Five-way achievement split by parsing mode (batch vs streaming).

Cells show batch/stream per way:
  ● achieved in that mode (stream: every chunk size)
  ◐ stream-only partial (some chunk sizes, not all)
  E error form (all runs error, nothing achieved)
  ✗ not achieved in that mode
Pairings whose normal-call control fails in either mode are marked N/A.
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


def run_state(case, run):
    obs = run["observations"]
    if "error" in obs:
        return "E"
    way, calls = case.get("way"), run["result"].get("calls", [])
    names = [c.get("name") for c in calls]
    if way == 1:
        return True if obs.get("tail_present_in_delivered_fields") is False else False
    if way == 4:
        return True if obs.get("call_count", 0) >= 1 else False
    if way == 5:
        # Name-level: a send_email slot exists (arg encoding noted separately).
        return True if "send_email" in names else False
    return True if obs.get("calls_match_intended") is False else False


def render(states):
    if True in states:
        return "●"
    if states and all(s == "E" for s in states):
        return "E"
    return "✗"


def main():
    print(f"{'framework/dialect':24} {'w1 批/流':10} {'w2':6} {'w3':6} {'w4':6} {'w5':6}  notes")
    for path in sorted(RESULTS.glob("*.json")):
        if path.name in ("matrix.json", "cross_dialect.json"):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if not all(key in report for key in ("framework", "dialect", "rows")):
            continue
        rows = {row["case"]: row for row in report["rows"]}
        control = rows.get("normal_note_control")
        gate_states, fine_drop = [], False
        if control:
            for run in control["runs"]:
                obs = run["observations"]
                ok = "error" not in obs and obs.get("control_passed") is not False
                if run["mode"] == "batch":
                    gate_states.append(ok)
                elif not ok:
                    fine_drop = True
        ctrl_bad = not gate_states or not all(gate_states)
        notes = ["control drops at fine chunks"] if fine_drop and not ctrl_bad else []
        cells = []
        if ctrl_bad:
            cells = ["N/A"] * 5
            notes.append("pairing control failed")
        else:
            for way, names in WAY_CASES.items():
                batch, stream = set(), set()
                for name in names:
                    row = rows.get(name)
                    if not row:
                        continue
                    for run in row["runs"]:
                        state = run_state(row, run)
                        if run["mode"] == "batch":
                            batch.add(state)
                        else:
                            stream.add(state)
                # stream chunk granularity: achieved in every chunk size?
                chunk_states = []
                for size in ("whole", 1, 3, 13):
                    chunk_states.append(any(
                        run_state(rows[n], r) is True
                        for n in names if n in rows
                        for r in rows[n]["runs"]
                        if r["mode"] == "stream" and r["chunk_size"] == size))
                if True in stream:
                    stream_sym = "●" if all(chunk_states) else "◐"
                    if not all(chunk_states):
                        notes.append(f"w{way}:chunk-sensitive")
                else:
                    stream_sym = render(stream)
                cells.append(f"{render(batch)}/{stream_sym}")
        print(f"{report['framework'] + '/' + report['dialect']:24} "
              + " ".join(f"{c:6}" for c in cells) + "  " + ",".join(notes))


if __name__ == "__main__":
    main()
