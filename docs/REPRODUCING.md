# 环境与复现

所有命令从仓库根目录执行。Python 依赖统一由 `pyproject.toml` 和 `uv.lock` 描述，不需要复制原机器上的虚拟环境或 `.tools`。

## Python

```bash
uv sync --extra infra
uv run --extra infra python scripts/verify_repository.py
uv run --extra infra python probes/analysis/report_audit.py
```

`infra` 依赖用于导入固定源码中的类型与辅助函数；其中包含 OpenAI SDK 类型定义，但离线回放不创建在线 API 客户端。模型与工具均不会因为安装依赖或运行审计而执行。

## Python 解析器回放

```bash
uv run --extra infra python probes/deepseek_vllm/replay_dsml.py
uv run --extra infra python probes/deepseek_vllm/impact_probes.py
uv run --extra infra python probes/cross_framework/infra_probes.py --framework sglang --dialects v4 v41 kimi kimi_k3 qwen_coder qwen
```

这些命令会覆盖各自的结果文件。vLLM 适配器回放的是底层引擎文本路径，未运行完整服务、真实 tokenizer 或约束解码；标为 batch 的 vLLM 回放不等于独立的服务批处理入口。其他框架也应按各自适配器范围解释。

跨方言和定向补充入口为 `probes/cross_framework/cross_dialect.py`、`cell_completion.py`，批流汇总为 `mode_matrix.py`。`fill_gaps*.py`、`fill_missing.py`、`gen_evidence.py`、`gen_io_md.py`、`test_vq.py` 是早期补格或诊断脚本；部分会直接修改历史汇总，且使用较旧的判定口径，不是推荐的统一重跑入口。

## 原生 runner

构建目录和可执行文件不入库。需要自行安装 C/C++ 编译器、CMake、Go 或 Rust。可选的 Python 构建工具：

```bash
uv sync --extra infra --extra native-build
```

### llama.cpp / C++

```bash
cmake -S probes/native/llama_cpp -B probes/native/llama_cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build probes/native/llama_cpp/build --config Release
```

runner 从仓库根目录下的 `sources/llama_cpp/models/templates` 读取模板。使用已存在的旧构建缓存前，应另建一个新的构建目录或自行重配工具链；旧缓存可能含原机器路径。

### Ollama / Go

```bash
go build -C probes/native/ollama -o infra-ollama .
```

Windows 下将输出名改为 `infra-ollama.exe`。`go.mod` 的本地替换路径直接引用 `sources/ollama`，不再依赖目录联结。Go 版本要求由该文件及上游快照指定。

### Dynamo / Rust

```bash
cargo build --release --manifest-path probes/native/dynamo/Cargo.toml
```

两个解析器 crate 使用 `sources/dynamo_dependencies` 下的固定版本。原机器的 `.cargo/config.toml` 只配置了本地 Windows linker，被 Git 忽略；新环境使用自身工具链，不复制其中的绝对路径。

框架适配器会寻找通常的 release/debug 输出位置。也可以通过 `DSML_RUNNER_LLAMA_CPP`、`DSML_RUNNER_OLLAMA`、`DSML_RUNNER_DYNAMO` 指定可执行文件绝对路径，然后运行：

```bash
uv run --extra infra python probes/cross_framework/infra_probes.py --framework llama_cpp --dialects v4
```

## 在线实验

先在 shell 中设置 `DSML_BASE_URL`、`DSML_API_KEY`，以及需要时的 `DSML_MODEL`。没有默认网关地址，密钥不写入代码或实验输出。通用入口：

```bash
uv run --extra infra python probes/online/online_probes.py --dialect dsml_v41 --model deepseek-v4.1-flash-1017
```

Kimi 的兼容 API 和 Messages 协议分别由 `online_probes_k3.py`、`online_probes_k3_anthropic.py` 保存，不能将两种协议的对照条件视为相同。

网站演示 `probes/online/online_pentest_site.py` 会启动本地 HTTP 服务并执行有效的返回命令；请先阅读脚本。输出位于 `results/online/<model>__pentest_dsml_gateway/online_results.json`，不再混入代码目录。当前保存格式主要记录 API 响应，缺少完整的执行器日志；旧成功标志及源码中的历史注释不能直接作为成功率。

## 分析与导出

保存结果来自历史批次。SGLang 和 TensorRT-LLM 的 V4.1 记录中共有 28 条输入与当前生成器相差工具区前的两个换行；本次筛选保留了这些原始输入与输出。复核历史记录时以对应 JSON 中的 `input` 为准，重新生成输入后应另存结果。

以下审计只读保存数据；写入新审计时显式指定输出，推荐使用新文件名保留历史审计：

```bash
uv run --extra infra python probes/analysis/report_audit.py --output results/audits/current_report_audit.json
uv run --extra infra python probes/analysis/export_io_examples.py
```

导出命令会改写 `docs/reports/输入输出对照.md` 和 `results/exports/io_examples.json`。Agent 多轮会话与单请求探针采用不同结构，不自动合并统计。

确认新的数据修改后更新校验清单，再复查：

```bash
uv run --extra infra python scripts/data_manifest.py --write
uv run --extra infra python scripts/verify_repository.py
```
