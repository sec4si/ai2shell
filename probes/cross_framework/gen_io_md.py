"""Generate five_ways_io.md organized by WAY then DIALECT (user-specified format)."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

import json

ev = json.load(open(str(ROOT / "results/exports/five_ways_evidence.json"), encoding="utf-8"))

WAYS = [
    ("way1_truncate","方式一：截断正文"),
    ("way2_damage","方式二：损坏调用"),
    ("way3_rewrite","方式三：改写参数"),
    ("way4_synth","方式四：构造完整调用"),
    ("way5_append","方式五：追加第二调用"),
]
DL_ORDER = ['DeepSeek-V4', 'DeepSeek-V4.1', 'Kimi-K2', 'Kimi-K3', 'Qwen-Coder', 'Qwen']
FW_ORDER = ["vllm","sglang","lmdeploy","tensorrt_llm","ollama","llama_cpp","dynamo"]
FW_NAMES = {"vllm":"vLLM","sglang":"SGLang","lmdeploy":"LMDeploy","tensorrt_llm":"TensorRT-LLM",
            "ollama":"Ollama","llama_cpp":"llama.cpp","dynamo":"Dynamo"}

# way2 variant types whose damage is self-evident in the I/O pair (value
# visibly truncated mid-content, emptied, invalid JSON, or the call lost);
# ordered — the dedicated-parser finding outranks the generic-route one
PREFER_WAY2 = ("param_emptied","rebalanced_param_close",
               "unescaped_quote_marker","unescaped_quote_unbalanced","raw_newline_eot_in_value",
               "nested_markers","generic_scanner")

def clean(s, n=None):
    if s is None: return ""
    value = str(s).replace("\n","⏎")
    return value if n is None else value[:n]

def table_row(*cells):
    # Pipes inside model markers are data, not Markdown column separators.
    return "| " + " | ".join(clean(cell).replace("|", "\\|") for cell in cells) + " |"

def fmt_calls(calls):
    if not calls: return "无"
    parts = []
    for c in calls:
        if isinstance(c, dict):
            name = c.get("name","?")
            a = c.get("arguments","")
            if isinstance(a, dict): a = json.dumps(a, ensure_ascii=False)
            try:
                json.loads(str(a)); tag=""
            except: tag="（无效JSON）"
            parts.append(f"{name}({str(a)}){tag}")
        else:
            parts.append(str(c))
    return "；".join(parts)

L = []
L.append("# 五种触发方式：各模型方言在各 Infra 下的输入与输出\n")

for way_key, way_label in WAYS:
    L.append(f"## {way_label}\n")

    for dl_name in DL_ORDER:
        fw_with_dl = [fw for fw in FW_ORDER if fw in ev and dl_name in ev[fw]]
        if not fw_with_dl:
            continue

        # Check if any framework has data for this way
        has_any = False
        for fw in fw_with_dl:
            if fw == "ollama" and dl_name == "DeepSeek-V4": continue
            ways = ev[fw][dl_name].get("ways", {})
            if any(wk.startswith(way_key) for wk in ways):
                has_any = True
        if not has_any:
            continue

        L.append(f"### {dl_name}\n")
        L.append("| Infra | 输入 | 输出 |")
        L.append("| --- | --- | --- |")

        for fw in fw_with_dl:
            if fw == "ollama" and dl_name == "DeepSeek-V4":
                L.append(table_row(FW_NAMES[fw], "—", "N/A（无DSML解析器）"))
                continue

            ways = ev[fw][dl_name].get("ways", {})

            # Find the best entry: for way2 prefer damage-self-evident variant
            # types (value visibly truncated / emptied / call lost) over a
            # default whose delivered value coincides with the legitimate
            # prefix; otherwise default if achieved, then any variant.
            best = None
            default = ways.get(way_key)
            if way_key == "way2_damage":
                for ptype in PREFER_WAY2:
                    for wk, v in sorted(ways.items()):
                        if (wk.startswith(way_key) and "__variant" in wk and v.get("way_achieved")
                                and v.get("construction","").replace("variant:","") == ptype):
                            best = v
                            break
                    if best is not None:
                        break
            if best is None and default and default.get("way_achieved"):
                best = default
            if best is None:
                for wk, v in sorted(ways.items()):
                    if wk.startswith(way_key) and "__variant" in wk and v.get("way_achieved"):
                        best = v
                        break

            if best is None:
                # Show default result even if not achieved
                if default:
                    inp = clean(default.get("input",""))
                    ct = clean(default.get("output_content","") or "")
                    calls = fmt_calls(default.get("output_calls",[]))
                    err = default.get("error","")
                    if err:
                        L.append(table_row(f"**{FW_NAMES[fw]}**", f"**`{inp}`**", "**解析错误**"))
                    else:
                        L.append(table_row(f"**{FW_NAMES[fw]}**", f"**`{inp}`**", f"**正文:`{ct}` 调用:{calls}（未达成）**"))
                else:
                    L.append(table_row(f"**{FW_NAMES[fw]}**", "—", "**无数据**"))
            else:
                inp = clean(best.get("input",""))
                ct = clean(best.get("output_content","") or "")
                rs = clean(best.get("output_reasoning","") or "", 1500)
                calls = fmt_calls(best.get("output_calls",[]))
                cons = best.get("construction","")
                tag = "" if cons == "default" else f"（变体:{cons.replace('variant:','')}）"

                parts = []
                if ct: parts.append(f"正文:`{ct}`")
                if rs: parts.append(f"reasoning:`{rs}`")
                if calls != "无": parts.append(f"调用:{calls}")
                if not parts: parts.append("正文为空、无调用")
                out = " ".join(parts)
                L.append(table_row(f"**{FW_NAMES[fw]}**", f"**`{inp}`{tag}**", f"**{out}**"))

        L.append("")

output = "\n".join(L)
with open(str(ROOT / "docs/reports/five_ways_io.md"), "w", encoding="utf-8") as f:
    f.write(output)
print(f"Written: {len(output)} chars, {output.count(chr(10))+1} lines")
