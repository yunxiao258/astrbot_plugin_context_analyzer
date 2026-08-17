"""AstrBot 上下文分析插件：LLM 会话分析、系统状态监控、插件生命周期管理"""

import asyncio
import csv
import json
import os
import re
import time
from datetime import datetime, timedelta

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import MessageChain, MessageEventResult
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import File, Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.star.star import StarMetadata

# 插件元数据
PLUGIN_NAME = "astrbot_plugin_context_analyzer"
PLUGIN_AUTHOR = "Administrator"
PLUGIN_DESC = "LLM 上下文分析、系统状态监控、插件生命周期管理"
PLUGIN_VERSION = "1.3.0"

# ========== 内置中文情绪词典（积极 ≥80 词） ==========
POSITIVE_WORDS: tuple[str, ...] = (
    "开心", "高兴", "快乐", "愉快", "兴奋", "喜悦", "欢喜", "满意", "满足", "幸福",
    "幸运", "美好", "美滋滋", "很棒", "真棒", "太棒", "点赞", "真赞", "厉害", "真厉害",
    "优秀", "给力", "加油", "不错", "真不错", "好耶", "绝了", "真绝", "yyds", "666",
    "真牛", "牛逼", "太牛", "真爽", "太爽", "惊艳", "惊喜", "喜欢", "爱了", "爱死",
    "超爱", "感动", "暖心", "温暖", "温馨", "甜蜜", "笑死", "哈哈", "嘿嘿", "嘻嘻",
    "哇塞", "妙啊", "精彩", "完美", "满分", "好评", "划算", "赚了", "中奖", "成功",
    "胜利", "赢了", "搞定", "通过", "恢复", "好转", "提升", "增长", "进步", "顺利",
    "好运", "棒棒哒", "可爱", "可可爱爱", "双赢", "爽歪歪", "冲鸭", "加油鸭", "太可爱", "好喜欢",
    "真喜欢", "开心死", "高兴死", "快乐死", "幸福死", "真香", "宝藏",
)

# ========== 内置中文情绪词典（消极 ≥80 词） ==========
NEGATIVE_WORDS: tuple[str, ...] = (
    "难过", "伤心", "悲伤", "痛苦", "绝望", "崩溃", "裂开", "无语", "烦死", "烦躁",
    "焦虑", "担心", "害怕", "恐惧", "生气", "愤怒", "恼火", "讨厌", "恶心", "反感",
    "失望", "沮丧", "郁闷", "憋屈", "委屈", "心塞", "扎心", "难受", "头疼", "好累",
    "疲惫", "疲倦", "困死", "无聊", "没意思", "烦人", "垃圾", "太差", "差劲", "糟糕",
    "完蛋", "失败", "输了", "亏了", "亏死", "后悔", "心疼", "心碎", "哭了", "呜呜",
    "泪目", "想哭", "哭死", "心态崩", "破防", "emo", "自闭", "摆烂", "躺平", "咸鱼",
    "社死", "尴尬", "丢人", "丢脸", "出丑", "被坑", "踩坑", "翻车", "炸了", "气死",
    "气炸", "火大", "脑溢血", "想吐", "受不了", "扛不住", "顶不住", "撑不住", "放弃", "没救了",
    "凉了", "凉凉", "白费", "白搭", "泡汤", "黄了", "吹了", "亏本", "赔钱", "被骗",
    "上当", "崩溃了", "心累", "绝望死", "难受死", "恶心死",
)

# ========== 话题分析内置停用词表 ==========
# 双字及以上停用词（精确过滤）
STOP_WORDS: frozenset[str] = frozenset({
    "我们", "你们", "他们", "她们", "它们", "这个", "那个", "这些", "那些",
    "什么", "怎么", "为什么", "因为", "所以", "但是", "可是", "然后", "而且",
    "或者", "如果", "虽然", "即使", "已经", "正在", "将要", "可以", "可能",
    "应该", "必须", "一定", "非常", "就是", "还是", "只是", "不过", "并且",
    "以及", "一下", "一点", "一个", "一种", "一天", "一会儿", "大家", "今天",
    "明天", "昨天", "现在", "时候", "这样", "那样", "等等", "之类", "来说",
    "而言", "关于", "对于", "通过", "进行", "没有", "不是", "还有", "其实",
    "真的", "确实", "果然", "反正", "当然", "毕竟", "居然", "竟然", "到底",
    "究竟", "稍微", "有点", "有些", "一直", "一起", "一般", "刚才", "刚刚",
    "马上", "立刻", "突然", "忽然", "最终", "最后", "开始", "结束", "东西",
    "事情", "问题", "情况", "时候", "还有", "觉得", "知道", "看到", "听到",
})
# 单字停用字（用于双字词/多字词过滤规则）
STOP_CHARS: frozenset[str] = frozenset(
    "的了吗呢啊吧呀哦嗯哈嘿诶哎哟哇嘛啦也都就是有在不没我你他她它"
    "这那什么怎为因所但而或如虽即已正将可能应该必须定非常太真只过"
    "并且以及一点大家等之类来说言关对进行好很最更再又才别要会想"
    "说看到去给把被让叫用做"
)

