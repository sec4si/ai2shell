"""JSON-lines adapter for original Python parsers, without model/GPU imports.

Only package initializers, logging, registry, environment configuration, and
unused grammar types are shimmed. Parser method bodies are imported unmodified.
SGLang/TRT tool definitions use compatible Pydantic carriers from LMDeploy;
their actual parser result models and conversion helpers are upstream originals.
No tokenizer, guided decoder, model, HTTP service, or tool executor is run.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_scope import ALLOWED_DIALECTS, DIALECT_LABELS, MODEL_NAMES, input_in_scope, model_in_scope, require_dialect


import importlib
import ast
import json
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "sources"
sys.path.insert(0, str(ROOT / "probes" / "deepseek_vllm"))


def package(name, path=None, **attrs):
    module = types.ModuleType(name)
    module.__path__ = [str(path)] if path else []
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


def bootstrap(name, root, subpackages):
    package(name, root)
    for sub in subpackages:
        package(name + "." + sub, root.joinpath(*sub.split(".")))


class Registry:
    def __init__(self, *args, **kwargs):
        self.module_dict = {}

    def register_module(self, name=None, **kwargs):
        def register(cls):
            for key in (name if isinstance(name, list) else [name or cls.__name__]):
                self.module_dict[key] = cls
            return cls
        return register

    def get(self, name):
        return self.module_dict[name]


def init():
    logging.disable(logging.CRITICAL)
    package("mmengine", Registry=Registry)
    lmroot = SOURCES / "lmdeploy/lmdeploy"
    bootstrap("lmdeploy", lmroot, ["serve", "serve.openai", "serve.parsers", "serve.parsers.tool_parser"])
    package("lmdeploy.utils", get_logger=logging.getLogger)
    protocol = importlib.import_module("lmdeploy.serve.openai.protocol")
    for name in ["deepseek_v32", "deepseek_v4", "kimi_k2", "qwen3", "qwen3coder"]:
        mod = importlib.import_module(f"lmdeploy.serve.parsers.tool_parser.{name}_tool_parser")
        for key, value in vars(mod).items():
            if isinstance(value, type):
                setattr(sys.modules["lmdeploy.serve.parsers.tool_parser"], key, value)

    sgroot = SOURCES / "sglang/python/sglang"
    bootstrap("sglang", sgroot, ["srt", "srt.entrypoints", "srt.entrypoints.openai", "srt.function_call"])
    package("sglang.srt.entrypoints.openai.protocol", Tool=protocol.Tool, ToolChoice=protocol.ToolChoice)
    package("sglang.srt.environ", envs=types.SimpleNamespace(SGLANG_FORWARD_UNKNOWN_TOOLS=types.SimpleNamespace(get=lambda: False)))
    trroot = SOURCES / "tensorrt_llm/tensorrt_llm"
    bootstrap("tensorrt_llm", trroot, ["serve", "serve.tool_parser"])
    log = logging.getLogger("trt-replay")
    log.warning_once = log.warning
    package("tensorrt_llm.logger", logger=log)
    package("tensorrt_llm.serve.openai_protocol", ChatCompletionToolsParam=protocol.Tool)
    
    class _MockMeta(type):
        def __getattr__(cls, name):
            return _MockStructuralTag

    class _MockStructuralTag(metaclass=_MockMeta):
        """Permissive stand-in for xgrammar structural tag classes."""
        def __init__(self, *args, **kwargs): pass
        def __getattr__(self, name): return _MockStructuralTag()
        def __call__(self, *args, **kwargs): return _MockStructuralTag()
        def __or__(self, other): return self
        def __repr__(self): return "MockStructuralTag"

    class _AnyAttrModule(types.ModuleType):
        def __getattr__(self, name):
            return _MockStructuralTag

    for _name in ("xgrammar", "xgrammar.structural_tag"):
        _mod = _AnyAttrModule(_name)
        _mod.__path__ = []
        sys.modules[_name] = _mod
    return protocol


PROTOCOL = None


def merge_calls(chunks):
    slots = {}
    for delta in chunks:
        d = delta.model_dump() if hasattr(delta, "model_dump") else delta
        if "function" in d:
            index, name, args = d.get("index", 0), d["function"].get("name"), d["function"].get("arguments")
        else:
            index, name, args = d["tool_index"], d.get("name"), d["parameters"]
        slot = slots.setdefault(index, {"name": "", "arguments": ""})
        if name:
            slot["name"] += name
        if args:
            slot["arguments"] += args
    return list(slots.values())


def run_python(request):
    framework, dialect = request["framework"], request["dialect"]
    require_dialect(dialect)
    chunks, tools = request["chunks"], request["tools"]
    mode = request.get("mode", "stream")
    if framework == "vllm":
        import replay_dsml as base
        if dialect in base.CONFIGS:
            config = base.CONFIGS[dialect]
        else:
            name = {"kimi": "kimi_k2", "kimi_k3": "kimi_k3", "qwen_coder": "qwen3", "qwen": "qwen3"}[dialect]
            path = SOURCES / "vllm_latest" / "vllm" / "parser" / (name + ".py")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            _strip = ("vllm.parser.engine.parser_engine", "vllm.entrypoints.generate.base.protocol",
                      "vllm.reasoning.kimi_k3_reasoning_parser", "vllm.entrypoints.openai.chat_completion.protocol",
                      "vllm.entrypoints.openai.responses.protocol", "vllm.parser.abstract_parser")
            tree.body = [n for n in tree.body if not isinstance(n, ast.ClassDef) and not (isinstance(n, ast.ImportFrom) and n.module in _strip)]
            namespace = {}
            exec(compile(tree, str(path), "exec"), namespace)
            config = namespace[name + "_config"](thinking=False)
        engine = base.StreamingParserEngine(config, tokenizer=None)
        events = []
        for chunk in chunks:
            events.extend(engine.feed(chunk, []))
        events.extend(engine.finish())
        slots = {}
        for event in events:
            if event.type == base.EventType.TOOL_CALL_START:
                slots.setdefault(event.tool_index, {"name": "", "arguments": ""})
            elif event.type in (base.EventType.TOOL_NAME, base.EventType.ARG_VALUE_CHUNK):
                slot = slots.setdefault(event.tool_index, {"name": "", "arguments": ""})
                slot["name" if event.type == base.EventType.TOOL_NAME else "arguments"] += event.value
        for slot in slots.values():
            if dialect == "kimi":
                slot["name"] = slot["name"].strip().split(":")[0].removeprefix("functions.")
            if config.arg_converter:
                slot["arguments"] = config.arg_converter(slot["arguments"], False)
        return {"content": "".join(e.value for e in events if e.type == base.EventType.TEXT_CHUNK), "reasoning": "".join(e.value for e in events if e.type == base.EventType.REASONING_CHUNK), "calls": list(slots.values()), "parser_path": "low_level_engine_text_path"}
    if framework == "lmdeploy":
        from lmdeploy.serve.parsers.response_parser import BaseResponseParser
        names = {"v32": "deepseek-v32", "v4": "deepseek-v4", "kimi": "kimi-k2", "qwen": "qwen", "qwen_coder": "qwen3coder"}
        from lmdeploy.serve.parsers.tool_parser.tool_parser import ToolParserManager
        cls = type("ReplayResponse", (BaseResponseParser,), {"tool_parser_cls": ToolParserManager.get(names[dialect]), "reasoning_parser_cls": None, "tokenizer": None})
        req = PROTOCOL.ChatCompletionRequest(model="replay", messages=[{"role": "user", "content": "replay"}], tools=tools, tool_choice=request.get("tool_choice", "auto"))
        parser = cls(req)
        if mode == "batch":
            content, calls, reasoning = parser.parse_complete("".join(chunks))
            return {"content": content or "", "reasoning": reasoning or "", "calls": [{"name": c.function.name, "arguments": c.function.arguments} for c in calls or []]}
        content, reasoning, deltas = [], [], []
        for i, chunk in enumerate(chunks):
            for message, _ in parser.stream_chunk(chunk, [], final=i == len(chunks)-1):
                content.append(message.content or "")
                reasoning.append(message.reasoning_content or "")
                deltas.extend(message.tool_calls or [])
        return {"content": "".join(content), "reasoning": "".join(reasoning), "calls": merge_calls(deltas)}
    if framework == "sglang":
        names = {"v32": ("deepseekv32_detector", "DeepSeekV32Detector"), "v4": ("deepseekv4_detector", "DeepSeekV4Detector"), "v41": ("deepseekv41_detector", "DeepSeekV41Detector"), "kimi": ("kimik2_detector", "KimiK2Detector"), "kimi_k3": ("kimik3_detector", "KimiK3Detector"), "deepseek3": ("deepseekv3_detector", "DeepSeekV3Detector"), "qwen": ("qwen25_detector", "Qwen25Detector"), "qwen_coder": ("qwen3_coder_detector", "Qwen3CoderDetector")}
        module_name, class_name = names[dialect]
        parser = getattr(importlib.import_module("sglang.srt.function_call." + module_name), class_name)()
    elif framework == "tensorrt_llm":
        names = {"v32": ("deepseekv32_parser", "DeepSeekV32Parser"), "v4": ("deepseekv4_parser", "DeepSeekV4Parser"), "v41": ("deepseekv41_parser", "DeepSeekV41Parser"), "kimi": ("kimi_k2_tool_parser", "KimiK2ToolParser"), "kimi_k3": ("kimi_k3_tool_parser", "KimiK3ToolParser"), "deepseek3": ("deepseekv3_parser", "DeepSeekV3Parser"), "qwen": ("qwen3_tool_parser", "Qwen3ToolParser"), "qwen_coder": ("qwen3_coder_parser", "Qwen3CoderToolParser")}
        module_name, class_name = names[dialect]
        parser = getattr(importlib.import_module("tensorrt_llm.serve.tool_parser." + module_name), class_name)()
    else:
        raise ValueError(framework)
    typed_tools = [PROTOCOL.Tool(**tool) for tool in tools]
    if mode == "batch":
        result = parser.detect_and_parse("".join(chunks), typed_tools)
        return {"content": result.normal_text, "reasoning": "", "calls": [{"name": c.name, "arguments": c.parameters} for c in result.calls]}
    results = [parser.parse_streaming_increment(chunk, typed_tools) for chunk in chunks]
    if hasattr(parser, "finish"):
        results.append(parser.finish(typed_tools))
    return {"content": "".join(r.normal_text for r in results), "reasoning": "", "calls": merge_calls([c for r in results for c in r.calls])}


def main():
    global PROTOCOL
    PROTOCOL = init()
    for line in sys.stdin:
        try:
            result = run_python(json.loads(line))
        except Exception as error:
            result = {"error": type(error).__name__ + ": " + str(error)}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
