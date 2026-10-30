"""Run newly added cell_completion cases and merge them into the report.

Runs the same five modes as cell_completion.main() so the merged file matches
what a full rerun would produce. Existing runs of the same (dialect, case,
mode) are replaced.
"""
import json
import re
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from cell_completion import CASES, classify, OUT
from infra_probes import TOOLS, worker_command

ROOT = Path(__file__).resolve().parents[2]
NEW_CASES = {"w2b_qw_eot_newline", "w2b_qw_unescaped_marker", "w2b_k2_unescaped_marker",
             "w2b_k2_unbalanced_quote", "w2b_k2_nested_markers", "kb_w4_section",
             "generic_w1_open", "generic_w2_value_markers",
             "ref_w4_section_fence", "qc_w1_sandwich", "qc_w1_fn_header",
             "generic_w2_qw_unescaped_quote", "w2c_rebalance_empty",
             "w2c_midvalue_cut", "qc_w2_early_complete", "w2b_qw_midvalue_cut",
             "w2c_param_emptied", "qc_w2_emptied", "w2b_qw_emptied"}

report = json.loads((OUT / "cell_completion.json").read_text(encoding="utf-8"))
known = {c["case"] for c in report["cases"]}

# Add any case objects not yet recorded
for case in CASES:
    if case["case"] in NEW_CASES and case["case"] not in known:
        report["cases"].append({k: case[k] for k in ("targets", "dialect", "case", "input", "note")})

frameworks = []
for case in CASES:
    if case["case"] not in NEW_CASES:
        continue
    for fw in case["targets"]:
        if fw not in frameworks:
            frameworks.append(fw)

for framework in frameworks:
    command = worker_command(framework)
    if not Path(command[0]).exists():
        print(f"!! worker missing for {framework}")
        continue
    rows = report["runs"].get(framework, [])
    native = framework in ("llama_cpp", "ollama", "dynamo")
    groups = {}
    for case in CASES:
        if case["case"] in NEW_CASES and framework in case["targets"]:
            groups.setdefault(case["dialect"] if native else "*", []).append(case)
    for group_cases in groups.values():
        stderr = open(OUT / f"cells_{framework}.stderr.log", "a", encoding="utf-8")
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=stderr, text=True, encoding="utf-8", cwd=ROOT)
        try:
            for case in group_cases:
                lines = case["input"].split("\n")
                nl_chunks = [line + "\n" for line in lines[:-1]] + [lines[-1]]
                for mode, chunks in (("batch", [case["input"]]),
                                     ("stream", [case["input"]]),
                                     ("stream13", [case["input"][i:i + 13]
                                                   for i in range(0, len(case["input"]), 13)]),
                                     ("streamnl", nl_chunks),
                                     ("streammk", [c for c in re.split(r"(<[^>]*>)", case["input"]) if c])):
                    request = {"framework": framework, "dialect": case["dialect"],
                               "mode": "batch" if mode == "batch" else "stream",
                               "chunks": chunks, "tools": TOOLS,
                               "thinking": case.get("thinking", False), "rf": case.get("rf") or ""}
                    proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                    proc.stdin.flush()
                    line = proc.stdout.readline()
                    result = json.loads(line) if line else {"error": "worker exited"}
                    row = {"dialect": case["dialect"], "case": case["case"], "mode": mode,
                           "result": result, "observations": classify(result, case["input"])}
                    rows = [r for r in rows
                            if not (r.get("dialect") == case["dialect"] and r.get("case") == case["case"]
                                    and r.get("mode") == mode)]
                    rows.append(row)
        finally:
            proc.stdin.close()
            proc.wait(timeout=15)
            stderr.close()
    report["runs"][framework] = rows
    for r in rows:
        if r["case"] in NEW_CASES and r["mode"] == "batch":
            obs = r["observations"]
            print(f"{framework:14s} {r['dialect']:8s} {r['case']:28s} outcome={obs.get('outcome'):16s} "
                  f"invalid={obs.get('invalid_json')} sentinel={obs.get('sentinel_delivered')}")

(OUT / "cell_completion.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("cell_completion.json merged")
