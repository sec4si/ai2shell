# 数据说明

当前数据范围固定为 DeepSeek-V4、DeepSeek-V4.1、Kimi-K2、Kimi-K3、Qwen-Coder、Qwen。范围外记录与混合输入的原件保存在本机忽略目录 `.local/model-scope/`，没有改写为范围内新实验。

## 文件分类

| 路径 | 内容 | 解释边界 |
| --- | --- | --- |
| `deepseek_vllm/results.json` | DSML 基础引擎文本回放 | 不含真实模型、服务或执行器 |
| `deepseek_vllm/impact_results.json` | 影响、分块与辅助方法检查 | 按所测层次分别解释 |
| `deepseek_vllm/e2e_results.json` | 最初在线 API 批次 | 上游内部实现和原始生成流未记录 |
| `cross_framework/infra_results` | 框架与方言回放、定向补充、跨方言比较及 stderr | 正常对照失败不计作攻击成立 |
| `online/<model>__<experiment>` | 单请求探针或 Agent 多轮轨迹 | 需先区分 JSON 结构与工具是否执行 |
| `exports` | 派生示例和旧汇总 | 可能截断字段或使用旧判定，不代替原始记录 |
| `audits` | 成文时保存的审计输出 | 当前按六类范围重新审计；历史适配器哈希保留 |

## 两种在线结构

单请求文件使用顶层 `probes`。每项可能保存 `request`、`request_payload` 或仅 `request_text`，以及 `response`、`stream_result` 或 `error`。不能把 HTTP 错误或缺失响应按空正文判为成功。

网站实验使用顶层 `scenarios`，每条轨迹包含 `transcript`，条目主要是 `round` 与 `response`。当前格式没有完整保存每次工具的 stdout、stderr、退出码和回传请求；`id_via_split` 只是历史标志，不能直接证明分裂原因或真实执行次数。`pentest_site5_results.json` 是历史批次，不与另一批的响应重复计数。

## 完整性与溯源

- [manifest.json](manifest.json) 记录数据相对路径、大小、SHA-256 和原始／派生分类。
- [layout-migration.json](layout-migration.json) 记录整理时的旧路径与新路径。
- [redactions.json](redactions.json) 记录内网网关地址替换及前后哈希；原件仅保留在本机忽略目录。
- 上游提交号与文件哈希位于 `sources/*/snapshot.json`；部分早期快照没有逐文件哈希表，需同时查看基础回放中的 `source_sha256`。
- `adapter_sha256` 指实验形成时的适配器，历史结果不保证匹配当前适配器；不会因整理仓库而改写这些字段。

从仓库根目录进行只读核对：

```bash
uv run --extra infra python scripts/data_manifest.py
uv run --extra infra python probes/analysis/report_audit.py
```

检查失败时先复核修改原因，不能只通过重写清单掩盖变化。各报告原有统计和成功标志保留，当前回放数量、有效对照数量和独立攻击数量是不同口径。
