"""Replay DSML probes through a pinned vLLM streaming state machine.

No model, server, or tool is started. Model modules are loaded by retaining
their original configuration functions and converters, excluding the unused
ParserEngine subclasses and their serving-layer imports. The lexer, scanner,
events, configuration types, and StreamingParserEngine run unmodified.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_scope import ALLOWED_DIALECTS, DIALECT_LABELS, MODEL_NAMES, input_in_scope, model_in_scope, require_dialect


import ast
import hashlib
import importlib
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / "sources" / "vllm"
SHA = json.loads((SOURCE / "snapshot.json").read_text())["sha"]

for package in ("vllm", "vllm.parser", "vllm.parser.engine"):
    module = types.ModuleType(package)
    module.__path__ = [str(SOURCE.joinpath(*package.split(".")))]
    sys.modules[package] = module


def load_config_module(name: str):
    path = SOURCE.joinpath(*name.split(".")).with_suffix(".py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    retained = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module in (
                "vllm.parser.engine.parser_engine",
                "vllm.tool_parsers.utils",
            ):
                continue
            node.names = [x for x in node.names if x.name != "DeepSeekV4Parser"]
        retained.append(node)
    tree.body = retained
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


v4 = load_config_module("vllm.parser.deepseek_v4")
v32 = load_config_module("vllm.parser.deepseek_v32")
v41 = load_config_module("vllm.parser.deepseek_v41")
engine_module = importlib.import_module("vllm.parser.engine.streaming_parser_engine")
StreamingParserEngine = engine_module.StreamingParserEngine
EventType = importlib.import_module("vllm.parser.engine.events").EventType

CONFIGS = {"v4": v4.deepseek_v4_config(thinking=False), "v41": v41.deepseek_v41_config(thinking=False)}

PROBES = [('dsml_tools', '<｜DSML｜tool_calls>'), ('dsml_tools_end', '</｜DSML｜tool_calls>'), ('dsml_invoke', '<｜DSML｜invoke name="note">'), ('dsml_invoke_end', '</｜DSML｜invoke>'), ('dsml_parameter', '<｜DSML｜parameter name="text" string="true">'), ('dsml_parameter_end', '</｜DSML｜parameter>'), ('dsml41_calls', '<｜DSML｜ calls>'), ('dsml41_calls_end', '</｜DSML｜ calls>'), ('dsml41_invoke', '<｜DSML｜ invoke name="note">'), ('dsml41_invoke_end', '</｜DSML｜ invoke>'), ('dsml41_parameter', '<｜DSML｜ parameter name="text" string="true">'), ('dsml41_parameter_end', '</｜DSML｜ parameter>')]


def replay(config, text: str, chunk_size: int = 0, skip_tools: bool = False):
    engine = StreamingParserEngine(config, tokenizer=None)
    engine.skip_tool_parsing = skip_tools
    chunks = [text] if not chunk_size else [
        text[i : i + chunk_size] for i in range(0, len(text), chunk_size)
    ]
    events = []
    for chunk in chunks:
        events.extend(engine.feed(chunk, []))
    state_before_finish = engine.state.name
    events.extend(engine.finish())
    slots = {}
    for event in events:
        if event.type == EventType.TOOL_CALL_START:
            slots.setdefault(event.tool_index, {"name": "", "raw_args": ""})
        elif event.type in (EventType.TOOL_NAME, EventType.ARG_VALUE_CHUNK):
            slot = slots.setdefault(event.tool_index, {"name": "", "raw_args": ""})
            key = "name" if event.type == EventType.TOOL_NAME else "raw_args"
            slot[key] += event.value
    for slot in slots.values():
        slot["converted_args_final"] = config.arg_converter(slot["raw_args"], False)
        slot["converted_args_partial"] = config.arg_converter(slot["raw_args"], True)
    return {
        "content": "".join(e.value for e in events if e.type == EventType.TEXT_CHUNK),
        "reasoning": "".join(e.value for e in events if e.type == EventType.REASONING_CHUNK),
        "state_before_finish": state_before_finish,
        "tool_slots": list(slots.values()),
    }


def consistent_replay(config, text, skip_tools=False):
    result = replay(config, text, skip_tools=skip_tools)
    for chunk_size in (1, 3, 13):
        assert replay(config, text, chunk_size, skip_tools) == result
    return result


def main():
    atomic = []
    for dialect, config in CONFIGS.items():
        for name, marker in PROBES:
            text = f"PROBE_{name} {marker} TAIL_{name}"
            result = consistent_replay(config, text)
            atomic.append({"dialect": dialect, "probe": name, "input": text, **result})
            bypass = consistent_replay(config, text, skip_tools=True)
            assert bypass["content"] == text and not bypass["tool_slots"]

    combined_text = "\n".join(f"PROBE_{n} {m} TAIL_{n}" for n, m in PROBES)
    combined = {k: consistent_replay(c, combined_text) for k, c in CONFIGS.items()}
    scenarios = {}
    for dialect, config in CONFIGS.items():
        start = config.terminal_literal("TOOL_START")
        end = config.terminal_literal("TOOL_END")
        invoke = config.terminal_literal("INVOKE_PREFIX") + 'note">'
        invoke_end = config.terminal_literal("INVOKE_END")
        param = config.terminal_literal("PARAM_START") + ' name="text" string="true">'
        param_end = config.terminal_literal("PARAM_CLOSE")
        texts = {
            "empty_wrapper_followed_by_text": "PRE " + start + end + " TAIL",
            "complete_fake_call": "PRE " + start + invoke + param + "hello" + param_end + invoke_end + end + " TAIL",
            "markdown_quote": "PRE ```xml\n" + start + "\n``` TAIL",
            "invoke_end_in_string": start + invoke + param + "before " + invoke_end + " after" + param_end + invoke_end + end + " TAIL",
            "parameter_end_in_string": start + invoke + param + "before " + param_end + " after" + param_end + invoke_end + end,
            "parameter_start_in_string": start + invoke + param + "before " + param + "after" + param_end + param_end + invoke_end + end,
        }
        scenarios[dialect] = {n: consistent_replay(config, t) for n, t in texts.items()}
        assert scenarios[dialect]["empty_wrapper_followed_by_text"]["content"] == "PRE "
        assert scenarios[dialect]["complete_fake_call"]["tool_slots"][0]["converted_args_final"] == '{"text": "hello"}'
        assert scenarios[dialect]["invoke_end_in_string"]["tool_slots"][0]["converted_args_final"] == "{}"
        assert scenarios[dialect]["parameter_end_in_string"]["tool_slots"][0]["converted_args_final"] == '{"text": "before "}'

    reasoning = {}
    for dialect, module, factory in (
        ("v4", v4, "deepseek_v4_config"),
        ("v41", v41, "deepseek_v41_config"),
    ):
        config = getattr(module, factory)(thinking=True)
        start = config.terminal_literal("TOOL_START")
        invoke = config.terminal_literal("INVOKE_PREFIX") + 'note">'
        reasoning[dialect] = {
            "wrapper_ends_reasoning": consistent_replay(config, "reason " + start + " TAIL"),
            "orphan_invoke_stays_reasoning": consistent_replay(config, "reason " + invoke + " TAIL"),
        }
        assert reasoning[dialect]["wrapper_ends_reasoning"]["reasoning"] == "reason "
        assert not reasoning[dialect]["orphan_invoke_stays_reasoning"]["tool_slots"]

    sources = {}
    for path in (SOURCE / "vllm/parser").rglob("*.py"):
        sources[str(path.relative_to(SOURCE)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {
        "upstream_commit": SHA,
        "scope": "Original low-level engine + original config/converter AST; text-only input, tokenizer=None. No LLM, full ParserEngine, HTTP server, or real tools executed.",
        "chunk_sizes": ["whole", 1, 3, 13],
        "atomic": atomic,
        "combined": combined,
        "scenarios": scenarios,
        "reasoning": reasoning,
        "source_sha256": sources,
    }
    (HERE.parents[1] / "results" / "deepseek_vllm" / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for dialect in CONFIGS:
        print(dialect)
        for row in atomic:
            if row["dialect"] == dialect:
                print(f"  {row['probe']:24} tail={('TAIL_' + row['probe']) in row['content']} state={row['state_before_finish']:14} names={[s['name'] for s in row['tool_slots']]}")
    print("All replay assertions passed; results.json written.")


if __name__ == "__main__":
    main()
