# AttentionOS Desktop（中档）— 桌宠 + 本地采集器

一只住在你桌面角落的像素宠物，是你注意力数据的**常驻低分辨率视图**：
深度专注时它进入心流蹦跳；上下文切换风暴时它被"切碎"到发抖；
你不在时它睡觉。双击它查看今日数据、粘贴网页测试的**存档码**领养专属物种。

数据只写本地 `~/.attentionos/attn.db`（与 `cli/attn.py` 同一张表），
永不上传。

## 运行（开发）

```sh
# 依赖：Rust (rustup)、Node ≥ 18
cd desktop
npm install
npm run dev        # 首次编译需几分钟
```

首次采集时 macOS 会请求「辅助功能/自动化」权限（读取前台 App 名称，仅此而已）——请允许。

## 打包

```sh
npm run build      # 产出 src-tauri/target/release/bundle/macos/AttentionOS.app
```

## 现状（骨架 v0.1）

- [x] 透明置顶像素宠物窗（可拖动，双击开面板）
- [x] 采集器线程：前台 App → SQLite（与 CLI 同库同 schema）
- [x] 心情引擎：近 30 分钟切换率 + 今日专注块 → sleeping / calm / focused / frazzled
- [x] 存档码导入（`attn1.…`，见 [docs/TIERS.md](../docs/TIERS.md)）→ 决定物种
- [x] 托盘菜单：显示/隐藏、退出
- [ ] 六物种精灵全套 + 进化形态（当前全物种共用史莱姆底模，仅配色不同）
- [ ] 每日结算卡（分享图导出）
- [ ] Focus Shield（宣告专注块，宠物替你挡通知）
- [ ] MCP server：`attention://state` 供 Agent 查询（Pro）
