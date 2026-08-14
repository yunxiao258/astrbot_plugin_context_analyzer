# AstrBot 上下文分析插件

AstrBot 群聊/私聊上下文分析插件：LLM 会话分析、系统状态监控、插件生命周期管理。

## 功能

### 上下文分析 (`/context`)
- 分析当前会话的消息历史，报告会标注**数据来源**（会话上下文 / 平台消息历史）
- 数据获取优先级：先读取 LLM 会话上下文（`conversation`），为空时自动回退到平台消息历史（`platform_message_history`）
- 统计消息数量、预估 Token 数
- 角色分布（用户 / 助手 / 系统 / 其他，`tool` 等角色计入"其他"）
- 最近 5 条消息预览
- 子命令（仅管理员）：
  - `/context export`：导出当前会话历史为文件（json / csv 格式），支持 `export [json|csv] [条数]` 筛选最近 N 条
  - `/context daily`（别名 `/context 日报`）：手动生成并发送插件事件日报
  - `/context weekly`（别名 `/context 周报`）：手动生成并发送插件事件周报

### 系统状态 (`/status`)
- CPU、内存、磁盘使用率
- 网络连接数
- 插件激活状态
- LLM 提供商配置
- 进程信息（PID、内存占用、运行时间）
- **仅管理员可用**

### 插件管理 (`/plugins`)
- 插件列表（激活/未激活）
- 插件版本信息
- 插件变更检测（新增/更新/删除），变更会自动写入事件日志
- 最近事件预览

### 查看日志 (`/log`)
- 显示插件事件日志（加载/卸载/新增/更新/删除/错误）
- 支持按插件名过滤
- 日志通过插件生命周期事件自动记录，无需手动操作

### 重置缓存 (`/reset`)
- 清空插件状态快照
- 清空事件日志
- 重置会话缓存

## 依赖

### 必需
- AstrBot 核心库（v4.x）

### 可选
- `Pillow`：图表生成功能（支持中文字体）
- `psutil`：系统状态监控

安装可选依赖：
```bash
pip install Pillow psutil
```

## 配置

见 `_conf_schema.json`。关键项：

- `enable_charts`：是否启用图表生成（需要 Pillow，默认 `true`）
- `max_events`：最大事件日志数量（默认 `500`，内存与磁盘同步截断）
- `enable_system_status`：是否启用系统状态监控（需要 psutil，默认 `true`）

## 数据

存储于 `plugin_data/astrbot_plugin_context_analyzer/`：

- `plugin_events.json`：插件事件日志（最近 `max_events` 条）
- `plugin_snapshots.json`：插件状态快照（用于跨重启的变更检测）
- `context_chart.png`：上下文分析图表（缓存）
- `status_chart.png`：系统状态图表（缓存）
- `plugins_chart.png`：插件状态图表（缓存）

## 使用示例

```
/context          # 分析当前会话上下文
/context export   # 导出会话历史文件（管理员）
/context daily    # 手动生成事件日报（管理员）
/context weekly   # 手动生成事件周报（管理员）
/status           # 查看系统状态（管理员）
/plugins          # 查看插件列表和状态
/reset            # 重置所有缓存
/reset plugin名   # 重置指定插件
/log              # 查看所有事件日志
/log plugin名     # 查看指定插件事件日志
```

## 指令说明

| 指令 | 说明 | 权限 |
|------|------|------|
| `/context` | 分析当前会话上下文 | 所有人 |
| `/context export` | 导出会话历史为文件（`export [json\|csv] [条数]` 可选筛选） | 管理员 |
| `/context daily` | 手动生成事件日报 | 管理员 |
| `/context weekly` | 手动生成事件周报 | 管理员 |
| `/status` | 查看系统状态 | 管理员 |
| `/plugins` | 查看插件列表 | 所有人 |
| `/reset` | 重置缓存（可指定插件名） | 所有人 |
| `/log` | 查看事件日志（可指定插件名） | 所有人 |

## 更新记录

### v1.2.1
- 修复日报/周报自动报告：触发判断改为"到达设定时间即触发"，不再依赖精确到分钟的匹配，周报随日报在报告时间点触发
- 报告时间格式非法时回退 `08:00`，不再导致定时任务崩溃
- 事件日志/插件快照加载增加结构校验，异常数据不再导致 `/plugins`、`/log` 崩溃
- `net_connections` 读取失败时显示 `N/A（无权限读取）`，不再拖垮 `/status`
- 新增 `/context export` 导出格式与权限、事件日志容错等回归测试

### v1.2.0
- 新增 `/context export`：导出当前会话历史为 json/csv 文件
- 新增 `/context daily` / `/context weekly`：手动生成并发送插件事件日报/周报
- 后台自动日报/周报推送（`daily_report_time` / `weekly_report_weekday` 配置）

### v1.1.2
- 重构三份图表生成的公共骨架（`_new_chart`），减少重复代码

### v1.1.1
- 修复与加固内部逻辑

### v1.1.0
- 修复 `/context` 无法获取会话历史的问题：修正历史管理器引用与查询参数，支持会话上下文 / 平台消息历史双来源
- 修复 `/log` 事件日志始终为空的问题：新增插件加载/卸载/错误生命周期事件监听，自动记录日志
- 事件日志内存与磁盘同步截断，`max_events` 配置生效
- 插件状态快照持久化，重启后不再误报插件"新增"
- 图表生成支持中文字体
- 支持含特殊字符的插件名过滤
