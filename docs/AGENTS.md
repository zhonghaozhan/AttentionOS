# Agent 联动 — 从进程监测到联合注意力时间线

窗口焦点只回答"你在看哪"。接上 coding agent 之后，时间线多出关键的一维：
**agent 正在干活，还是在等你。**

这修正了两个此前测不准的东西：

1. **监督并行 ≠ 分心。** Agent 跑任务时你切去读论文，不是注意力碎片，
   是正确的并行调度。
2. **Agent-Wait Cost 是新的隐形税。** Claude 停下来等你确认，而你在
   Slack 里泡了 12 分钟——agent 阻塞 + 你被打断，双向浪费。现在它是
   `attn report` 里的一行数字。

## 接线（Claude Code hooks → attn）

把下面加进 `~/.claude/settings.json`（路径换成你的仓库位置）：

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command",
      "command": "python3 /path/to/AttentionOS/cli/attn.py agent-event working" }] }],
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "python3 /path/to/AttentionOS/cli/attn.py agent-event waiting" }] }],
    "Notification": [{ "hooks": [{ "type": "command",
      "command": "python3 /path/to/AttentionOS/cli/attn.py agent-event notify" }] }]
  }
}
```

语义：你提交 prompt = agent 开始工作；agent 停下 = 开始等你；
需要许可/注意 = notify。事件带 session id 写入本地
`~/.attentionos/attn.db` 的 `agent_events` 表——和人类焦点数据同库，
永不上传。

## 你能得到什么

- **`attn report`** 新增一行 `Agent-Wait Cost`：今天所有 agent 等你输入的
  总分钟数（每段封顶 30 分钟——超过说明你下班了，不算你头上）。
- **`attn statusline`**：Claude Code 状态栏一行字——ASCII 宠物脸 + 今日
  深度专注 + "⏳等你 Nm"。加进 settings.json：

  ```json
  { "statusLine": { "type": "command",
      "command": "python3 /path/to/AttentionOS/cli/attn.py statusline" } }
  ```

- **MCP `get_attention_state`** 新增 `agents_waiting_on_user` 字段——
  一个 agent 可以看见另一个 agent 在等你，然后决定别再往队列里加问题。
  （配合 [MCP.md](MCP.md) 的注意力感知片段，这就是完整的 agent skill。）

## 设计原则

- 钩子命令 <50ms、纯本地写入，绝不拖慢 agent。
- 只记状态转换（working/waiting/notify + 时间戳 + session），
  不碰 prompt 内容——观测调度，不偷看工作。
- 下一步（roadmap）：dashboard 时间线叠加 agent 泳道；宠物在
  "Claude 等你超过 5 分钟"时探头提醒——把等待成本变成可感知的推力。
