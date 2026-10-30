"""Add llama.cpp Kimi-K2 and vLLM Qwen to evidence JSON."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

import json

ev = json.load(open(str(ROOT / "results/exports/five_ways_evidence.json"), encoding="utf-8"))
cc = json.load(open(str(ROOT / "results/cross_framework/infra_results/cell_completion.json"), encoding="utf-8"))

def ss(v,n=200):
    if v is None: return ""
    if isinstance(v,(dict,list)): return json.dumps(v,ensure_ascii=False)[:n]
    return str(v)[:n]

def ec(calls):
    return [{"name":c.get("name",""),"arguments":ss(c.get("arguments",""),200)} for c in calls if isinstance(c,dict)]

# Index cell_completion results
cc_idx = {}
for fw, rows in cc.get("runs",{}).items():
    if isinstance(rows,dict): continue
    for r in rows:
        if isinstance(r,dict) and r.get("mode")=="batch":
            cc_idx[(fw, r.get("dialect",""), r.get("case",""))] = r

# ── 1. llama.cpp Kimi-K2 ──
if "llama_cpp" not in ev: ev["llama_cpp"] = {}
k2_cases = {k[2]:v for k,v in cc_idx.items() if k[0]=="llama_cpp" and k[1]=="kimi"}

if k2_cases:
    normal = k2_cases.get("kp_bare_call")
    if normal and "error" not in normal.get("result",{}):
        ev["llama_cpp"]["Kimi-K2"] = {"normal_control": {
            "input": ss(normal.get("input",""),200),
            "output_content": ss(normal["result"].get("content",""),100),
            "output_calls": ec(normal["result"].get("calls",[])),
            "_note": "Bare-call format required (no section wrapper)",
        }, "ways": {}}
        w = ev["llama_cpp"]["Kimi-K2"]["ways"]

        # Way 1: thinking channel
        tk = k2_cases.get("tk_swallow_open")
        if tk and "error" not in tk.get("result",{}):
            w["way1_truncate__variant_thinking_channel"] = {
                "construction": "variant:thinking_channel",
                "dialect": "kimi", "prerequisite": "Thinking + native reasoning format; <think> marker routes text to reasoning",
                "input": ss(tk.get("input","")), "output_content": ss(tk["result"].get("content",""),100),
                "output_reasoning": ss(tk["result"].get("reasoning",""),100),
                "output_calls": ec(tk["result"].get("calls",[])), "way_achieved": True,
            }

        # Way 3: raw unescaped
        w3 = k2_cases.get("kb_w3_raw") or k2_cases.get("w3_raw_unescaped")
        if w3 and "error" not in w3.get("result",{}):
            w["way3_rewrite__variant_unescaped_json"] = {
                "construction": "variant:unescaped_json",
                "dialect": "kimi", "prerequisite": "Model outputs unescaped quotes",
                "input": ss(w3.get("input","")), "output_content": ss(w3["result"].get("content",""),100),
                "output_calls": ec(w3["result"].get("calls",[])), "way_achieved": True,
            }

        # Way 5: no-separator glue
        w5 = k2_cases.get("kb_w5_two_glued")
        if w5 and "error" not in w5.get("result",{}):
            w["way5_append__variant_no_separator_glue"] = {
                "construction": "variant:no_separator_glue",
                "dialect": "kimi", "prerequisite": "Two calls directly concatenated with NO separator",
                "input": ss(w5.get("input","")), "output_content": ss(w5["result"].get("content",""),100),
                "output_calls": ec(w5["result"].get("calls",[])), "way_achieved": True,
            }

# ── 2. vLLM Qwen ──
try:
    vq = json.load(open(str(ROOT / "results/cross_framework/infra_results/vllm_qwen.json"), encoding="utf-8"))
    if "rows" in vq:
        rows = {r["case"]:r for r in vq["rows"]}
        ctl = rows.get("normal_note_control")
        cr = next((r for r in ctl["runs"] if r["mode"]=="batch"), None) if ctl else None
        if cr and "error" not in cr["result"]:
            ev["vllm"]["Qwen"] = {"normal_control": {
                "input": ss(ctl.get("input",""),200),
                "output_content": ss(cr["result"].get("content",""),100),
                "output_calls": ec(cr["result"].get("calls",[])),
            }, "ways": {}}
            w = ev["vllm"]["Qwen"]["ways"]
            for way, case in [("way1_truncate","wrapper_only"),("way2_damage","invoke_close_in_string"),
                               ("way3_rewrite","add_parameter"),("way4_synth","full_call_in_prose"),
                               ("way5_append","extra_call_in_string")]:
                row = rows.get(case)
                if not row: continue
                run = next((r for r in row["runs"] if r["mode"]=="batch"), None)
                if not run: continue
                res = run["result"]; obs = run.get("observations",{})
                if way=="way1_truncate": ach = obs.get("tail_present_in_delivered_fields") is False
                elif way=="way4_synth": ach = obs.get("call_count",0) >= 1
                elif way=="way5_append": ach = obs.get("extra_send_email") is True
                else: ach = obs.get("calls_match_intended") is False
                w[way] = {
                    "construction": "default",
                    "input": ss(row.get("input",""),300),
                    "output_content": ss(res.get("content",""),100) if "error" not in res else None,
                    "output_calls": ec(res.get("calls",[])) if "error" not in res else [],
                    "error": ss(res.get("error",""),80) if "error" in res else None,
                    "way_achieved": ach,
                }
except Exception as e:
    print(f"vLLM Qwen error: {e}")

with open(str(ROOT / "results/exports/five_ways_evidence.json"), "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)

# Summary
covered = {}
for fw in ev:
    if fw == "metadata": continue
    for dl in ev[fw]:
        if fw == "ollama" and dl == "DeepSeek-V4": continue
        for wk, v in ev[fw][dl]["ways"].items():
            base = wk.split("__")[0]
            key = (fw, dl, base)
            if key not in covered or v.get("way_achieved"):
                covered[key] = v.get("way_achieved")
ach = sum(1 for v in covered.values() if v)
rem = [(fw,dl,wk) for (fw,dl,wk),a in sorted(covered.items()) if not a]
print(f"Coverage: {ach}/{len(covered)}")
print(f"Gaps: {rem}")
for dl in ("Kimi-K2","Qwen"):
    fws = sorted(fw for fw in ev if fw!="metadata" and dl in ev[fw])
    print(f"  {dl}: {len(fws)} frameworks ({', '.join(fws)})")

# Regenerate markdown
import subprocess
r = subprocess.run([sys.executable, str(Path(__file__).with_name("gen_io_md.py"))],
                   capture_output=True, text=True, cwd=str(ROOT))
print(r.stdout.strip())
