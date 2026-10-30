# 固定上游源码

此目录是实验实际使用的部分源码快照，不是完整安装的推理服务，也不包含模型权重。目录名 `vllm_latest` 是历史命名，不保证是当前最新版本。

每个框架的 `snapshot.json` 记录提交号和现有哈希；`tree.json` 是当时抓取的完整上游文件目录，虽然较大，仍保留用于溯源。Dynamo 两个 crate 的清单记录版本和归档 SHA-256。

源码按原始字节提交，避免自动换行或格式化破坏实验哈希。项目自有适配器位于 `probes/`，不要把适配层修改写进这里。

`probes/cross_framework/fetch_infra_sources.py` 是部分框架的抓取辅助程序，不能重建所有早期快照，也不负责下载模型。已有快照是复现基础，不应为了运行回放先刷新它们。

原始许可证与文件头保留，补充说明见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
