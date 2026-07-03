# AttentionOS MCP Server — 让你的 Agent 学会不打扰

> 我们给了 Agent 无限的耐心，却没告诉它们你没有。

`mcp/attention_mcp.py` 是一个零依赖的 MCP (Model Context Protocol) 服务器，
把本地采集器的数据变成任何 Agent 都能查询的**注意力状态接口**。
纯 stdio、纯本地回环——你的数据依然不出机器。

## 安装（Claude Code）

```sh
claude mcp add attention -- python3 /绝对路径/AttentionOS/mcp/attention_mcp.py
```

前提：采集器在跑（桌宠 App 或 `python3 cli/attn.py collect` 任一即可）。

## 提供什么

| 工具 / 资源 | 返回 |
|---|---|
| `get_attention_state` / `attention://state` | `focused / calm / frazzled / away` + 打断建议 + 切换率 + 当前专注块时长 |
| `get_attention_report` | 当日全指标：专注半衰期、切换率、恢复成本、打断负载、深度专注分钟、Top 应用与打断者 |
| `get_attention_profile` / `attention://profile` | 60 秒体检的类型与三网分数 |

`get_attention_state` 的工具描述本身就在教 Agent 怎么做：
**focused → 憋住问题攒着批量问；frazzled → 把所有要说的合并成一条；
away → 静默干活攒结果；calm → 正常交流。**

## 让 Claude Code 变得注意力感知（agent skill）

把这段加进你的项目 `CLAUDE.md`（或全局 `~/.claude/CLAUDE.md`）：

```markdown
# Attention awareness
在向我提问、请求确认、或产出需要我审阅的长内容之前，先调用
attention MCP 的 get_attention_state：
- "focused"：不要打断。能自主决定的就自主决定，把非紧急问题攒到最后批量问。
- "frazzled"：我已经被切碎了。把所有要问的合并成一条消息，不要连环追问。
- "away"：我不在。继续自主推进，回来后给我一份摘要。
- "calm"：正常交流。
```

就这么多——不需要插件，行为约定 + 状态接口 = 一个不打扰的 Agent。

## 试一试

```
> 看一下我现在的注意力状态，然后决定要不要现在问我问题

⏺ attention - get_attention_state()
  ⎿ { "state": "focused", "in_deep_block": true, "current_block_min": 23, ... }

⏺ 你正在一个 23 分钟的深度专注块里。我先把三个待确认项攒着，
  继续能自主推进的部分，等你出块了再一起问。
```

## 设计说明

- 状态判定与桌宠心情引擎同源（近 30 分钟切换率 + 当日专注块 + 5 分钟无事件 = away），
  阈值见 [METRICS.md](METRICS.md)。
- 服务器每次调用即时查询 SQLite，无缓存无常驻状态——重启无成本。
- 观测者不计入观测：AttentionOS 自身的窗口焦点被排除。
