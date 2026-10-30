"""Export saved model-dialect/infra input-output examples; no experiment reruns.

Writes docs/reports/输入输出对照.md and results/exports/io_examples.json using original saved strings.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_scope import ALLOWED_DIALECTS, DIALECT_LABELS, MODEL_NAMES, input_in_scope, model_in_scope, require_dialect


import collections
import json
import re
from pathlib import Path

import report_audit

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/cross_framework/infra_results"
FRAMEWORKS = ("vllm", "sglang", "lmdeploy", "tensorrt_llm", "llama_cpp", "ollama", "dynamo")
LABELS = {"vllm": "vLLM", "sglang": "SGLang", "lmdeploy": "LMDeploy",
          "tensorrt_llm": "TensorRT-LLM", "llama_cpp": "llama.cpp", "ollama": "Ollama", "dynamo": "Dynamo"}
DIALECTS = dict(DIALECT_LABELS)
WAYS = {1: "方式一 截断正文", 2: "方式二 损坏调用或参数", 3: "方式三 改写参数",
        4: "方式四 从正文构造完整调用", 5: "方式五 从单调用中带出额外调用"}
TAG_DIALECTS = {"v32", "v4", "v41", "kimi_k3", "qwen_coder"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def primary_case(dialect, way):
    return {1: "wrapper_only",
            2: "parameter_close_in_string" if dialect in TAG_DIALECTS else "invoke_close_in_string",
            3: "add_parameter" if dialect in TAG_DIALECTS else "parameter_spelling_in_string",
            4: "full_call_in_prose", 5: "extra_call_in_string"}[way]


def project(result):
    # Preserve original values, types, invalid JSON and errors without repair.
    return {key: result[key] for key in ("content", "reasoning", "calls", "error") if key in result}


def mode_label(run):
    mode = run["mode"]
    if mode == "batch":
        return "批处理"
    if "chunk_size" in run:
        size = run["chunk_size"]
        return "流式整段" if size == "whole" else f"流式每 {size} 字符"
    return {"stream": "流式整段", "stream13": "流式每 13 字符",
            "streamnl": "流式按行", "streammk": "流式按标记"}[mode]


def fenced(value, language="text"):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    length = max([3, *[len(m.group()) + 1 for m in re.finditer(r"`{3,}", text)]])
    fence = "`" * length
    return f"{fence}{language}\n{text}\n{fence}\n"


def way_anchor(dialect, way):
    title = (DIALECTS[dialect] + " " + WAYS[way]).lower()
    return re.sub(r"[^\w\- ]", "", title).replace(" ", "-")


def source_line(entry):
    return f"来源：[{entry['source']}](../../{entry['source']})，记录 `{entry['case']}`。"


def output_blocks(entry, level=4):
    lines = [f"{'#' * level} {LABELS[entry['framework']]}", "", source_line(entry), ""]
    groups = collections.OrderedDict()
    for run in entry["runs"]:
        output = project(run["result"])
        key = json.dumps(output, ensure_ascii=False, sort_keys=True)
        group = groups.setdefault(key, {"modes": [], "output": output})
        group["modes"].append(mode_label(run))
    for group in groups.values():
        lines.extend(["输出适用：" + "、".join(group["modes"]) + "。", "",
                      fenced(group["output"], "json")])
    return lines


def collect():
    reports = {}
    for path in sorted(RESULTS.glob("*.json")):
        report = load(path)
        if "framework" in report and "rows" in report:
            reports[report["dialect"], report["framework"]] = (path, report)
    entries, controls, additional = [], [], []
    for (dialect, framework), (path, report) in reports.items():
        rows = {row["case"]: row for row in report["rows"]}
        normal = rows["normal_note_control"]
        control_by_mode = {report_audit.mode_key(r): r["observations"].get("control_passed") is True
                           for r in normal["runs"]}
        controls.append({"dialect": dialect, "framework": framework, "case": normal["case"],
                         "input": normal["input"], "runs": normal["runs"],
                         "source": path.relative_to(ROOT).as_posix()})
        for way in WAYS:
            row = rows[primary_case(dialect, way)]
            entry = {"kind": "default", "dialect": dialect, "framework": framework, "way": way,
                     "case": row["case"], "input": row["input"], "intended_calls": row["intended_calls"],
                     "runs": row["runs"], "source": path.relative_to(ROOT).as_posix()}
            entries.append(entry)
            # Include other default constructs when they establish an effect
            # absent in at least one corresponding primary mode.
            primary_runs = {report_audit.mode_key(r): r for r in row["runs"]}
            for other in rows.values():
                if other.get("way") != way or other["case"] in (row["case"], "full_call_undeclared"):
                    continue
                improved = any(
                    control_by_mode.get(report_audit.mode_key(r))
                    and report_audit.observed(other, r["result"])
                    and not report_audit.observed(row, primary_runs[report_audit.mode_key(r)]["result"])
                    for r in other["runs"])
                if improved:
                    additional.append({**entry, "kind": "other_default", "case": other["case"],
                                       "input": other["input"], "intended_calls": other["intended_calls"],
                                       "runs": other["runs"]})
    supplement = load(RESULTS / "cell_completion.json")
    supplement_controls = []
    control_names = {"normal_control", "literal_control", "ref_normal_control", "qc_exact",
                     "kp_bare_call", "v32_normal", "l2_w2_sentinel_control", "lq_w2_sentinel_control",
                     "qc_w2_sentinel_control", "v32_w2_control", "w3_escaped_control"}
    for case in supplement["cases"]:
        match = re.search(r"(?:^|_)w([1-5])(?:_|$)", case["case"])
        for framework in case["targets"]:
            runs = [r for r in supplement["runs"].get(framework, [])
                    if r["dialect"] == case["dialect"] and r["case"] == case["case"]]
            if not runs:
                continue
            entry = {**case, "kind": "supplement", "framework": framework, "runs": runs,
                     "source": "results/cross_framework/infra_results/cell_completion.json"}
            if case["case"] in control_names:
                supplement_controls.append(entry)
            elif match:
                entry["way"] = int(match.group(1))
                additional.append(entry)
    online = []
    paths = [ROOT / "results/deepseek_vllm/e2e_results.json",
             *sorted((ROOT / "results/online").glob("*/online_results.json"))]
    for path in paths:
        record = load(path)
        if not model_in_scope(record["model"]):
            continue
        # Agent sessions use a different schema and remain in results/online/.
        for name, probe in record.get("probes", {}).items():
            # Never copy base_url or credentials to the derived artifact.
            request = probe.get("request", probe.get("request_payload"))
            if request is None:
                if "request_text" in probe:
                    request = {"saved_user_text": probe["request_text"], "request_body_saved": False}
                else:
                    raise ValueError(f"Missing saved request: {path} {name}")
            online.append({"model": record["model"], "infra": "上游 Infra 未记录",
                           "protocol": record.get("protocol", "openai_compatible"),
                           "case": name, "request": request,
                           "result": probe.get("response", probe.get("stream_result", {"error": probe.get("error")})),
                           "source": path.relative_to(ROOT).as_posix()})
    return {"default": entries, "additional": additional, "normal_controls": controls,
            "supplement_controls": supplement_controls, "online": online}


def render(data):
    lines = ["# 不同模型方言在不同 Infra 下的五种触发方式输入输出", "",
             "本表按模型方言列出五种方式的完整输入，以及各 Infra 的实际输出。每种方式先比较固定的默认输入，再列出已保存的其他默认构造与定向变体。默认输入未触发、解析报错和对照失败的结果一并展示。", "",
             "这里的模型名称表示解析器接受的输出方言，离线实验没有加载对应模型。在线请求单独列在文末；其上游 Infra 未记录，不能归入某一个已知框架。", "",
             "## 如何读取输入输出", "",
             "输入代码块保留原始行序与开头空行；代码围栏结束前的排版换行不表示输入额外含换行，精确字符串见配套 JSON。输出保留 `content`、`reasoning`、`calls` 与 `error` 的原值；换行和引号遵循 JSON 显示编码。参数 `arguments` 仍按原记录保留字符串或对象，未修复无效 JSON。", "",
             "只有输出字段逐项完全一致的模式才合并展示。内部 `raw_deltas`、`partial_snapshots` 等字段不在正文展开，完整原始结果保存在 [io_examples.json](../../results/exports/io_examples.json)，每条示例也链接到来源。", "",
             "普通正文与正常单调用对照失败时，异常输出只作为原始观测展示，不代表该方式成功。参数本身已含新键的 JSON 变体与合法字符串内标签触发不同；`thinking`、`rf`、模板排布也必须按变体说明解释。Dynamo 批处理使用 v1 库，流式使用 v2 库。", "",
             "离线声明工具为 `note(text,to)`、`send_email(to,subject)`、`web_fetch(url)` 与 `ping()`；参数和工具均未执行。方式三、五预期只有单个 `note.text` 保存完整数据，方式一、四预期保留正文且不形成调用。", "",
             "## 模型与五种方式导航", "",
             "| 模型方言 | Infra 组合数 | 五种方式 |", "| --- | --- | --- |"]
    for dialect, label in DIALECTS.items():
        count = len({e["framework"] for e in data["default"] if e["dialect"] == dialect})
        links = " / ".join(f"[方式{w}](#{way_anchor(dialect, w)})" for w in WAYS)
        lines.append(f"| {label} | {count} | {links} |")
    lines.extend(["", f"每个默认框架×方言组合列出五种方式，共 {len(data['default'])} 项默认输入输出；同项包含批处理与四种流式记录。完整分析见 [报告.md](报告.md)。", ""])
    for dialect, label in DIALECTS.items():
        lines.extend([f"## {label}", "", "正常单调用对照：", "",
                      "| Infra | 批处理 | 流式整段 | 每 1 字符 | 每 3 字符 | 每 13 字符 |",
                      "| --- | --- | --- | --- | --- | --- |"])
        controls = {e["framework"]: e for e in data["normal_controls"] if e["dialect"] == dialect}
        for framework in FRAMEWORKS:
            if framework not in controls:
                lines.append(f"| {LABELS[framework]} | 未保存该配对 | — | — | — | — |")
                continue
            flags = ["通过" if r["observations"].get("control_passed") is True else "未通过"
                     for r in controls[framework]["runs"]]
            lines.append("| " + " | ".join([LABELS[framework], *flags]) + " |")
        lines.append("")
        for way, way_label in WAYS.items():
            lines.extend([f"### {label} {way_label}", ""])
            entries = [e for e in data["default"] if e["dialect"] == dialect and e["way"] == way]
            groups = collections.OrderedDict()
            for framework in FRAMEWORKS:
                for entry in entries:
                    if entry["framework"] == framework:
                        groups.setdefault(entry["input"], []).append(entry)
            for index, (text, grouped) in enumerate(groups.items(), 1):
                heading = "默认输入" if len(groups) == 1 else f"默认输入排布 {index}"
                lines.extend([f"**{heading}**，适用于：" + "、".join(LABELS[e["framework"]] for e in grouped) + "。", "",
                              fenced(text)])
                intended = grouped[0].get("intended_calls")
                if way in (2, 3, 5) and intended is not None:
                    lines.extend(["原任务预期调用：", "", fenced(intended, "json")])
                for entry in grouped:
                    lines.extend(output_blocks(entry))
            extras = [e for e in data["additional"] if e["dialect"] == dialect and e["way"] == way]
            if extras:
                lines.extend(["#### 其他构造的输入输出", "",
                              "以下输入或配置不同于上面的默认构造，结果单独展示。未转义 JSON、提前闭合、额外换行及思考配置均是实际测试条件。", ""])
                groups = collections.OrderedDict()
                for entry in extras:
                    key = (entry["kind"], entry["case"], entry["input"], entry.get("thinking", False), entry.get("rf"))
                    groups.setdefault(key, []).append(entry)
                for (kind, case, text, thinking, rf), grouped in groups.items():
                    lines.extend([f"**{'主矩阵其他构造' if kind == 'other_default' else '定向变体'} `{case}`**", "",
                                  "适用于：" + "、".join(LABELS[e["framework"]] for e in grouped) + "。", ""])
                    if kind == "supplement":
                        lines.extend([f"配置：`thinking={str(thinking).lower()}`，`rf={json.dumps(rf, ensure_ascii=False)}`。", ""])
                        if grouped[0].get("note"):
                            lines.extend(["记录条件：" + grouped[0]["note"], ""])
                    lines.append(fenced(text))
                    for entry in grouped:
                        lines.extend(output_blocks(entry, level=5))
        controls_extra = [e for e in data["supplement_controls"] if e["dialect"] == dialect]
        if controls_extra:
            lines.extend(["### 模板配对和字面量对照输入输出", "",
                          "以下对照用于核对定向变体的模板或序列化条件，原始输出不自动等同于已通过。", ""])
            groups = collections.OrderedDict()
            for entry in controls_extra:
                key = (entry["case"], entry["input"], entry.get("thinking", False), entry.get("rf"))
                groups.setdefault(key, []).append(entry)
            for (case, text, thinking, rf), grouped in groups.items():
                lines.extend([f"**对照 `{case}`**", "", f"配置：`thinking={str(thinking).lower()}`，`rf={json.dumps(rf, ensure_ascii=False)}`。", "",
                              fenced(text)])
                for entry in grouped:
                    lines.extend(output_blocks(entry))
    lines.extend(["## 在线 API 的请求输入与响应输出", "",
                  "以下为保存的单请求探针输入及响应字段；仅有用户文字时明确标记 request_body_saved=false。Agent 多轮会话另保存在 results/online 中，不合并到单请求统计。上游 Infra 未记录。未保存服务端原始生成流，不能直接等同于前述某个框架的输出。", "",
                  "Kimi-K3 的相应请求返回 `send_email`，需要按调用名变化与实际参数解释。不能把邮箱子串命中直接当成独立新字段。", "",
                  "目标地址不在本文展开。非流式 reasoning 只在原记录保存开头时保留其已有字段；流式结果是已保存的聚合结果。", ""])
    for entry in data["online"]:
        lines.extend([f"### {entry['model']} {entry['protocol']} {entry['case']}", "", source_line(entry), "",
                      "保存的请求输入：", "", fenced(entry["request"], "json"),
                      "保存的响应输出：", "", fenced(entry["result"], "json")])
    lines.extend(["## 复算方式", "", "在项目根目录运行下列命令，可从原结果重新生成本文与完整输入输出 JSON：", "",
                  fenced("& .\\.venv\\Scripts\\python.exe -X utf8 .\\probes\\analysis\\export_io_examples.py", "powershell")])
    return "\n".join(lines).rstrip() + "\n"


def main():
    data = collect()
    assert len(data["default"]) == len(data["normal_controls"]) * len(WAYS)
    assert all(len(e["runs"]) == 5 for e in data["default"])
    output = render(data)
    (ROOT / "docs/reports/输入输出对照.md").write_text(output, encoding="utf-8")
    (ROOT / "results/exports/io_examples.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"default_examples": len(data["default"]), "additional_examples": len(data["additional"]),
                      "normal_controls": len(data["normal_controls"]), "supplement_controls": len(data["supplement_controls"]),
                      "online_examples": len(data["online"]), "markdown_characters": len(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
