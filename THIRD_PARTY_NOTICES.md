# Third-party source notices

The upstream source snapshots in `sources/` retain their existing copyright,
SPDX notices, and license files. They are partial research snapshots, not code
authored by this project. Exact revisions and file hashes are recorded in the
adjacent `snapshot.json` manifests; historical naming does not imply recency.

| Snapshot | Upstream | License information retained here |
| --- | --- | --- |
| vLLM / vllm_latest | [vllm-project/vllm](https://github.com/vllm-project/vllm) | SPDX headers; [supplemental license](licenses/vllm.LICENSE) |
| SGLang | [sgl-project/sglang](https://github.com/sgl-project/sglang) | [LICENSE](sources/sglang/LICENSE) |
| LMDeploy | [InternLM/lmdeploy](https://github.com/InternLM/lmdeploy) | [LICENSE](sources/lmdeploy/LICENSE) |
| TensorRT-LLM | [NVIDIA/TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) | [LICENSE](sources/tensorrt_llm/LICENSE) |
| llama.cpp | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | [LICENSE](sources/llama_cpp/LICENSE); vendor subdirectories retain separate notices |
| Ollama | [ollama/ollama](https://github.com/ollama/ollama) | [LICENSE](sources/ollama/LICENSE) |
| Dynamo and parser crates | [ai-dynamo/dynamo](https://github.com/ai-dynamo/dynamo) | [LICENSE](sources/dynamo/LICENSE), crate Cargo metadata and source headers |

The Ollama runner includes parser support files under
`probes/native/ollama/parsers/` whose original file headers must be retained.
Other dependencies installed through Python, Go, or Rust retain their own
licenses; their lock files do not transfer copyright to this project.

No new open-source license for project-authored code or research data was
selected during repository preparation. Third-party licenses continue to
apply to their respective files.
