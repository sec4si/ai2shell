# 仓库整理与发布

## 本次整理

- 在线脚本从 `probes/common` 移到 `probes/online`；分析脚本移到 `probes/analysis`。
- 原根目录的报告集中到 `docs/reports`，派生 JSON 移到 `results/exports`，审计输出移到 `results/audits`。
- 网站实验结果集中到 `results/online/<model>__pentest_dsml_gateway`，保留历史文件。
- 原生 runner 源码引用真实的 `sources` 路径；构建入口不再固定本机 C/C++ 工具链路径。
- 增加 Python 依赖配置、Git 忽略规则和只读校验工具。

全部旧路径到新路径的对应关系见 [layout-migration.json](../results/layout-migration.json)。

## 原始记录与脱敏

整理前的项目代码、文档和实验记录均保存在本机 `.local/repository-prep/<时间>/`；该目录被 Git 忽略。根目录临时文件与 `work/` 也保存在该备份的 `scratch/` 中，没有删除。

公开数据只替换了已识别的内网网关 URL，保留模型输入、工具参数、输出以及历史判定标志。脱敏文件、替换次数和修改前后 SHA-256 见 [redactions.json](../results/redactions.json)。不声称记录已完全匿名化：在线文本仍可能包含实验用户名、工作目录和服务响应标识。

固定上游源码没有修改或重新格式化。`.gitattributes` 为源码快照和实验数据禁用了 Git 换行转换，避免 Windows 提交或检出改变其哈希。

## 不提交的内容

`.venv/`、`.infra-venv/`、`.tools/`、`.local/`、`__pycache__/`、原生 `build/` 与 `target/`、可执行文件、`.env` 及旧目录联结不入库。源码快照、非空和空的实验 stderr 日志、Go/Rust 依赖锁文件保留，以支持复核。

## 提交前检查

```bash
uv run --extra infra python scripts/verify_repository.py
git status --short
git add .
git diff --cached --stat
```

新实验后，应先审核数据变化、处理目标地址，再显式更新 `results/manifest.json`。不要将本地未脱敏新记录直接视为可公开数据。

仓库初始化不等于已经创建提交或配置远端；维护者自行决定仓库地址、公开范围和自有代码许可。第三方授权信息见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 六类模型数据范围

测试数据与文档仅保留 DeepSeek-V4、DeepSeek-V4.1、Kimi-K2、Kimi-K3、Qwen-Coder、Qwen。范围定义在 `specs/study_scope.json`，筛选说明在 [scope.json](../results/scope.json)。范围外数据与筛选前文档保存在本机 `.local/model-scope/`。上游源码依赖未删除；它们不代表新增测试模型。
