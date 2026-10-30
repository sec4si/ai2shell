"""Generate fully covered five_ways_evidence.json with default AND variant results."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

import json, os

def ss(v, n=2000):
    if v is None: return ""
    if isinstance(v, dict): return json.dumps(v, ensure_ascii=False)[:n]
    if isinstance(v, list): return json.dumps(v, ensure_ascii=False)[:n]
    return str(v)[:n]

def ec(calls):
    out = []
    for c in calls:
        if isinstance(c, dict):
            out.append({"name": c.get("name",""), "arguments": ss(c.get("arguments",""),200)})
        else:
            out.append({"name": str(c), "arguments": ""})
    return out

DIR = str(ROOT / "results/cross_framework/infra_results")
CC  = json.load(open(f"{DIR}/cell_completion.json", encoding="utf-8"))

# ── Load default results ──
default = {}
for f in os.listdir(DIR):
    if not f.endswith(".json") or f in ("matrix.json","cross_dialect.json","cell_completion.json"): continue
    try: rep = json.load(open(f"{DIR}/{f}", encoding="utf-8"))
    except: continue
    if not isinstance(rep, dict) or not isinstance(rep.get("rows"), list): continue
    if "framework" not in rep or "dialect" not in rep: continue
    default[(rep["framework"], rep["dialect"])] = {r["case"]: r for r in rep["rows"]}

# ── Index variant results by (fw, dl, case) ──
variants = {}
for fw, rows in CC.get("runs", {}).items():
    if isinstance(rows, dict): continue
    for row in rows:
        if not isinstance(row, dict): continue
        if row.get("mode") != "batch": continue
        variants[(fw, row.get("dialect",""), row.get("case",""))] = row

# Case inputs live only on the case objects, not on the runs.
CASE_INPUTS = {(c["dialect"], c["case"]): c.get("input","") for c in CC.get("cases", [])}

# Directed replays can add a framework result for an existing case definition.
# Match the full Qwen input before attaching its saved result to this case.
checks_path = os.path.join(DIR, "article_variant_checks.json")
if os.path.exists(checks_path):
    with open(checks_path, encoding="utf-8") as checks_file:
        checks = json.load(checks_file)
    for record in checks.get("records", []):
        request = record.get("request", {})
        if record.get("control") or record.get("nominal_way") != 3: continue
        if request.get("dialect") != "qwen" or request.get("mode") != "batch": continue
        if request.get("thinking") or request.get("rf"): continue
        raw_input = "".join(request.get("chunks", []))
        if raw_input != CASE_INPUTS.get(("qwen", "w3_raw_unescaped")): continue
        result = record.get("result", {})
        has_to = False
        for call in result.get("calls", []):
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try: arguments = json.loads(arguments)
                except ValueError: continue
            if call.get("name") == "note" and isinstance(arguments, dict) and "to" in arguments:
                has_to = True
        key = (request["framework"], "qwen", "w3_raw_unescaped")
        variants.setdefault(key, {"input": raw_input, "result": result,
                                  "observations": {"to_key_injected": has_to},
                                  "source": "article_variant_checks.json"})

def args_invalid_and_clean(vres):
    """Way2 damage: a delivered call whose arguments no longer parse as JSON.

    The injection broke the argument payload (truncated/mangled). Where the
    sentinel text itself ends up (args or leaked content) does not change that
    the call is damaged.
    """
    for c in (vres.get("calls") or []):
        raw = c.get("arguments")
        if isinstance(raw, str):
            try: json.loads(raw)
            except ValueError:
                return True
    return False


def call_value_destroyed(vres):
    """Way2 damage with structurally valid output: a call is delivered but the
    original value text is gone from it (truncated/emptied) and the sentinel
    was swallowed with the call."""
    calls = vres.get("calls") or []
    if not calls:
        return False
    blob = json.dumps(calls, ensure_ascii=False)
    return "SENTINEL" not in blob and "save this" not in blob

DL = {"v4":"DeepSeek-V4","v32":"DeepSeek-V3.2","v41":"DeepSeek-V4.1",
      "kimi":"Kimi-K2","kimi_k3":"Kimi-K3","deepseek3":"DeepSeek-V3",
      "qwen_coder":"Qwen-Coder","qwen":"Qwen"}
FWS = ["vllm","sglang","lmdeploy","tensorrt_llm","ollama","llama_cpp","dynamo"]

DEF_CASES = {
    "way1_truncate": ["wrapper_only","empty_wrapper"],
    "way2_damage":   ["invoke_close_in_string","parameter_close_in_string"],
    "way3_rewrite":  ["add_parameter","overwrite_parameter"],
    "way4_synth":    ["full_call_in_prose","full_call_without_suffix"],
    "way5_append":   ["extra_call_in_string","extra_call_balanced"],
}

VAR_MAP = {
    "way1_truncate": {
        "v4/r9_all_reasoning": "thinking_channel",
        "qwen_coder/qc_w1_open": "template_exact",
        "deepseek3/ds3_w1_open": "marker_aligned",
        "qwen_coder_generic/generic_w1_open": "generic_scanner",
        "qwen/w2_earlybalanced": "balanced_json",
        "qwen_coder/qc_w1_sandwich": "sandwich",
        "qwen_coder/qc_w1_fn_header": "fn_header",
    },
    "way2_damage": {
        "kimi/w2_earlyclose": "early_close_json",
        "qwen/w2_earlyclose_tag": "early_close_tag",
        "qwen/w2_earlybalanced": "balanced_json",
        "qwen_coder/w2_close_then_junk": "early_close_tag",
        "deepseek3/ref_w2_single_fence": "single_fence",
        "qwen/w2b_qw_eot_newline": "raw_newline_eot_in_value",
        "qwen/w2b_qw_unescaped_marker": "unescaped_quote_marker",
        "qwen/w2b_qw_midvalue_cut": "midvalue_cut",
        "qwen/w2b_qw_emptied": "param_emptied",
        "kimi/w2b_k2_unescaped_marker": "unescaped_quote_marker",
        "kimi/w2b_k2_unbalanced_quote": "unescaped_quote_unbalanced",
        "kimi/w2b_k2_nested_markers": "nested_markers",
        "v32/v32_w2_param_close": "close_tag_in_value",
        "qwen_coder_generic/generic_w2_value_markers": "generic_scanner",
        "qwen_coder_generic/generic_w2_qw_unescaped_quote": "generic_scanner",
        "qwen_coder/w2c_rebalance_empty": "rebalanced_param_close",
        "qwen_coder/w2c_midvalue_cut": "midvalue_cut",
        "qwen_coder/w2c_param_emptied": "param_emptied",
        "qwen_coder/qc_w2_emptied": "param_emptied",
        "qwen_coder/qc_w2_early_complete": "early_complete_close",
    },
    "way3_rewrite": {
        "kimi/w3_raw_unescaped": "unescaped_json",
        "qwen/w3_raw_unescaped": "unescaped_json",
        "deepseek3/w3_raw_unescaped": "unescaped_json",
        "kimi/kb_w3_raw": "unescaped_json",
        "qwen/lq_w3_extra_key": "unescaped_json",
    },
    "way4_synth": {
        "deepseek3/ref_w4_prose": "reference_construct",
        "deepseek3/ref_w4_section_fence": "reference_construct",
        "kimi/kb_w4_section": "section_after_prose",
        "qwen/lq_w4_proper": "grammar_full_call",
    },
    "way5_append": {
        "kimi/w5_earlyclose": "early_close_second",
        "kimi/w5_two_proper_calls": "early_close_second",
        "kimi/kb_w5_two_glued": "no_separator_glue",
        "kimi/kb_w5_section_two": "two_sections",
        "qwen/w5_two_proper_calls": "early_close_second",
        "qwen/lq_w5_two": "two_blocks",
        "qwen_coder/qc_w5_two_blocks": "two_blocks",
        "deepseek3/ref_w5_two_proper": "reference_construct",
    },
}

PREREQ = {
    "thinking_channel": "Model deployment with thinking enabled + native reasoning format; model outputs text without </think> closer",
    "template_exact": "Template-exact format: parameter values surrounded by newlines (<parameter=url>\\nvalue\\n</parameter>)",
    "generic_scanner": "Ollama official model routing uses the generic template-tag scanner (no dedicated parser for this dialect): bare tag enters tool mode and an unparsable body is held/swallowed without error",
    "early_close_json": "Model outputs unescaped closing brace+quote before the injected end marker, putting the marker outside JSON string context",
    "early_close_tag": "Model outputs closing JSON+tag (\"}}+</tool_call>) before sentinel, putting sentinel outside the call structure",
    "balanced_json": "Parameter contains a complete balanced JSON object followed by attack text",
    "unescaped_json": "Model copies text verbatim WITHOUT escaping quotes; the JSON already contains the extra key in the output",
    "single_fence": "Injected close-fence+call-end; no more ``` sequences after injection point (greedy regex constraint)",
    "reference_construct": "Classic V3 format with function prefix + json code fence (SGLang/TRT/Dynamo expected format)",
    "early_close_second": "Model outputs unescaped closing brace+quote, then end marker, then a second complete call",
    "no_separator_glue": "llama.cpp Kimi grammar: calls must be directly concatenated with NO separator (no newline/space)",
    "two_sections": "llama.cpp Kimi grammar: two complete section-wrapped calls",
    "two_blocks": "llama.cpp/generic grammar: two independent <tool_call> blocks, not one block with two functions",
    "grammar_full_call": "llama.cpp grammar: a complete, well-formed call block on its own line group (grammar accepts it as a real call)",
    "section_after_prose": "llama.cpp Kimi grammar: complete section-wrapped call emitted directly after prose, no separator",
    "marker_aligned": "Chunk boundaries align with token boundaries (realistic token stream; arbitrary splits fail but aligned ones succeed)",
    "raw_newline_eot_in_value": "Model copies injected newline+</tool_call> verbatim inside the JSON string (raw newline byte, not \\\\n): the lazy batch regex ends the call at the marker, JSON truncated, call dropped",
    "unescaped_quote_marker": "Model outputs the value's closing quote unescaped, then the end marker lands between string-close and object-close: LMDeploy ends the call at a not-in-string marker; Dynamo falls back to the lazy regex capture when serde rejects the region",
    "unescaped_quote_unbalanced": "Model outputs an unescaped quote inside the value: the Go brace-balance scanner flips in_string and never sees the closing brace, no balanced object, call never emitted",
    "nested_markers": "Model copies a second unescaped marker set inside the value: the argument scan breaks and args are delivered as truncated invalid JSON",
    "close_tag_in_value": "Parameter close tag inside the value: the grammar route drops the whole call",
    "sandwich": "An unclosed <tool_call> region swallows the following text; a second complete call inside the region is still delivered",
    "fn_header": "A function header opens a call region that never closes; the trailing text is never delivered while a call slot is emitted",
    "rebalanced_param_close": "Model copies an injected </parameter> into the value AND re-opens a same-name parameter to keep the XML balanced: the original value is silently truncated (here emptied), no parse error",
    "param_emptied": "Injected close tag lands at the very START of the parameter value: the parameter is delivered as an empty string — the entire legitimate value is destroyed (unambiguous damage; control without the injection delivers the full value)",
    "midvalue_cut": "Model copies an injected close tag verbatim into the MIDDLE of the parameter's sentence value: the parser cuts the value at the tag, delivering an obviously incomplete half sentence (control without the injection delivers the full sentence)",
    "early_complete_close": "llama.cpp QC grammar (template-exact, newline-wrapped values): model copies a complete close sequence (</parameter></function></tool_call>) into the middle of the value; the call ends early with the value truncated to the half sentence",
}

# Cells in scope for the comparison matrix (the studied framework x dialect
# pairs; extra cross-dialect probe files exist but are out of scope).
SCOPE = {
    "vllm": {"v32", "v4", "v41", "kimi", "qwen_coder", "qwen"},
    "sglang": {"v32", "v4", "v41", "kimi", "kimi_k3", "deepseek3", "qwen_coder", "qwen"},
    "lmdeploy": {"v32", "v4", "v41", "kimi", "qwen_coder", "qwen"},
    "tensorrt_llm": {"v32", "v4", "v41", "kimi", "kimi_k3", "deepseek3", "qwen_coder", "qwen"},
    "ollama": {"kimi", "deepseek3", "qwen_coder", "qwen"},
    "llama_cpp": {"v32", "v4", "kimi", "qwen_coder", "qwen"},
    "dynamo": {"v32", "v4", "kimi", "kimi_k3", "deepseek3", "qwen_coder", "qwen"},
}

# Variant runs whose dialect key differs from the cell they document.
# The ollama runner exposes the generic template-tag scanner only under the
# qwen_coder_generic dialect key; per-case attribution keeps each finding on
# the dialect cell it actually documents.
ALLOW_CROSS = {"qwen_coder_generic": {"qwen_coder", "qwen"}}
CASE_CELL = {
    "generic_w1_open": {"qwen_coder"},
    "generic_w2_value_markers": {"qwen_coder"},
    "generic_w2_qw_unescaped_quote": {"qwen"},
}

out = {"metadata": {
    "description": "Five trigger ways: fully covered evidence with default AND variant constructions",
    "construction_types": {
        "default": "Standard probe from infra_probes.py — a normal text containing markers is parsed",
        "variant": "Carefully crafted input from cell_completion.py — input shaped to exploit specific parser logic",
    },
    "prerequisite_meaning": "What must happen (model behavior or encoding) for the variant input to occur from a real user task",
    "ways": {
        "way1_truncate": "Tool-section start marker in prose → subsequent text dropped",
        "way2_damage": "Close tag in call's string value → parameter truncated or call ended early",
        "way3_rewrite": "Injected tags or unescaped quotes → new param keys or replaced values",
        "way4_synth": "Complete call structure in prose → delivered as real call",
        "way5_append": "Early-close + second complete call → two calls delivered",
    },
    "note": "way_achieved=true means the described anomaly was observed. For variants, prerequisite explains what upstream condition is needed.",
}}

for fw in FWS:
    fw_data = {}
    for (f2, dl), rows in default.items():
        if f2 != fw: continue
        if dl not in SCOPE.get(fw, set()): continue
        dl_name = DL.get(dl, dl)
        ctl = rows.get("normal_note_control")
        if not ctl: continue
        cr = next((r for r in ctl["runs"] if r["mode"]=="batch"), None)
        if not cr: continue
        # A dialect whose normal control fails is still recorded: its defaults
        # are documented as uninterpretable rather than silently dropped from
        # the matrix. Two failure modes:
        # - control errored (grammar rejection, missing config)
        # - control extracted no call at all (probe format never matched the
        #   parser, so negative way results prove nothing about injections)
        cr_obs = cr.get("observations", {})
        control_error = "error" in cr["result"]
        control_no_call = (not control_error) and cr_obs.get("call_count", 0) < 1
        if control_error:
            control_note = "normal control errored on this dialect: default probes are recorded for completeness, achievements come from variants"
        elif control_no_call:
            control_note = "normal control extracted no call (probe format does not match this parser): default probe results are not attributable to the injection"
        else:
            control_note = None

        d = {"normal_control": {
            "input": ss(ctl.get("input",""),200),
            "output_content": ss(cr["result"].get("content",""),100) if not control_error else None,
            "output_calls": ec(cr["result"].get("calls",[])) if not control_error else [],
            "error": ss(cr["result"].get("error",""),80) if control_error else None,
            "note": control_note,
        }, "ways": {}}

        # ── Default results ──
        for wk, cns in DEF_CASES.items():
            candidates = []
            for cn in cns:
                row = rows.get(cn)
                if not row: continue
                run = next((r for r in row["runs"] if r["mode"]=="batch"), None)
                if not run: continue
                res = run["result"]
                obs = run.get("observations",{})
                if "error" in res:
                    ach = False
                elif wk=="way1_truncate": ach = obs.get("tail_present_in_delivered_fields") is False
                elif wk=="way4_synth":    ach = obs.get("call_count",0) >= 1
                elif wk=="way5_append":   ach = obs.get("extra_send_email") is True
                else:                     ach = obs.get("calls_match_intended") is False
                candidates.append((ach, row, run, res, obs))
            if not candidates: continue
            # Prefer the first case that actually shows the anomaly; otherwise
            # show the first case's (negative) result.
            ach, row, run, res, obs = next((c for c in candidates if c[0]), candidates[0])
            # Without a passing control, default achievements are not
            # attributable to the injection (the probe format itself fails).
            if control_no_call and wk != "way1_truncate":
                ach = False
            entry = {
                "construction": "default",
                "dialect": dl,
                "case": row["case"],
                "input": row.get("input", ""),
                "output_content": ss(res.get("content",""),1000) if "error" not in res else None,
                "output_calls": ec(res.get("calls",[])) if "error" not in res else [],
                "error": ss(res.get("error",""),800) if "error" in res else None,
                "way_achieved": ach,
            }
            if control_note:
                entry["control_note"] = control_note
            d["ways"][wk] = entry

        # ── Variant results ──
        for wk, vardefs in VAR_MAP.items():
            for case_key, var_type in vardefs.items():
                parts = case_key.split("/", 1)
                if len(parts) != 2: continue
                vdl, vcn = parts
                # A variant documents THIS cell's dialect (cross-dialect routes
                # must be listed in ALLOW_CROSS, and a case listed in CASE_CELL
                # documents only its attributed cells).
                if vdl != dl and dl not in ALLOW_CROSS.get(vdl, set()): continue
                if vcn in CASE_CELL and dl not in CASE_CELL[vcn]: continue
                vkey = (fw, vdl, vcn)
                if vkey not in variants: continue
                vrow = variants[vkey]
                vres = vrow.get("result",{})
                vobs = vrow.get("observations",{})

                if "error" in vres:
                    v_ach = False
                elif wk == "way1_truncate":
                    v_ach = vobs.get("sentinel_delivered") is False
                elif wk == "way2_damage":
                    v_ach = (vobs.get("outcome") == "tail_swallowed"
                             or args_invalid_and_clean(vres)
                             or call_value_destroyed(vres))
                elif wk == "way3_rewrite":
                    v_ach = vobs.get("to_key_injected") is True
                elif wk == "way4_synth":
                    v_ach = vobs.get("outcome") == "web_fetch_call" or any(
                        c.get("name") == "web_fetch" for c in (vres.get("calls") or []))
                else:  # way5_append
                    v_ach = vobs.get("outcome") == "send_email_call" or any(
                        c.get("name") == "send_email" for c in (vres.get("calls") or []))

                var_key = f"{wk}__variant_{var_type}"
                if var_key in d["ways"]: continue

                d["ways"][var_key] = {
                    "construction": f"variant:{var_type}",
                    "dialect": vdl,
                    "case": vcn,
                    "source": vrow.get("source", "cell_completion.json"),
                    "prerequisite": PREREQ.get(var_type, ""),
                    "input": vrow.get("input", "") or CASE_INPUTS[(vdl, vcn)],
                    "output_content": ss(vres.get("content",""),100) if "error" not in vres else None,
                    "output_calls": ec(vres.get("calls",[])) if "error" not in vres else [],
                    "output_reasoning": ss(vres.get("reasoning",""),100) if "error" not in vres and vres.get("reasoning") else None,
                    "error": ss(vres.get("error",""),80) if "error" in vres else None,
                    "way_achieved": v_ach,
                    "detail": {
                        "outcome": vobs.get("outcome"),
                        "to_key": vobs.get("to_key_injected"),
                        "sentinel_delivered": vobs.get("sentinel_delivered"),
                        "arg_keys": vobs.get("arg_keys"),
                    },
                }

        if d["ways"]:
            fw_data[dl_name] = d

    if fw_data:
        out[fw] = fw_data

path = str(ROOT / "results/exports/five_ways_evidence.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"Written: {path} ({os.path.getsize(path)} bytes)")

# Summary
total_d = total_v = ach_d = ach_v = 0
for fw in FWS:
    if fw not in out: continue
    for dl in out[fw]:
        for k, v in out[fw][dl]["ways"].items():
            if v.get("construction") == "default":
                total_d += 1; ach_d += v.get("way_achieved",False)
            elif "variant" in v.get("construction",""):
                total_v += 1; ach_v += v.get("way_achieved",False)
print(f"\nDefault: {ach_d}/{total_d} achieved")
print(f"Variants: {ach_v}/{total_v} achieved")
print(f"Total coverage: {ach_d+ach_v}/{total_d+total_v}")
