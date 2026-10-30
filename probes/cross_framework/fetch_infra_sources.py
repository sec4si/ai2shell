"""Fetch immutable, hashed upstream parser sources; never fetch model weights.

The initial commit/tree lookup is saved before any files are downloaded. Reruns
reuse that commit. Each directory is a partial source snapshot, not an installed
serving framework. Original upstream files are never rewritten by this helper.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "sources"
REPOS = {
    "sglang": "sgl-project/sglang",
    "lmdeploy": "InternLM/lmdeploy",
    "dynamo": "ai-dynamo/dynamo",
    "llama_cpp": "ggml-org/llama.cpp",
    "ollama": "ollama/ollama",
    "tensorrt_llm": "NVIDIA/TensorRT-LLM",
}


def fetch(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DSML-Infra-Research"})
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def selected(name, path):
    if path in {"AGENTS.md", "LICENSE", "LICENSE.md", "LICENSE.txt", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum"}:
        return True
    prefixes = {
        "sglang": ("python/sglang/srt/function_call/", "test/registered/unit/function_call/"),
        "lmdeploy": ("lmdeploy/serve/parsers/", "tests/test_lmdeploy/serve/parsers/"),
        "dynamo": ("lib/llm/src/protocols/openai/chat_completions/", "lib/llm/tests/test_streaming_tool_parsers", "docs/fern/pages/use-cases/tool-calling-and-reasoning/"),
        "llama_cpp": ("common/", "include/", "src/", "ggml/", "vendor/", "cmake/", "tests/"),
        "ollama": ("model/parsers/", "tools/", "api/", "internal/parser/"),
        "tensorrt_llm": ("tensorrt_llm/serve/tool_parser/", "tests/unittest/serve/tool_parser/"),
    }
    if path.startswith(prefixes[name]):
        return True
    extra = {
        "sglang": {"python/sglang/srt/entrypoints/openai/protocol.py"},
        "lmdeploy": {"lmdeploy/deepseek_v32_encoding.py", "lmdeploy/deepseek_v4_encoding.py", "lmdeploy/serve/openai/protocol.py"},
        "dynamo": {"lib/llm/Cargo.toml", "lib/bindings/python/rust/parsers.rs"},
        "llama_cpp": {"CMakeLists.txt", ".gitmodules"},
        "ollama": set(),
        "tensorrt_llm": {"tensorrt_llm/serve/openai_protocol.py"},
    }
    return path in extra[name]


def main():
    jobs, manifests = [], {}
    for name, repo in REPOS.items():
        folder = ROOT / name
        folder.mkdir(parents=True, exist_ok=True)
        inventory = folder / "tree.json"
        if not inventory.exists():
            commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/HEAD"))["sha"]
            tree = json.loads(fetch(f"https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1"))
            inventory.write_text(json.dumps({"repo": repo, "commit": commit, "tree": tree["tree"]}, indent=2), encoding="utf-8")
        meta = json.loads(inventory.read_text(encoding="utf-8"))
        paths = [x["path"] for x in meta["tree"] if x["type"] == "blob" and selected(name, x["path"])]
        manifests[name] = {"repository": repo, "commit": meta["commit"], "partial_snapshot": True, "files": {}}
        jobs.extend((name, path, f'https://raw.githubusercontent.com/{repo}/{meta["commit"]}/{path}') for path in paths)

    def download(job):
        name, path, url = job
        target = ROOT / name / path
        if not target.exists():
            data = fetch(url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        data = target.read_bytes()
        return name, path, hashlib.sha256(data).hexdigest()

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for name, path, digest in pool.map(download, jobs):
            manifests[name]["files"][path] = digest
    for name, manifest in manifests.items():
        (ROOT / name / "snapshot.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(name, manifest["commit"], len(manifest["files"]), flush=True)


if __name__ == "__main__":
    main()