# ========== 会话自动摘要常量 ==========
SESSION_GAP_SECONDS = 600  # 相邻消息间隔超过 10 分钟视为新会话
SESSION_SUMMARY_THRESHOLD = 50  # 单场会话消息数 ≥50 触发自动摘要
SESSION_MAX_MSGS = 100  # 内存中每个会话最多保留的消息条数
SENTIMENT_POSITIVE_THRESHOLD = 0.05  # 情绪分数高于该值判为积极
SENTIMENT_NEGATIVE_THRESHOLD = -0.05  # 情绪分数低于该值判为消极


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
        self._load_snapshots()

        # 会话上下文缓存（内存）
        self._session_cache: dict[str, dict] = {}
        # 日报/周报后台任务
        self._report_task: asyncio.Task | None = None
        self._report_running = False

        # ===== 新增：情绪趋势 / 话题聚类 / 会话自动摘要 =====
        # 每日统计（消息数、情绪分布、话题词频），独立文件持久化，保留最近 30 天
        self._daily_stats: dict[str, dict] = {}
        self._stats_save_counter = 0
        self._load_daily_stats()
        # 群活跃会话跟踪（内存）：umo -> {"start_ts", "last_ts", "count", "summarized", "msgs"}
        self._active_sessions: dict[str, dict] = {}
        # LLM 话题一句话摘要缓存（内存）：date_str -> 摘要
        self._topic_summaries: dict[str, str] = {}

        logger.info(f"【{PLUGIN_NAME}】插件初始化完成")

    # ========== 工具方法 ==========

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """是否管理员会话（admin_umos 白名单）"""
        umos = self._admin_umos()
        return str(event.session) in umos if umos else False

    def _admin_umos(self) -> list[str]:
        v = self.config.get("admin_umos", "")
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return list(v or [])

    def _deny(self) -> str:
        umos = self._admin_umos()
        if not umos:
            return (
                "本插件未配置管理员白名单（admin_umos），系统管理命令不可用。\n"
                "请在插件配置中填写 admin_umos（如 default:GroupMessage:1234567890）后重启 AstrBot。"
            )
        return "你没有执行此命令的权限（不在 admin_umos 白名单内）"

    def _load_events(self):
        """从磁盘加载插件事件日志（校验结构，损坏/非预期格式时重置）"""
        try:
            events_file = os.path.join(self.data_dir, "plugin_events.json")
            if os.path.exists(events_file):
                with open(events_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._plugin_events = data
                else:
                    logger.warning("插件事件日志格式异常，已重置")
        except Exception as e:
            logger.warning(f"加载插件事件日志失败: {e}")

    def _save_events(self):
        """保存插件事件日志到磁盘（内存与磁盘同步截断到 max_events 条）"""
        try:
            events_file = os.path.join(self.data_dir, "plugin_events.json")
            # 只保留最近 max_events 条事件（同时截断内存列表，避免无限增长）
            max_events = int(self.config.get("max_events", 500) or 500)
            self._plugin_events = self._plugin_events[-max_events:]
            os.makedirs(os.path.dirname(events_file), exist_ok=True)
            tmp = events_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._plugin_events, f, ensure_ascii=False, indent=2)
            os.replace(tmp, events_file)
        except Exception as e:
            logger.warning(f"保存插件事件日志失败: {e}")

    def _load_snapshots(self):
        """从磁盘加载插件快照（校验结构，损坏/非预期格式时重置）"""
        try:
            snap_file = os.path.join(self.data_dir, "plugin_snapshots.json")
            if os.path.exists(snap_file):
                with open(snap_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._plugin_snapshots = data
                else:
                    logger.warning("插件快照格式异常，已重置")
        except Exception as e:
            logger.warning(f"加载插件快照失败: {e}")

    def _save_snapshots(self):
        """保存插件快照到磁盘"""
        try:
            snap_file = os.path.join(self.data_dir, "plugin_snapshots.json")
            os.makedirs(os.path.dirname(snap_file), exist_ok=True)
            tmp = snap_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._plugin_snapshots, f, ensure_ascii=False, indent=2)
            os.replace(tmp, snap_file)
        except Exception as e:
            logger.warning(f"保存插件快照失败: {e}")

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

    def _extract_text_from_content(self, content: dict) -> str:
        """从平台消息历史 content 中提取纯文本。

        AstrBot 存储的消息历史 content 结构为:
            {"type": "user"/"bot", "message": [{"type": "plain", "text": "..."}, ...]}
        """
        try:
            message = content.get("message", [])
            if not isinstance(message, list):
                return ""
            parts = []
            for part in message:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "plain":
                    text = part.get("text", "")
                    if isinstance(text, str) and text:
                        parts.append(text)
                elif ptype == "image":
                    parts.append("[图片]")
                elif ptype == "tool_call":
                    parts.append("[工具调用]")
                elif ptype == "think":
                    parts.append("[思考]")
            return " ".join(parts).strip()
        except Exception:
            return ""

    async def _get_session_history(self, event: AstrMessageEvent) -> tuple[list[dict], str]:
        """获取当前会话的消息历史，返回 (记录列表, 数据来源说明)。

        记录格式: [{"role": "user"/"assistant"/"system", "text": "..."}]
        优先从 LLM 会话上下文（conversation）获取，回退到平台消息历史。
        """
        history: list[dict] = []
        source = "会话上下文"

        # 方式一：LLM 会话上下文（OpenAI 格式，包含 role/content）
        try:
            conv_mgr = self.context.conversation_manager
            if conv_mgr:
                umo = event.unified_msg_origin
                conv_id = await conv_mgr.get_curr_conversation_id(umo)
                if conv_id:
                    conv = await conv_mgr.get_conversation(umo, conv_id)
                    if conv and conv.history:
                        try:
                            raw_history = json.loads(conv.history)
                        except (json.JSONDecodeError, TypeError):
                            raw_history = []
                        for item in raw_history:
                            if not isinstance(item, dict):
                                continue
                            role = item.get("role", "unknown")
                            content = item.get("content", "")
                            if not isinstance(content, str):
                                content = str(content) if content else ""
                            history.append({"role": role, "text": content})
        except Exception as e:
            logger.warning(f"获取会话上下文失败: {e}")

        if history:
            return history, source

        # 方式二：平台消息历史
        source = "平台消息历史"
        try:
            history_mgr = self.context.message_history_manager
            if history_mgr:
                # 存储端以 unified_msg_origin（完整 UMO）为 user_id 键
                platform_id = event.get_platform_id()
                user_id = event.unified_msg_origin or (
                    event.session.session_id if event.session else None
                )
                records = await history_mgr.get(
                    platform_id, user_id, page=1, page_size=100
                )
                for record in records:
                    content = getattr(record, "content", None)
                    if not isinstance(content, dict):
                        continue
                    role = "assistant" if content.get("type") == "bot" else "user"
                    text = self._extract_text_from_content(content)
                    history.append({"role": role, "text": text})
        except Exception as e:
            logger.warning(f"获取平台消息历史失败: {e}")

        return history, source

    # ========== 导出与日报/周报 ==========

    def _exports_dir(self) -> str:
        d = os.path.join(self.data_dir, "exports")
        os.makedirs(d, exist_ok=True)
        return d

    def _build_export_data(self, history: list[dict], source: str) -> dict:
        """构造导出数据结构"""
        return {
            "exported_at": datetime.now().isoformat(),
            "source": source,
            "message_count": len(history),
            "messages": [{"role": m["role"], "text": m["text"]} for m in history],
        }

    def _write_export_file(self, data: dict, fmt: str) -> str:
        """把导出数据写为 json/csv 文件，返回文件路径"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "csv":
            path = os.path.join(self._exports_dir(), f"context_export_{stamp}.csv")
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["role", "text"])
                for m in data["messages"]:
                    writer.writerow([m["role"], (m["text"] or "").replace("\n", " ")])
            return path
        path = os.path.join(self._exports_dir(), f"context_export_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    async def _export_history(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """导出当前会话聊天记录为文件（管理员）；支持 /context export [json|csv] [条数]"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        fmt = "json"
        fm = re.search(r"export\s+(json|csv)", event.message_str.strip(), re.I)
        if fm:
            fmt = fm.group(1).lower()
        # 可选条数筛选：/context export json 50（导出最近 50 条）
        limit = 0
        lm = re.search(r"\b(\d{1,5})\b", event.message_str.strip())
        if lm:
            limit = int(lm.group(1))
        history, source = await self._get_session_history(event)
        if not history:
            return self._send_text(event, "📂 当前会话没有可导出的消息记录")
        total = len(history)
        if limit > 0:
            history = history[-limit:]
        try:
            data = self._build_export_data(history, source)
            path = self._write_export_file(data, fmt)
            name = os.path.basename(path)
            tail = f"（最近 {limit} 条）" if limit else ""
            await event.send(
                MessageChain(
                    [
                        Plain(f"📂 已导出 {len(history)}/{total} 条消息{tail}（来源: {source}）"),
                        File(name=name, file=path),
                    ]
                )
            )
            return None
        except Exception as e:
            logger.error(f"导出聊天记录失败: {e}")
            return self._send_text(event, f"❌ 导出失败: {str(e)}")

    @staticmethod
    def _agg_events(events: list[dict], since: str) -> tuple[int, dict, list[dict]]:
        """统计 since 之后的事件：返回 (总数, 类型分布 dict, 错误事件列表)"""
        total = 0
        by_type: dict[str, int] = {}
        errors = []
        for e in events:
            if e.get("time", "") < since:
                continue
            total += 1
            t = e.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            if t == "error":
                errors.append(e)
        return total, by_type, errors

    def _build_daily_report(self, events: list[dict]) -> str:
        """构建某日报表文本（插件事件日志 + 情绪/话题分析段落）"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        since = f"{yesterday}T00:00:00"
        total, by_type, errors = self._agg_events(events, since)
        label = f"{yesterday} 插件事件日报"
        if total == 0:
            lines = [f"📅 {label}", "昨天没有记录到任何插件事件。"]
        else:
            lines = [f"📅 {label}", "━━━━━━━━━━━━━━━━━━━━━━", f"🔢 事件总数: {total} 条"]
            type_zh = {
                "loaded": "插件加载", "unloaded": "插件卸载", "error": "运行错误",
                "new": "新增", "updated": "更新", "deleted": "删除",
            }
            for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"  {type_zh.get(t, t)}: {n} 条")
            if errors:
                lines.append("")
                lines.append(f"❌ 出错插件（{len(errors)} 个）:")
                for e in errors[:8]:
                    lines.append(f"  - {e.get('plugin', '?')}: {(e.get('details') or {}).get('error', '')[:40]}")
        # 附加：情绪分布 + 最近 7 天情绪趋势 + 今日话题 Top5（不影响原有内容）
        extra = self._build_daily_analysis_section(yesterday)
        if extra:
            lines.append("")
            lines.append(extra)
        return "\n".join(lines)

    def _build_weekly_report(self, events: list[dict]) -> str:
        """构建周报文本（最近 7 天聚合）"""
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")
        total, by_type, errors = self._agg_events(events, since)
        label = "最近 7 天插件事件周报"
        if total == 0:
            return f"📊 {label}\n近 7 天没有记录到任何插件事件。"
        lines = [f"📊 {label}", "━━━━━━━━━━━━━━━━━━━━━━", f"🔢 事件总数: {total} 条"]
        type_zh = {
            "loaded": "插件加载", "unloaded": "插件卸载", "error": "运行错误",
            "new": "新增", "updated": "更新", "deleted": "删除",
        }
        for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {type_zh.get(t, t)}: {n} 条")
        if errors:
            lines.append("")
            lines.append(f"❌ 出错插件（{len(errors)} 个）:")
            for e in errors[:10]:
                lines.append(f"  - {e.get('plugin', '?')}: {(e.get('details') or {}).get('error', '')[:40]}")
        return "\n".join(lines)

    async def _manual_daily(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """手动生成昨日日报（管理员）"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        return self._send_text(event, self._build_daily_report(self._plugin_events))

    async def _manual_weekly(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """手动生成周报（管理员）"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        return self._send_text(event, self._build_weekly_report(self._plugin_events))

    def _report_targets(self) -> list[str]:
        v = self.config.get("report_umo", "")
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return list(v or [])

    async def _send_report(self, text: str):
        for umo in self._report_targets():
            try:
                await self.context.send_message(umo, MessageChain([Plain(text)]))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"发送日报到 {umo} 失败: {e}")

    @filter.on_astrbot_loaded()
    async def _start_report_loop(self):
        """AstrBot 加载完成后启动日报/周报定时任务"""
        self._start_report_loop_sync()

    def initialize(self):
        """插件热重载后幂等启动日报/周报定时任务（on_astrbot_loaded 热重载不触发）"""
        self._start_report_loop_sync()

    def _start_report_loop_sync(self):
        """幂等启动日报/周报循环；未启用或已在运行则跳过"""
        if not self.config.get("report_enabled", False):
            return
        if self._report_running:
            return
        self._report_running = True
        self._report_task = asyncio.create_task(self._report_loop())

    async def _report_loop(self):
        """定时循环：每天到 report_time 发昨日日报；周一随日报一并发送周报"""
        last_daily = ""
        last_weekly = ""
        while self._report_running:
            try:
                now = datetime.now()
                target = str(self.config.get("report_time", "08:00") or "08:00").strip()
                # 校验 report_time 格式（HH:MM），非法值回退默认，避免永远不触发
                if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", target):
                    target = "08:00"
                cur = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")
                targets = self._report_targets()
                # 日报：到达/越过 report_time 后一次性触发（防重复由 last_daily 保证）
                if cur >= target and last_daily != today and targets:
                    last_daily = today
                    await self._send_report(self._build_daily_report(self._plugin_events))
                # 周报：周一且当日已到 report_time 时随日报一并发送
                if now.weekday() == 0 and cur >= target and last_weekly != today and targets:
                    last_weekly = today
                    await self._send_report(self._build_weekly_report(self._plugin_events))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"日报/周报任务异常: {e}")
            await asyncio.sleep(30)

    # ========== 情绪趋势分析（内置词典 + 块字符趋势图） ==========

    def _score_sentiment(self, text) -> float:
        """情绪打分：词典匹配逐词累加（积极 +1 / 消极 -1），归一化到 [-1, 1]。

        归一化公式: (积极次数 - 消极次数) / (积极次数 + 消极次数)；无命中返回 0。
        脏输入（None、非字符串）防御性返回 0，不抛异常。
        """
        if not text or not isinstance(text, str):
            return 0.0
        pos = sum(text.count(w) for w in POSITIVE_WORDS)
        neg = sum(text.count(w) for w in NEGATIVE_WORDS)
        if pos + neg == 0:
            return 0.0
        return (pos - neg) / (pos + neg)

    @staticmethod
    def _classify_sentiment(score: float) -> str:
        """按分数将情绪分为 积极/中性/消极 三类"""
        if score > SENTIMENT_POSITIVE_THRESHOLD:
            return "积极"
        if score < SENTIMENT_NEGATIVE_THRESHOLD:
            return "消极"
        return "中性"

    def _build_mood_trend(self, days: int = 7) -> str:
        """最近 N 天情绪趋势文本图（块字符条形图，每行一天，最多 10 格）"""
        lines = []
        now = datetime.now()
        for i in range(days - 1, -1, -1):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            stat = self._daily_stats.get(d) or {}
            pos = int(stat.get("pos") or 0)
            neu = int(stat.get("neu") or 0)
            neg = int(stat.get("neg") or 0)
            total = pos + neu + neg
            if total == 0:
                lines.append(f"  {d[5:]} │ 无数据")
                continue
            pos_b = round(pos / total * 10)
            neg_b = round(neg / total * 10)
            neu_b = max(0, 10 - pos_b - neg_b)
            bar = "█" * pos_b + "·" * neu_b + "░" * neg_b
            lines.append(
                f"  {d[5:]} │ {bar} 积极 {pos / total * 100:.0f}% "
                f"中性 {neu / total * 100:.0f}% 消极 {neg / total * 100:.0f}%（{total} 条）"
            )
        return "\n".join(lines)

    def _build_mood_section(self, date_str: str) -> str:
        """指定日期的情绪分布一行摘要；无数据返回空串"""
        stat = self._daily_stats.get(date_str) or {}
        total = int(stat.get("msg_count") or 0)
        if total <= 0:
            return ""
        pos = int(stat.get("pos") or 0)
        neu = int(stat.get("neu") or 0)
        neg = int(stat.get("neg") or 0)
        denom = max(pos + neu + neg, 1)
        return (
            f"😊 情绪分布: 积极 {pos / denom * 100:.1f}% · 中性 {neu / denom * 100:.1f}% · "
            f"消极 {neg / denom * 100:.1f}%（共 {total} 条消息）"
        )

    # ========== 话题聚类（内置正则分词 + 停用词过滤） ==========

    @staticmethod
    def _extract_ngrams(text, min_n: int = 2, max_n: int = 6) -> list[str]:
        """内置中文分词：正则提取连续中文串，按 2-6 字窗口切出候选词组。

        长度在 [min_n, max_n] 内的中文串直接作为候选；超长串滑动窗口取 2-6 字
        子串并去重，避免重复膨胀。脏输入返回空列表。
        """
        words: list[str] = []
        if not text or not isinstance(text, str):
            return words
        for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
            n = len(chunk)
            if n < min_n:
                continue
            if n <= max_n:
                words.append(chunk)
                continue
            seen: set[str] = set()
            for w in range(min_n, max_n + 1):
                for i in range(0, n - w + 1):
                    cand = chunk[i:i + w]
                    if cand not in seen:
                        seen.add(cand)
                        words.append(cand)
        return words

    @staticmethod
    def _filter_stopwords(words: list[str]) -> list[str]:
        """停用词过滤：
        1. 命中 STOP_WORDS（双字以上停用词）剔除；
        2. 双字词含任一停用单字剔除（如 去爬/我们/可以）；
        3. 三字及以上词全部由停用单字组成时剔除（如 为什么）；
        4. 三字及以上词以停用单字开头或结尾时剔除（如 去爬山/天气好）。
        """
        out: list[str] = []
        for w in words:
            if not w:
                continue
            if w in STOP_WORDS:
                continue
            if len(w) == 2:
                if w[0] in STOP_CHARS or w[1] in STOP_CHARS:
                    continue
            elif len(w) >= 3:
                if all(c in STOP_CHARS for c in w):
                    continue
                if w[0] in STOP_CHARS or w[-1] in STOP_CHARS:
                    continue
            out.append(w)
        return out

    def _extract_topics(self, texts: list[str], top: int = 5) -> list[tuple[str, int]]:
        """按日统计高频词作为话题：分词 + 停用词过滤 + 词频排序，返回 TopN [(词, 次数)]"""
        counter: dict[str, int] = {}
        for t in texts:
            for w in self._filter_stopwords(self._extract_ngrams(t)):
                counter[w] = counter.get(w, 0) + 1
        ranked = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
        return ranked[:top]

    @staticmethod
    def _topics_from_stat(stat: dict, top: int = 5) -> list[tuple[str, int]]:
        """从每日统计的 words 词频字典中取话题 TopN；脏数据防御性返回空列表"""
        words = stat.get("words") if isinstance(stat, dict) else None
        if not isinstance(words, dict) or not words:
            return []
        ranked = sorted(words.items(), key=lambda x: (-x[1], x[0]))
        return ranked[:top]

    async def _llm_summarize(self, prompt: str) -> str | None:
        """调用当前 LLM 提供商生成文本；无可用 LLM / 调用失败返回 None（调用方回退规则）"""
        try:
            if self.context is None:
                return None
            provider = self.context.get_using_provider()
            if provider is None or not hasattr(provider, "text_chat"):
                return None
            resp = await provider.text_chat(prompt)
            if resp is None:
                return None
            text = getattr(resp, "completion_text", None) or ""
            return text.strip() or None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"LLM 摘要调用失败，将回退规则抽取: {e}")
            return None

    def _build_daily_analysis_section(self, date_str: str) -> str:
        """日报附加分析段落：情绪分布 + 7 天趋势文本图 + 今日话题 Top5；无数据返回空串"""
        parts: list[str] = []
        mood = self._build_mood_section(date_str)
        if mood:
            parts.append(mood)
        trend = self._build_mood_trend(7)
        if trend:
            parts.append("📈 最近 7 天情绪趋势:")
            parts.append(trend)
        topics = self._topics_from_stat(self._daily_stats.get(date_str) or {}, 5)
        if topics:
            parts.append(f"🔥 今日话题 Top5（{date_str}）:")
            for i, (w, c) in enumerate(topics, 1):
                parts.append(f"  {i}. {w} ({c} 次)")
            summary = self._topic_summaries.get(date_str)
            if summary:
                parts.append(f"📝 话题摘要: {summary}")
        return "\n".join(parts)

    # ========== 每日统计持久化（独立文件，原子写） ==========

    def _load_daily_stats(self):
        """从磁盘加载每日统计（校验结构，损坏/非预期格式时重置）"""
        try:
            stats_file = os.path.join(self.data_dir, "daily_stats.json")
            if os.path.exists(stats_file):
                with open(stats_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._daily_stats = data
                else:
                    logger.warning("每日统计格式异常，已重置")
        except Exception as e:
            logger.warning(f"加载每日统计失败: {e}")

    def _save_daily_stats(self):
        """保存每日统计到独立文件（原子写；只保留最近 30 天）"""
        try:
            cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            self._daily_stats = {k: v for k, v in self._daily_stats.items() if k >= cutoff}
            stats_file = os.path.join(self.data_dir, "daily_stats.json")
            os.makedirs(os.path.dirname(stats_file), exist_ok=True)
            tmp = stats_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._daily_stats, f, ensure_ascii=False, indent=2)
            os.replace(tmp, stats_file)
        except Exception as e:
            logger.warning(f"保存每日统计失败: {e}")

    # ========== 会话自动摘要（间隔切分 + 阈值触发 + 防重复） ==========

    @staticmethod
    def _split_sessions(messages: list[tuple], gap_seconds: int = SESSION_GAP_SECONDS) -> list[dict]:
        """把 (timestamp, text) 消息列表按相邻间隔切分为会话列表。

        相邻消息间隔 > gap_seconds 视为新会话；超长间隔自动重置，防止全天候误判。
        返回 [{"start_ts", "last_ts", "count", "msgs"}, ...]
        """
        sessions: list[dict] = []
        cur: dict | None = None
        for ts, text in messages:
            if cur is None or (ts - cur["last_ts"]) > gap_seconds:
                cur = {"start_ts": ts, "last_ts": ts, "count": 0, "msgs": []}
                sessions.append(cur)
            cur["last_ts"] = max(cur["last_ts"], ts)
            cur["count"] += 1
            cur["msgs"].append(text)
        return sessions

    def _track_session(self, umo: str, ts: float, text: str):
        """会话跟踪：相邻消息间隔 > 10 分钟重置为新会话；消息数 ≥ 阈值触发自动摘要（防重复）"""
        sess = self._active_sessions.get(umo)
        if sess is None or (ts - sess["last_ts"]) > SESSION_GAP_SECONDS:
            sess = {"start_ts": ts, "last_ts": ts, "count": 0, "summarized": False, "msgs": []}
            self._active_sessions[umo] = sess
        else:
            sess["last_ts"] = max(sess["last_ts"], ts)
        sess["count"] += 1
        if len(sess["msgs"]) < SESSION_MAX_MSGS:
            sess["msgs"].append((text or "")[:200])
        # 达到阈值且未总结 → 触发自动摘要（先标记防重复；无事件循环时跳过推送）
        if sess["count"] >= SESSION_SUMMARY_THRESHOLD and not sess["summarized"]:
            sess["summarized"] = True
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._auto_summarize_session(umo, dict(sess)))
            except RuntimeError:
                pass  # 无运行事件循环（如离线统计/测试环境），跳过异步推送

    def _build_rule_summary(self, msgs: list[str], max_msg: int = 8, head_len: int = 30, top_words: int = 5) -> str:
        """无 LLM 时的规则抽取摘要：每条消息取前 30 字 + 高频话题词"""
        lines = []
        for m in msgs[:max_msg]:
            m = (m or "").strip().replace("\n", " ")
            if not m:
                continue
            head = m[:head_len]
            if len(m) > head_len:
                head += "…"
            lines.append(f"· {head}")
        if not lines:
            return "（无可摘要消息）"
        topics = self._extract_topics(msgs, top_words)
        words_part = "、".join(f"{w}({c})" for w, c in topics) if topics else "无"
        return "消息要点:\n" + "\n".join(lines) + f"\n高频词: {words_part}"

    async def _summarize_session(self, msgs: list[str]) -> str:
        """会话摘要：有 LLM 用 LLM 总结，无 LLM 用规则抽取（前 30 字 + 高频词）"""
        prompt = (
            "请对以下群聊消息做一段简洁的中文摘要（100 字以内），"
            "概括讨论的主题与结论：\n"
            + "\n".join(f"- {m}" for m in msgs[-50:])
        )
        text = await self._llm_summarize(prompt)
        if text:
            return text
        return self._build_rule_summary(msgs)

    async def _auto_summarize_session(self, umo: str, sess: dict):
        """生成自动摘要并推送到该群，标注「自动摘要」"""
        try:
            if self.context is None:
                return
            summary = await self._summarize_session(sess.get("msgs") or [])
            if not summary:
                return
            start = datetime.fromtimestamp(sess.get("start_ts") or time.time()).strftime("%H:%M")
            count = sess.get("count", 0)
            text = (
                f"📝 自动摘要（本群最近一场活跃会话 {count} 条消息，自 {start} 起）\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n{summary}"
            )
            await self.context.send_message(umo, MessageChain([Plain(text)]))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"自动摘要推送失败: {e}")

    # ========== 群消息实时收集（情绪/话题统计 + 会话跟踪，不拦截消息） ==========

    def _extract_event_text(self, event) -> str:
        """从消息事件提取纯文本（防御：脏消息/非文本不崩溃），优先消息链，回退 message_str"""
        try:
            obj = getattr(event, "message_obj", None)
            if obj is not None:
                msg = getattr(obj, "message", None)
                if isinstance(msg, list):
                    parts = []
                    for comp in msg:
                        if isinstance(comp, Plain):
                            t = getattr(comp, "text", "")
                            if isinstance(t, str) and t:
                                parts.append(t)
                    if parts:
                        return " ".join(parts).strip()
            s = getattr(event, "message_str", "") or ""
            return s.strip() if isinstance(s, str) else ""
        except Exception:
            return ""

    def _record_chat_message(self, event):
        """收集群消息：更新每日情绪/话题统计并跟踪会话活跃度（防御性，失败不影响主流程）"""
        try:
            text = self._extract_event_text(event)
            if not text or text.startswith("/"):
                return  # 空消息与命令消息不参与统计
            ts = time.time()
            try:
                obj = getattr(event, "message_obj", None)
                if obj is not None and getattr(obj, "timestamp", 0):
                    ts = float(obj.timestamp)
            except Exception:
                pass
            umo = str(event.unified_msg_origin) if getattr(event, "unified_msg_origin", None) else ""
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            # 每日统计（情绪分布 + 话题词频）
            stat = self._daily_stats.setdefault(
                date, {"msg_count": 0, "pos": 0, "neu": 0, "neg": 0, "words": {}}
            )
            stat["msg_count"] = int(stat.get("msg_count") or 0) + 1
            cls = self._classify_sentiment(self._score_sentiment(text))
            key = {"积极": "pos", "中性": "neu", "消极": "neg"}[cls]
            stat[key] = int(stat.get(key) or 0) + 1
            words = stat.setdefault("words", {})
            for w in self._filter_stopwords(self._extract_ngrams(text)):
                words[w] = int(words.get(w) or 0) + 1
            # 周期落盘（每 20 条消息一次，降低写盘频率）
            self._stats_save_counter += 1
            if self._stats_save_counter >= 20:
                self._stats_save_counter = 0
                self._save_daily_stats()
            # 会话活跃度跟踪（仅限群内）
            if umo:
                self._track_session(umo, ts, text)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"消息统计失败: {e}")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def _on_group_message_collect(self, event: AstrMessageEvent) -> None:
        """群消息收集钩子：实时统计情绪/话题并跟踪会话（返回 None，不拦截消息）"""
        self._record_chat_message(event)

    # ========== 指令处理 ==========

    @filter.command("context", priority=200)
    async def analyze_context(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """分析当前会话上下文；子命令：export / daily / weekly"""
        # 子命令分发：/context export|daily|weekly
        text = event.message_str.strip()
        m = re.search(r"\b(export|daily|日报|weekly|周报)\b", text)
        sub = m.group(1) if m else ""
        if sub == "export":
            return await self._export_history(event)
        if sub in ("daily", "日报"):
            return await self._manual_daily(event)
        if sub in ("weekly", "周报"):
            return await self._manual_weekly(event)
        try:
            # 获取会话历史（优先 LLM 会话上下文，回退平台消息历史）
            history, source = await self._get_session_history(event)
            total_messages = len(history)
            if total_messages == 0:
                return self._send_text(event, "📊 当前会话没有历史消息记录")

            # 统计信息
            role_counts = {"user": 0, "assistant": 0, "system": 0, "other": 0}
            total_tokens = 0
            for msg in history:
                role = msg["role"]
                text = msg["text"]
                if role in role_counts:
                    role_counts[role] += 1
                else:
                    role_counts["other"] += 1
                total_tokens += self._estimate_tokens(text)

            # 最近消息
            recent = history[-5:] if len(history) >= 5 else history
            recent_lines = []
            for msg in recent:
                role = msg["role"]
                text = (msg["text"] or "")[:50]
                icon = "👤" if role == "user" else "🤖" if role == "assistant" else "⚙️"
                recent_lines.append(f"{icon} {text}...")

            # 生成报告
            report = [
                "📊 会话上下文分析报告",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"🔍 数据来源: {source}",
                f"💬 消息总数: {total_messages} 条",
                f"🔢 预估 Token: {total_tokens:,}",
                "",
                "👥 角色分布:",
                f"  👤 用户消息: {role_counts['user']} 条",
                f"  🤖 助手回复: {role_counts['assistant']} 条",
                f"  ⚙️ 系统消息: {role_counts['system']} 条",
            ]
            if role_counts["other"] > 0:
                report.append(f"  🧩 其他消息: {role_counts['other']} 条")
            report.extend([
                "",
                "📝 最近 5 条消息:",
            ])
            report.extend(recent_lines)

            # 检查是否有图片生成能力（尝试用 Pillow），并尊重 enable_charts 配置
            if self.config.get("enable_charts", True):
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

    @staticmethod
    def _parse_date_arg(event, default: str | None = None) -> str:
        """从命令消息解析可选日期参数 YYYY-MM-DD；非法/缺省回退默认日期（今天）"""
        default = default or datetime.now().strftime("%Y-%m-%d")
        m = re.search(r"\d{4}-\d{2}-\d{2}", getattr(event, "message_str", "") or "")
        if m:
            try:
                datetime.strptime(m.group(0), "%Y-%m-%d")
                return m.group(0)
            except ValueError:
                pass
        return default

    @filter.command("analyze_mood", priority=200)
    async def analyze_mood(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """情绪趋势分析：查看指定日期情绪分布与最近 7 天趋势（管理员）

        用法: /analyze_mood [YYYY-MM-DD]（缺省为今天）
        """
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        try:
            date_str = self._parse_date_arg(event)
            stat = self._daily_stats.get(date_str) or {}
            if not stat.get("msg_count"):
                return self._send_text(event, f"😊 {date_str} 没有可用的消息情绪统计")
            pos = int(stat.get("pos") or 0)
            neu = int(stat.get("neu") or 0)
            neg = int(stat.get("neg") or 0)
            denom = max(pos + neu + neg, 1)
            lines = [
                f"😊 情绪趋势分析（{date_str}）",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"💬 统计消息: {stat['msg_count']} 条",
                f"📊 情绪分布: 积极 {pos / denom * 100:.1f}% · 中性 {neu / denom * 100:.1f}% · "
                f"消极 {neg / denom * 100:.1f}%",
                "",
                "📈 最近 7 天情绪趋势:",
                self._build_mood_trend(7),
            ]
            return self._send_text(event, "\n".join(lines))
        except Exception as e:
            logger.error(f"情绪分析失败: {e}")
            return self._send_text(event, f"❌ 情绪分析失败: {str(e)}")

    @filter.command("analyze_topics", priority=200)
    async def analyze_topics(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """话题聚类：查看指定日期话题 Top5 与一句话摘要（管理员）

        用法: /analyze_topics [YYYY-MM-DD]（缺省为今天）；有 LLM 时自动生成一句话摘要
        """
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        try:
            date_str = self._parse_date_arg(event)
            stat = self._daily_stats.get(date_str) or {}
            topics = self._topics_from_stat(stat, 5)
            if not topics:
                return self._send_text(event, f"🔥 {date_str} 没有可用的消息话题统计")
            lines = [
                f"🔥 话题聚类分析（{date_str}）",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"💬 基于 {stat.get('msg_count', 0)} 条消息",
                "📌 今日话题 Top5:",
            ]
            for i, (w, c) in enumerate(topics, 1):
                lines.append(f"  {i}. {w} ({c} 次)")
            # 有 LLM 接口时生成话题一句话摘要；无 LLM 时直接用词频直出
            words = "、".join(w for w, _ in topics)
            summary = await self._llm_summarize(f"请用一句不超过 30 字的话概括这些群聊话题: {words}")
            if summary:
                self._topic_summaries[date_str] = summary
                lines.append(f"📝 一句话摘要: {summary}")
            return self._send_text(event, "\n".join(lines))
        except Exception as e:
            logger.error(f"话题分析失败: {e}")
            return self._send_text(event, f"❌ 话题分析失败: {str(e)}")

    @filter.command("analyze_session", priority=200)
    async def analyze_session(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """会话自动摘要：查看当前群活跃会话状态或手动触发摘要（管理员）

        用法: /analyze_session         查看会话活跃度
              /analyze_session summary 对当前群当前会话立即生成摘要
        """
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        try:
            umo = str(event.unified_msg_origin) if getattr(event, "unified_msg_origin", None) else ""
            sess = self._active_sessions.get(umo)
            words = (event.message_str or "").split()
            if "summary" in words:
                if not sess or sess["count"] < 2:
                    return self._send_text(event, "💬 当前群暂无活跃会话可摘要")
                summary = await self._summarize_session(sess["msgs"])
                return self._send_text(
                    event, f"📝 会话摘要（{sess['count']} 条消息）\n{summary}"
                )
            if not sess:
                return self._send_text(event, "💬 当前群暂未跟踪到活跃会话")
            start = datetime.fromtimestamp(sess["start_ts"]).strftime("%Y-%m-%d %H:%M")
            dur = max(0.0, (sess["last_ts"] - sess["start_ts"]) / 60)
            status = "✅ 已自动摘要" if sess["summarized"] else "⏳ 未触发摘要"
            lines = [
                "💬 会话活跃度分析",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 会话开始: {start}",
                f"🔢 消息数: {sess['count']} 条",
                f"⏱️ 持续时长: {dur:.0f} 分钟",
                f"📌 状态: {status}",
                f"🎯 摘要触发阈值: {SESSION_SUMMARY_THRESHOLD} 条",
                f"⏲️ 会话切分间隔: {SESSION_GAP_SECONDS // 60} 分钟",
            ]
            return self._send_text(event, "\n".join(lines))
        except Exception as e:
            logger.error(f"会话分析失败: {e}")
            return self._send_text(event, f"❌ 会话分析失败: {str(e)}")

    @filter.command("status", priority=200)
    async def analyze_status(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """分析系统状态（管理员）"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        try:
            import psutil

            # 资源采集移到线程池，避免阻塞事件循环（net_connections 在 Windows 可能 AccessDenied，单独兜底）
            def _collect():
                res = {
                    "cpu": psutil.cpu_percent(interval=1),
                    "memory": psutil.virtual_memory(),
                    "disk": psutil.disk_usage('/'),
                }
                try:
                    res["connections"] = len(psutil.net_connections())
                except Exception:
                    res["connections"] = -1
                return res

            res = await asyncio.to_thread(_collect)
            cpu_percent = res["cpu"]
            memory = res["memory"]
            disk = res["disk"]
            connections = res["connections"]

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
                f"  🌐 网络连接数: {'N/A（无权限读取）' if connections < 0 else connections}",
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
            if self.config.get("enable_charts", True):
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
        """分析插件状态（管理员）"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
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
            self._save_snapshots()

            # 记录变更到事件日志
            for change in changes:
                if change["type"] == "new":
                    self._record_event("new", change["plugin"], {"version": change["version"]})
                elif change["type"] == "updated":
                    self._record_event("updated", change["plugin"], {
                        "old_version": change["old_version"],
                        "new_version": change["new_version"],
                    })
                elif change["type"] == "deleted":
                    self._record_event("deleted", change["plugin"])

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
                    ev_type = evt.get("type", "unknown")
                    ev_time = evt.get("time", "")
                    icon = self._event_icon(ev_type)
                    time_str = ev_time.split("T")[1][:8] if "T" in ev_time else ev_time
                    report.append(f"  {icon} {time_str} - {evt.get('plugin', '?')}")

            # 检查是否有 Pillow
            if self.config.get("enable_charts", True):
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
        """重置插件（清空缓存和事件日志，管理员）"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        try:
            text = event.message_str.strip()
            import re
            m = re.match(r"^reset(?:\s+(\S+))?$", text)
            if not m:
                return self._send_text(event, "❌ 用法: /reset [plugin_name]")

            plugin_name = m.group(1)

            if plugin_name:
                # 重置指定插件
                self._plugin_snapshots.pop(plugin_name, None)
                self._plugin_events = [e for e in self._plugin_events if e.get("plugin") != plugin_name]
                self._save_events()
                self._save_snapshots()
                return self._send_text(event, f"✅ 已重置插件: {plugin_name}")
            else:
                # 重置所有
                self._plugin_snapshots.clear()
                self._plugin_events.clear()
                self._session_cache.clear()
                self._save_events()
                self._save_snapshots()
                return self._send_text(event, "✅ 已重置所有插件状态和缓存")

        except Exception as e:
            logger.error(f"重置插件失败: {e}")
            return self._send_text(event, f"❌ 重置插件时出错: {str(e)}")

    @filter.command("log", priority=200)
    async def show_log(self, event: AstrMessageEvent) -> MessageEventResult | None:
        """显示插件事件日志（管理员）"""
        if not self._is_admin(event):
            return self._send_text(event, self._deny())
        try:
            text = event.message_str.strip()
            import re
            m = re.match(r"^log(?:\s+(\S+))?$", text)
            if not m:
                return self._send_text(event, "❌ 用法: /log [plugin_name]")

            plugin_name = m.group(1)

            if plugin_name:
                # 过滤指定插件的日志
                events = [e for e in self._plugin_events if e.get("plugin") == plugin_name]
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
                ev_type = evt.get("type", "unknown")
                ev_time = evt.get("time", "")
                icon = self._event_icon(ev_type)
                time_str = ev_time.split("T")[1][:8] if "T" in ev_time else ev_time
                report.append(f"{icon} {time_str} [{evt.get('plugin', '?')}] {ev_type}")

            if len(events) > 20:
                report.append(f"\n... 还有 {len(events) - 20} 条历史记录")

            return self._send_text(event, "\n".join(report))

        except Exception as e:
            logger.error(f"显示日志失败: {e}")
            return self._send_text(event, f"❌ 显示日志时出错: {str(e)}")

    # ========== 图表生成（可选 Pillow） ==========

    @staticmethod
    def _load_chart_font(size: int = 16):
        """加载支持中文的字体，找不到时返回 None（使用 PIL 默认字体）"""
        try:
            from PIL import ImageFont
            # 常见 Windows 中文字体
            for font_name in ["msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc", "Deng.ttf"]:
                try:
                    return ImageFont.truetype(font_name, size)
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _new_chart(self, title: str, width: int, height: int, filename: str) -> tuple | None:
        """图表公共骨架：创建白底图 + 标题，返回 (img, draw, font_title, font_label, path)；Pillow 不可用时返回 None"""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None
        try:
            font_title = self._load_chart_font(20)
            font_label = self._load_chart_font(16)
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)
            draw.text((20, 20), title, fill='black', font=font_title)
            return img, draw, font_title, font_label, os.path.join(self.data_dir, filename)
        except Exception as e:
            logger.warning(f"创建图表失败: {e}")
            return None

    def _generate_context_chart(self, role_counts: dict, total_messages: int, total_tokens: int) -> str | None:
        """生成上下文分析图表（需要 Pillow）"""
        base = self._new_chart("会话上下文分析", 600, 400, "context_chart.png")
        if base is None:
            return None

        try:
            img, draw, font_title, font_label, chart_path = base

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
                draw.text((x, 260), f"{label}\n{value}条", fill='black', font=font_label)

            # 保存
            img.save(chart_path)
            return chart_path

        except Exception as e:
            logger.warning(f"生成上下文图表失败: {e}")
            return None

    def _generate_status_chart(self, cpu: float, memory: float, disk: float) -> str | None:
        """生成系统状态图表（需要 Pillow）"""
        base = self._new_chart("系统状态", 600, 200, "status_chart.png")
        if base is None:
            return None

        try:
            img, draw, font_title, font_label, chart_path = base

            # 仪表盘
            metrics = [("CPU", cpu), ("内存", memory), ("磁盘", disk)]
            for i, (label, value) in enumerate(metrics):
                x = 100 + i * 160
                # 背景圆
                draw.ellipse([x, 60, x + 80, 140], outline='gray', width=3)
                # 填充弧度
                angle = int(value * 3.6)
                draw.arc([x, 60, x + 80, 140], 0, angle, fill='green', width=3)
                draw.text((x + 10, 150), f"{label}: {value:.1f}%", fill='black', font=font_label)

            img.save(chart_path)
            return chart_path

        except Exception as e:
            logger.warning(f"生成状态图表失败: {e}")
            return None

    def _generate_plugins_chart(self, stars: list) -> str | None:
        """生成插件状态图表（需要 Pillow）"""
        base = self._new_chart("插件状态", 600, 300, "plugins_chart.png")
        if base is None:
            return None

        try:
            img, draw, font_title, font_label, chart_path = base

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
            draw.text((480, 100), f"已激活: {active}", fill='black', font=font_label)
            draw.rectangle([450, 140, 470, 160], fill='red')
            draw.text((480, 140), f"未激活: {inactive}", fill='black', font=font_label)

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

    @staticmethod
    def _event_icon(event_type: str) -> str:
        """根据事件类型返回对应的图标"""
        icons = {
            "new": "🆕",
            "updated": "⬆️",
            "deleted": "🗑️",
            "loaded": "✅",
            "unloaded": "⏸️",
            "error": "❌",
        }
        return icons.get(event_type, "📋")

    # ========== 插件生命周期事件监听 ==========

    @filter.on_plugin_loaded()
    async def on_plugin_loaded_event(self, metadata: StarMetadata) -> None:
        """插件加载完成时记录事件"""
        try:
            self._record_event("loaded", metadata.name or "unknown", {"version": metadata.version})
        except Exception as e:
            logger.warning(f"记录插件加载事件失败: {e}")

    @filter.on_plugin_unloaded()
    async def on_plugin_unloaded_event(self, metadata: StarMetadata) -> None:
        """插件卸载完成时记录事件"""
        try:
            self._record_event("unloaded", metadata.name or "unknown", {"version": metadata.version})
        except Exception as e:
            logger.warning(f"记录插件卸载事件失败: {e}")

    @filter.on_plugin_error()
    async def on_plugin_error_event(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        handler_name: str,
        error: Exception,
        traceback_text: str,
    ) -> None:
        """插件处理消息异常时记录事件"""
        try:
            self._record_event("error", plugin_name, {
                "handler": handler_name,
                "error": str(error)[:200],
            })
        except Exception as e:
            logger.warning(f"记录插件错误事件失败: {e}")

    async def terminate(self):
        """插件卸载时清理"""
        self._report_running = False
        if self._report_task:
            self._report_task.cancel()
            self._report_task = None
        try:
            self._save_events()
        except Exception:
            pass
        try:
            self._save_daily_stats()
        except Exception:
            pass
