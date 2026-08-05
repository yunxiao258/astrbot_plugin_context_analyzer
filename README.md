# AstrBot 上下文分析插件

AstrBot 群聊/私聊上下文分析插件：LLM 会话分析、系统状态监控、插件生命周期管理。

## 功能

### 上下文分析 (`/context`)
- 分析当前会话的消息历史
- 统计消息数量、Token 预估
- 角色分布（用户/助手/系统）
- 最近消息预览

### 系统状态 (`/status`)
- CPU、内存、磁盘使用率
- 网络连接数
- 插件激活状态
- LLM 提供商配置

### 插件管理 (`/plugins`)
- 插件列表（激活/未激活）
- 插件版本信息
- 插件变更检测（新增/更新/删除）
- 事件日志查看

### 重置缓存 (`/reset`)
- 清空插件状态快照
- 清空事件日志
- 重置会话缓存

### 查看日志 (`/log`)
- 显示插件事件日志
- 支持按插件名过滤

## 依赖

### 必需
- AstrBot 核心库

### 可选
- `Pillow`：图表生成功能
- `psutil`：系统状态监控

安装可选依赖：
```bash
pip install Pillow psutil
```

## 配置

见 `_conf_schema.json`。关键项：

- `enable_charts`：是否启用图表生成
- `max_events`：最大事件日志数量
- `enable_system_status`：是否启用系统状态监控

## 数据

存储于 `plugin_data/astrbot_plugin_context_analyzer/`：

- `plugin_events.json`：插件事件日志
- `context_chart.png`：上下文分析图表（缓存）
- `status_chart.png`：系统状态图表（缓存）
- `plugins_chart.png`：插件状态图表（缓存）

## 使用示例

```
/context          # 分析当前会话上下文
/status           # 查看系统状态
/plugins          # 查看插件列表和状态
/plugins music    # 查看指定插件详情
/reset            # 重置所有缓存
/reset music      # 重置指定插件
/log              # 查看所有事件日志
/log music        # 查看指定插件事件日志
```

## 指令说明

| 指令 | 说明 | 权限 |
|------|------|------|
| `/context` | 分析当前会话上下文 | 所有人 |
| `/status` | 查看系统状态 | 所有人 |
| `/plugins` | 查看插件列表 | 所有人 |
| `/reset` | 重置缓存 | 管理员 |
| `/log` | 查看事件日志 | 管理员 |
