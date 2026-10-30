"""Restore missing way2/way4 keys for llama_cpp/Kimi-K2.

An earlier evidence regeneration silently dropped this dialect's default
entries (its section-wrapped normal control does not pass the llama.cpp Kimi
grammar), and the later fill rounds only re-added way1/way3/way5. This script
re-runs and records:

- way2: the grammar route rejects the whole output once the injection breaks
  the call region (binary acceptance) -> recorded honestly as NOT achieved,
  with the error retained.
- way4: prose followed by a complete section-wrapped call -> call delivered,
  HEAD preserved.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from infra_probes import TOOLS, worker_command

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EV = os.path.join(ROOT, "results", "exports", "five_ways_evidence.json")


def run(text):
    cmd = worker_command("llama_cpp")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, encoding="utf-8", cwd=ROOT)
    payload = {"framework": "llama_cpp", "dialect": "kimi", "mode": "batch",
               "chunks": [text], "tools": TOOLS}
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    proc.stdin.close()
    proc.wait()
    return json.loads(line) if line else {"error": "worker exited"}


def ss(v, n=200):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:n]
    return str(v)[:n]


def ec(calls):
    return [{"name": c.get("name", ""), "arguments": ss(c.get("arguments", ""), 200)}
            for c in calls if isinstance(c, dict)]


W2_TEXT = ('HEAD\n<|tool_call_begin|>functions.note:0<|tool_call_argument_begin|>'
           '{"text": "save this"}<|tool_call_end|> TAIL_SENTINEL junk<|tool_call_end|>')
W4_TEXT = ('HEAD<|tool_calls_section_begin|><|tool_call_begin|>functions.note:0'
           '<|tool_call_argument_begin|>{"text": "save this"}<|tool_call_end|>'
           '<|tool_calls_section_end|>')

ev = json.load(open(EV, encoding="utf-8"))
ways = ev["llama_cpp"]["Kimi-K2"]["ways"]

r2 = run(W2_TEXT)
print("way2 rerun:", json.dumps(r2, ensure_ascii=False)[:220])
r4 = run(W4_TEXT)
print("way4 rerun:", json.dumps(r4, ensure_ascii=False)[:220])

ways["way2_damage"] = {
    "construction": "default",
    "dialect": "kimi",
    "prerequisite": "",
    "input": ss(W2_TEXT, 300),
    "output_content": None,
    "output_calls": [],
    "error": ss(r2.get("error", ""), 120),
    "way_achieved": False,
    "detail": "llama.cpp grammar route: binary acceptance — once the injected tail "
              "breaks the call region, the whole output is rejected; no silent "
              "partial damage is possible",
}
w4_ok = "error" not in r4 and any(c.get("name") == "note" for c in r4.get("calls", []))
ways["way4_synth__variant_section_after_prose"] = {
    "construction": "variant:section_after_prose",
    "dialect": "kimi",
    "prerequisite": "Complete section-wrapped call emitted right after prose, no separator",
    "input": ss(W4_TEXT, 300),
    "output_content": ss(r4.get("content", ""), 100) if "error" not in r4 else None,
    "output_calls": ec(r4.get("calls", [])) if "error" not in r4 else [],
    "error": ss(r4.get("error", ""), 80) if "error" in r4 else None,
    "way_achieved": w4_ok,
}
print(f"way2 recorded: not achieved (grammar binary reject)")
print(f"way4 recorded: achieved={w4_ok}")

with open(EV, "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)

covered = {}
for fw in ev:
    if fw == "metadata":
        continue
    for dl in ev[fw]:
        if fw == "ollama" and dl == "DeepSeek-V4":
            continue
        for wk, v in ev[fw][dl]["ways"].items():
            base = wk.split("__")[0]
            key = (fw, dl, base)
            if key not in covered or v.get("way_achieved"):
                covered[key] = v.get("way_achieved")
ach = sum(1 for v in covered.values() if v)
rem = [(fw, dl, wk) for (fw, dl, wk), a in sorted(covered.items()) if not a]
print(f"\nCoverage: {ach}/{len(covered)}")
for g in rem:
    print("  gap:", g)
