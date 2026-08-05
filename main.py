"""AstrBot 上下文分析插件：LLM 会话分析、系统状态监控、插件生命周期管理"""

import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import MessageChain, MessageEventResult
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image, Plain
from astrbot.api.platform import MessageType
from astrbot.api.star import Context, Star, register

# 插件元数据
PLUGIN_NAME = "astrbot_plugin_context_analyzer"
PLUGIN_AUTHOR = "Administrator"
PLUGIN_DESC = "LLM 上下文分析、系统状态监控、插件生命周期管理"
PLUGIN_VERSION = "1.0.0"

# 无额外常量，直接使用 @filter.command 注册指令


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class ContextAnalyzerPlugin(Star):
    """LLM 上下文分析插件：分析会话状态、监控插件生命周期、查看系统状态"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        # 数据目录
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "plugin_data",
            PLUGIN_NAME,
        )
        os.makedirs(self.data_dir, exist_ok=True)

        # 插件事件日志（内存 + 持久化）
        self._plugin_events: list[dict] = []
        self._plugin_snapshots: dict[str, dict] = {}  # plugin_name -> snapshot
        self._load_events()

        # 会话上下文缓存（内存）
        self._session_cache: dict[str, dict] = {}

        logger.info(f"【{PLUGIN_NAME}】插件初始化完成")

    # ========== 工具方法 ==========

    def _load_events(self):
        """从磁盘加载插件事件日志"""
        try:
            events_file = os.path.join(self.data_dir, "plugin_events.json")
            if os.path.exists(events_file):
                import json
                with open(events_file, "r", encoding="utf-8") as f:
                    self._plugin_events = json.load(f)
        except Exception as e:
            logger.warning(f"加载插件事件日志失败: {e}")

    def _save_events(self):
        """保存插件事件日志到磁盘"""
        try:
            events_file = os.path.join(self.data_dir, "plugin_events.json")
            import json
            # 只保留最近 500 条事件
            events = self._plugin_events[-500:]
            with open(events_file, "w", encoding="utf-8") as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存插件事件日志失败: {e}")

    def _record_event(self, event_type: str, plugin_name: str, details: dict = None):
        """记录插件事件"""
        event = {
            "time": datetime.now().isoformat(),
            "type": event_type,
            "plugin": plugin_name,
            "details": details or {},
        }
        self._plugin_events.append(event)
        self._save_events()

    def _format_time(self, seconds: float) -> str:
        """格式化时间（秒 -> 可读格式）"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            return f"{seconds/60:.1f}分钟"
        elif seconds < 86400:
            return f"{seconds/3600:.1f}小时"
        else:
            return f"{seconds/86400:.1f}天"

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数（粗略估算：中文 1 token/字，英文 0.75 token/词）"""
        if not text:
            return 0
        # 简单估算：中文字符数 * 1 + 英文单词数 * 0.75
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_words = len([w for w in text.split() if w.isascii()])
        return chinese_chars + int(english_words * 0.75)

    # ========== 指令处理 ==========

    @filter.command("context", priority=200)
    async def analyze_context(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """分析当前会话上下文"""
        try:
            # 获取会话信息
            platform_id = event.get_platform_name() if hasattr(event, 'get_platform_name') else "unknown"
            user_id = str(event.get_sender_id())
            group_id = str(event.get_group_id() or "")
            session_id = f"{platform_id}:{user_id}:{group_id}"

            # 从数据库获取消息历史
            history = []
            try:
                history_mgr = self.context.platform_message_history_mgr
                if history_mgr:
                    history = await history_mgr.get(platform_id, user_id, page=1, page_size=100)
            except Exception as e:
                logger.warning(f"获取消息历史失败: {e}")

            # 统计信息
            total_messages = len(history)
            if total_messages == 0:
                return self._send_text(event, "📊 当前会话没有历史消息记录")

            # 分析角色分布
            role_counts = {"user": 0, "assistant": 0, "system": 0}
            total_tokens = 0
            for msg in history:
                content = msg.content if hasattr(msg, 'content') else {}
                role = content.get("role", "unknown")
                text = content.get("text", "")
                if role in role_counts:
                    role_counts[role] += 1
                total_tokens += self._estimate_tokens(text)

            # 最近消息
            recent = history[-5:] if len(history) >= 5 else history
            recent_lines = []
            for msg in recent:
                content = msg.content if hasattr(msg, 'content') else {}
                role = content.get("role", "unknown")
                text = content.get("text", "")[:50]
                icon = "👤" if role == "user" else "🤖" if role == "assistant" else "⚙️"
                recent_lines.append(f"{icon} {text}...")

            # 生成报告
            report = [
                "📊 会话上下文分析报告",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"💬 消息总数: {total_messages} 条",
                f"🔢 预估 Token: {total_tokens:,}",
                "",
                "👥 角色分布:",
                f"  👤 用户消息: {role_counts['user']} 条",
                f"  🤖 助手回复: {role_counts['assistant']} 条",
                f"  ⚙️ 系统消息: {role_counts['system']} 条",
                "",
                "📝 最近 5 条消息:",
            ]
            report.extend(recent_lines)

            # 检查是否有图片生成能力（尝试用 Pillow）
            try:
                chart = self._generate_context_chart(role_counts, total_messages, total_tokens)
                if chart:
                    report.append("\n📈 详细图表已生成")
                    await event.send(MessageChain([Image.fromFileSystem(chart)]))
            except Exception:
                pass  # Pillow 不可用，忽略

            return self._send_text(event, "\n".join(report))

        except Exception as e:
            logger.error(f"分析上下文失败: {e}")
            return self._send_text(event, f"❌ 分析上下文时出错: {str(e)}")

    @filter.command("status", priority=200)
    async def analyze_status(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """分析系统状态"""
        try:
            import psutil

            # CPU 和内存
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # 网络连接
            connections = len(psutil.net_connections())

            # 进程信息
            process = psutil.Process()
            process_memory = process.memory_info()

            # 插件统计
            stars = self.context.get_all_stars()
            active_plugins = sum(1 for s in stars if s.activated)
            total_plugins = len(stars)

            # LLM 提供商统计
            providers = self.context.get_all_providers()
            provider_count = len(providers)

            report = [
                "🖥️ 系统状态报告",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "💻 资源使用:",
                f"  🔥 CPU 使用率: {cpu_percent}%",
                f"  💾 内存使用: {memory.percent}% ({memory.used // (1024**2)}MB / {memory.total // (1024**2)}MB)",
                f"  💿 磁盘使用: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)",
                f"  🌐 网络连接数: {connections}",
                "",
                "🔌 插件状态:",
                f"  ✅ 已激活: {active_plugins} 个",
                f"  ⏸️ 未激活: {total_plugins - active_plugins} 个",
                f"  📦 总计: {total_plugins} 个",
                "",
                "🤖 LLM 提供商:",
                f"  📡 已配置: {provider_count} 个",
                "",
                "⚙️ 进程信息:",
                f"  🆔 进程ID: {process.pid}",
                f"  📊 进程内存: {process_memory.rss // (1024**2)} MB",
                f"  ⏱️ 运行时间: {self._format_time(time.time() - process.create_time())}",
            ]

            # 检查是否有 Pillow，生成图表
            try:
                chart = self._generate_status_chart(cpu_percent, memory.percent, disk.percent)
                if chart:
                    report.append("\n📈 详细图表已生成")
                    await event.send(MessageChain([Image.fromFileSystem(chart)]))
            except Exception:
                pass

            return self._send_text(event, "\n".join(report))

        except ImportError:
            return self._send_text(event, "❌ 系统状态分析需要 psutil 库，请安装: pip install psutil")
        except Exception as e:
            logger.error(f"分析系统状态失败: {e}")
            return self._send_text(event, f"❌ 分析系统状态时出错: {str(e)}")

    @filter.command("plugins", priority=200)
    async def analyze_plugins(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """分析插件状态"""
        try:
            stars = self.context.get_all_stars()
            if not stars:
                return self._send_text(event, "📦 没有已加载的插件")

            # 当前插件快照
            current_snapshot = {}
            for star in stars:
                current_snapshot[star.name] = {
                    "version": star.version,
                    "activated": star.activated,
                    "desc": star.desc,
                }

            # 检测变更
            changes = []
            for name, snapshot in current_snapshot.items():
                if name not in self._plugin_snapshots:
                    changes.append({"type": "new", "plugin": name, "version": snapshot["version"]})
                elif self._plugin_snapshots[name]["version"] != snapshot["version"]:
                    changes.append({
                        "type": "updated",
                        "plugin": name,
                        "old_version": self._plugin_snapshots[name]["version"],
                        "new_version": snapshot["version"],
                    })

            # 检查删除的插件
            for name in list(self._plugin_snapshots.keys()):
                if name not in current_snapshot:
                    changes.append({"type": "deleted", "plugin": name})

            # 更新快照
            self._plugin_snapshots = current_snapshot

            # 生成报告
            active_count = sum(1 for s in stars if s.activated)
            report = [
                "📦 插件状态报告",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"📊 插件总数: {len(stars)} 个",
                f"✅ 已激活: {active_count} 个",
                f"⏸️ 未激活: {len(stars) - active_count} 个",
            ]

            # 显示变更
            if changes:
                report.append("")
                report.append("🔄 插件变更:")
                for change in changes:
                    if change["type"] == "new":
                        report.append(f"  🆕 新增: {change['plugin']} v{change['version']}")
                    elif change["type"] == "updated":
                        report.append(f"  ⬆️ 更新: {change['plugin']} {change['old_version']} → {change['new_version']}")
                    elif change["type"] == "deleted":
                        report.append(f"  🗑️ 删除: {change['plugin']}")

            # 插件列表
            report.append("")
            report.append("📋 插件列表:")
            for star in stars:
                status = "✅" if star.activated else "⏸️"
                report.append(f"  {status} {star.name} v{star.version}")
                if star.desc:
                    report.append(f"     {star.desc[:60]}...")

            # 最近事件
            recent_events = self._plugin_events[-10:] if self._plugin_events else []
            if recent_events:
                report.append("")
                report.append("📝 最近事件:")
                for evt in reversed(recent_events):
                    icon = "🆕" if evt["type"] == "new" else "⬆️" if evt["type"] == "updated" else "🗑️"
                    time_str = evt["time"].split("T")[1][:8] if "T" in evt["time"] else evt["time"]
                    report.append(f"  {icon} {time_str} - {evt['plugin']}")

            # 检查是否有 Pillow
            try:
                chart = self._generate_plugins_chart(stars)
                if chart:
                    report.append("\n📈 详细图表已生成")
                    await event.send(MessageChain([Image.fromFileSystem(chart)]))
            except Exception:
                pass

            return self._send_text(event, "\n".join(report))

        except Exception as e:
            logger.error(f"分析插件状态失败: {e}")
            return self._send_text(event, f"❌ 分析插件状态时出错: {str(e)}")

    @filter.command("reset", priority=200)
    async def reset_plugin(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """重置插件（清空缓存和事件日志）"""
        try:
            text = event.message_str.strip()
            import re
            m = re.match(r"^reset(?:\s+(\w+))?$", text)
            if not m:
                return self._send_text(event, "❌ 用法: /reset [plugin_name]")

            plugin_name = m.group(1)

            if plugin_name:
                # 重置指定插件
                self._plugin_snapshots.pop(plugin_name, None)
                self._plugin_events = [e for e in self._plugin_events if e["plugin"] != plugin_name]
                self._save_events()
                return self._send_text(event, f"✅ 已重置插件: {plugin_name}")
            else:
                # 重置所有
                self._plugin_snapshots.clear()
                self._plugin_events.clear()
                self._session_cache.clear()
                self._save_events()
                return self._send_text(event, "✅ 已重置所有插件状态和缓存")

        except Exception as e:
            logger.error(f"重置插件失败: {e}")
            return self._send_text(event, f"❌ 重置插件时出错: {str(e)}")

    @filter.command("log", priority=200)
    async def show_log(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """显示插件事件日志"""
        try:
            text = event.message_str.strip()
            import re
            m = re.match(r"^log(?:\s+(\w+))?$", text)
            if not m:
                return self._send_text(event, "❌ 用法: /log [plugin_name]")

            plugin_name = m.group(1)

            if plugin_name:
                # 过滤指定插件的日志
                events = [e for e in self._plugin_events if e["plugin"] == plugin_name]
            else:
                # 显示所有日志
                events = self._plugin_events

            if not events:
                return self._send_text(event, "📝 没有事件日志记录")

            # 最近 20 条
            recent = events[-20:]

            report = [
                f"📝 插件事件日志 (共 {len(events)} 条)",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ]

            for evt in reversed(recent):
                icon = "🆕" if evt["type"] == "new" else "⬆️" if evt["type"] == "updated" else "🗑️" if evt["type"] == "deleted" else "📋"
                time_str = evt["time"].split("T")[1][:8] if "T" in evt["time"] else evt["time"]
                report.append(f"{icon} {time_str} [{evt['plugin']}] {evt['type']}")

            if len(events) > 20:
                report.append(f"\n... 还有 {len(events) - 20} 条历史记录")

            return self._send_text(event, "\n".join(report))

        except Exception as e:
            logger.error(f"显示日志失败: {e}")
            return self._send_text(event, f"❌ 显示日志时出错: {str(e)}")

    # ========== 图表生成（可选 Pillow） ==========

    def _generate_context_chart(self, role_counts: dict, total_messages: int, total_tokens: int) -> str | None:
        """生成上下文分析图表（需要 Pillow）"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return None

        try:
            width, height = 600, 400
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)

            # 标题
            draw.text((20, 20), "会话上下文分析", fill='black')

            # 饼图数据
            labels = ['用户消息', '助手回复', '系统消息']
            values = [role_counts.get('user', 0), role_counts.get('assistant', 0), role_counts.get('system', 0)]
            colors = ['#4CAF50', '#2196F3', '#FF9800']

            # 简单绘制柱状图
            bar_width = 80
            start_x = 100
            max_val = max(values) if max(values) > 0 else 1

            for i, (label, value, color) in enumerate(zip(labels, values, colors)):
                x = start_x + i * 120
                bar_height = int((value / max_val) * 200) if max_val > 0 else 0
                draw.rectangle([x, 250 - bar_height, x + bar_width, 250], fill=color)
                draw.text((x, 260), f"{label}\n{value}条", fill='black')

            # 保存
            chart_path = os.path.join(self.data_dir, "context_chart.png")
            img.save(chart_path)
            return chart_path

        except Exception as e:
            logger.warning(f"生成上下文图表失败: {e}")
            return None

    def _generate_status_chart(self, cpu: float, memory: float, disk: float) -> str | None:
        """生成系统状态图表（需要 Pillow）"""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None

        try:
            width, height = 600, 200
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)

            # 标题
            draw.text((20, 20), "系统状态", fill='black')

            # 仪表盘
            metrics = [("CPU", cpu), ("内存", memory), ("磁盘", disk)]
            for i, (label, value) in enumerate(metrics):
                x = 100 + i * 160
                # 背景圆
                draw.ellipse([x, 60, x + 80, 140], outline='gray', width=3)
                # 填充弧度
                angle = int(value * 3.6)
                draw.arc([x, 60, x + 80, 140], 0, angle, fill='green', width=3)
                draw.text((x + 20, 150), f"{label}: {value:.1f}%", fill='black')

            chart_path = os.path.join(self.data_dir, "status_chart.png")
            img.save(chart_path)
            return chart_path

        except Exception as e:
            logger.warning(f"生成状态图表失败: {e}")
            return None

    def _generate_plugins_chart(self, stars: list) -> str | None:
        """生成插件状态图表（需要 Pillow）"""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None

        try:
            width, height = 600, 300
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)

            # 标题
            draw.text((20, 20), "插件状态", fill='black')

            # 激活/未激活数量
            active = sum(1 for s in stars if s.activated)
            inactive = len(stars) - active

            # 饼图
            center_x, center_y, radius = 300, 150, 80
            if active > 0:
                draw.pieslice([center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                              0, int(active / len(stars) * 360), fill='green')
            if inactive > 0:
                draw.pieslice([center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                              int(active / len(stars) * 360), 360, fill='red')

            # 图例
            draw.rectangle([450, 100, 470, 120], fill='green')
            draw.text((480, 100), f"已激活: {active}", fill='black')
            draw.rectangle([450, 140, 470, 160], fill='red')
            draw.text((480, 140), f"未激活: {inactive}", fill='black')

            chart_path = os.path.join(self.data_dir, "plugins_chart.png")
            img.save(chart_path)
            return chart_path

        except Exception as e:
            logger.warning(f"生成插件图表失败: {e}")
            return None

    # ========== 工具方法 ==========

    def _send_text(self, event, text: str) -> MessageEventResult:
        """构造纯文本回复结果"""
        return event.chain_result([Plain(text)])

    async def terminate(self):
        """插件卸载时清理"""
        try:
            self._save_events()
        except Exception:
            pass
