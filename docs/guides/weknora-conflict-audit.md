# WeKnora 文档冲突审计

本集成从 WeKnora 文档和分块列表读取全部分页，不以检索 Top-K 结果代替知识库全量数据。
线上只读；不修改或裁决覆盖源内容。Codex CLI 负责事实抽取和候选事实对的语义判断。

## 配置

使用 Python 3.10–3.13，安装 Explorer 依赖。另需已登录的 `codex` CLI。
连接信息放在 Git 忽略的 `.local/weknora/connection.json`，权限设为 `0600`：

```json
{
  "base_url": "https://weknora.example",
  "token": "<JWT，仅本地保存>",
  "knowledge_base_id": "<指定知识库 ID>"
}
```

也可在调用 `WeKnoraIngestor` 时传 `api_key`，使用 `X-API-Key` 认证。
服务器地址由管理员配置，支持明确授权的内网地址；HTTP 跳转不会携带凭据自动跟随。
会话过期后更新 token；不会存储账号密码。快照和报告包含业务内容，应限制文件访问权限。

## 获取冻结快照

```python
import json
from pathlib import Path
from semantica.ingest.weknora_ingestor import WeKnoraIngestor
from semantica.conflicts.codex_audit import write_json

root = Path(".local/weknora")
config = json.loads((root / "connection.json").read_text())
client = WeKnoraIngestor(config["base_url"], token=config["token"])
snapshot = client.snapshot(config["knowledge_base_id"], progress=print)
write_json(root / "snapshot.json", snapshot)
```

快照保留原始分块、文档 ID、分块 ID、内容哈希及服务端提供的位置元数据。
检测分页重复、丢失、总数变化及文档清单变化，报告未解析文档和空内容。
接口不是事务快照；分块内容仍可能在扫描期间更新，原始 PDF/OCR 质量也需独立验证。

## 运行

```bash
python3.13 -m semantica.conflicts.codex_audit \
  .local/weknora/snapshot.json .local/weknora/audit \
  --model gpt-6-sol --workers 3
```

遵循参考项目 `sematica_test2` 的隔离调用方式：独立临时目录、stdin、只读沙箱、
临时 CLI 会话和结果文件。本实现另传 JSON Schema 并在本地校验。
认证复用已登录 CLI；可用 `CODEX_CLI_PATH`、`CODEX_HOME` 和 `SEMANTICA_CODEX_MODEL` 配置。
若直连模型服务超时，可设置 `SEMANTICA_CODEX_PROXY=http://127.0.0.1:端口`，
它仅作用于 Codex 子进程，不影响内网 WeKnora 连接和系统网络。
原文会发送给 CLI 所使用的模型服务。提示词要求将文档当作数据；只读沙箱不等同完全禁用工具。

缓存按模型、提示词及源内容哈希隔离，重跑可复用成功的模型结果。
每次抽取要求确认全部分块，且证据必须逐字存在于源分块；错误不计入已处理数量。
候选来自主体/属性一致匹配及字符 n-gram 邻居检索，模型再判断条件和时间是否重叠。
不同版本、不同对象、等价单位或明示例外不应直接判为冲突；条件不足进入待复核。

**覆盖全部内容不代表召回全部冲突。** 候选召回不是所有事实对穷举；模型可能漏抽事实、
错误理解主体或条件。`completed` 仅表示本轮计划任务完成，不是“知识库不存在其它冲突”的证明。
失败批次或来源问题会使结果为 `partial`，应修复后重试并人工审核发现项。

## Explorer

启动后端时设置 `SEMANTICA_WEKNORA_DIR` 为上述本地目录的绝对路径。
进入 **Enrich → 文档冲突检测** 查看进度、冲突、待复核项和原文分块。
页面的运行按钮针对已有快照执行/重试，重新获取线上变化需要先更新快照。
API 路由沿用 Explorer 的 API Key 认证策略，不能在请求中指定任意源地址或 CLI 命令。

- `GET /api/conflicts/weknora`：覆盖率和进度
- `GET /api/conflicts/weknora/findings?kind=conflicts|uncertain`：分页证据
- `GET /api/conflicts/weknora/source/{chunk_id}`：原文
- `POST /api/conflicts/weknora/audit`：执行或重试

协议参考：[WeKnora 文档 API](https://github.com/Tencent/WeKnora/blob/main/website-docs/04-api/02-api-knowledge.md)、
[分块 API](https://github.com/Tencent/WeKnora/blob/main/website-docs/04-api/02-api-chunks.md)、
[OpenAI Docs 非交互模式](https://developers.openai.com/codex/noninteractive)。
