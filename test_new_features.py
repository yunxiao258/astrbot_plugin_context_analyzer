# -*- coding: utf-8 -*-
"""context_analyzer 插件新增能力测试：情绪趋势分析 / 话题聚类 / 会话自动摘要"""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta

import sys
import os

sys.path.insert(0, r"D:\astrbot\data\plugins")

from astrbot_plugin_context_analyzer.main import (  # noqa: E402
    ContextAnalyzerPlugin,
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    SESSION_GAP_SECONDS,
    SESSION_SUMMARY_THRESHOLD,
)


class FakeSession:
    def __init__(self, umo="default:GroupMessage:123"):
        self.umo = umo

    def __str__(self):
        return self.umo


class FakeEvent:
    """最小事件替身：支持 session、message_str、unified_msg_origin 与 send"""
    def __init__(self, message_str="", umo="default:GroupMessage:123"):
        self.session = FakeSession(umo)
        self.message_str = message_str
        self.unified_msg_origin = umo
        self.message_obj = None  # 无消息链时回退 message_str
        self.sent = []

    def chain_result(self, chain):
        return chain

    async def send(self, chain):
        self.sent.append(chain)
        return None


def make_plugin(admin_umos="default:GroupMessage:123"):
    p = ContextAnalyzerPlugin(None, {"admin_umos": admin_umos})
    p.data_dir = tempfile.mkdtemp(prefix="ctx_new_test_")
    return p


class TestSentimentDictionary(unittest.TestCase):
    """情绪词典：规模与关键网络用语"""

    def test_dictionary_size(self):
        self.assertGreaterEqual(len(POSITIVE_WORDS), 80)
        self.assertGreaterEqual(len(NEGATIVE_WORDS), 80)

    def test_internet_slang(self):
        for w in ("好耶", "绝了", "yyds", "真香"):
            self.assertIn(w, POSITIVE_WORDS)
        for w in ("无语", "裂开", "破防", "emo"):
            self.assertIn(w, NEGATIVE_WORDS)

    def test_no_overlap(self):
        overlap = set(POSITIVE_WORDS) & set(NEGATIVE_WORDS)
        self.assertEqual(overlap, set())


class TestSentimentScoring(unittest.TestCase):
    """情绪打分与分类"""

    def test_positive_score(self):
        p = make_plugin()
        self.assertGreater(p._score_sentiment("今天真开心，好耶！"), 0)
        self.assertEqual(p._score_sentiment("好耶"), 1.0)

    def test_negative_score(self):
        p = make_plugin()
        self.assertLess(p._score_sentiment("我裂开了，太无语，难受死"), 0)

    def test_neutral_score(self):
        p = make_plugin()
        self.assertEqual(p._score_sentiment("今天去超市买牛奶"), 0.0)

    def test_mixed_score(self):
        p = make_plugin()
        # 积极 1 次（开心）+ 消极 1 次（无语）→ 归一化 0
        self.assertEqual(p._score_sentiment("开心但无语"), 0.0)

    def test_dirty_input(self):
        p = make_plugin()
        self.assertEqual(p._score_sentiment(None), 0.0)
        self.assertEqual(p._score_sentiment(123), 0.0)
        self.assertEqual(p._score_sentiment(""), 0.0)
        self.assertEqual(p._score_sentiment("   "), 0.0)

    def test_classify(self):
        p = make_plugin()
        self.assertEqual(p._classify_sentiment(0.8), "积极")
        self.assertEqual(p._classify_sentiment(0.0), "中性")
        self.assertEqual(p._classify_sentiment(-0.8), "消极")


class TestTopics(unittest.TestCase):
    """内置分词、停用词过滤与话题提取"""

    def test_extract_ngrams_range(self):
        p = make_plugin()
        words = p._extract_ngrams("今天天气真好呀，大家一起去爬山")
        self.assertTrue(words)
        for w in words:
            self.assertTrue(2 <= len(w) <= 6, f"词组长度越界: {w}")
        self.assertIn("天气", words)
        self.assertIn("爬山", words)

    def test_extract_ngrams_dirty(self):
        p = make_plugin()
        self.assertEqual(p._extract_ngrams(None), [])
        self.assertEqual(p._extract_ngrams(123), [])
        self.assertEqual(p._extract_ngrams(""), [])
        self.assertEqual(p._extract_ngrams("abcd 123 !!!"), [])  # 无中文

    def test_extract_ngrams_short_chunk(self):
        p = make_plugin()
        # 单字中文串长度不足 2，不产出
        self.assertEqual(p._extract_ngrams("天气好啊"), ["天气好啊"])  # 4 字 ≤6 整串

    def test_stopwords_filtered(self):
        p = make_plugin()
        words = p._filter_stopwords(["我们", "可以", "但是", "天气", "爬山", "今天", "为什么"])
        self.assertNotIn("我们", words)  # STOP_WORDS 精确过滤
        self.assertNotIn("可以", words)  # 双字均停用字
        self.assertNotIn("但是", words)
        self.assertNotIn("今天", words)
        self.assertNotIn("为什么", words)  # 三字全停用字
        self.assertIn("天气", words)
        self.assertIn("爬山", words)

    def test_extract_topics_order(self):
        p = make_plugin()
        texts = ["今天天气不错去爬山", "天气很好也去爬山", "明天还想去爬山"]
        topics = p._extract_topics(texts, top=3)
        self.assertEqual(topics[0][0], "爬山")
        self.assertGreaterEqual(topics[0][1], 3)

    def test_topics_from_stat(self):
        p = make_plugin()
        stat = {"words": {"天气": 5, "爬山": 3, "火锅": 8}}
        topics = p._topics_from_stat(stat, 2)
        self.assertEqual(topics, [("火锅", 8), ("天气", 5)])
        self.assertEqual(p._topics_from_stat(None, 5), [])
        self.assertEqual(p._topics_from_stat({}, 5), [])
        self.assertEqual(p._topics_from_stat({"words": "bad"}, 5), [])


class TestSessionSplit(unittest.TestCase):
    """会话切分与摘要触发阈值"""

    def test_split_merge_within_gap(self):
        msgs = [(1000.0, "a"), (1300.0, "b"), (1900.0, "c")]
        sessions = ContextAnalyzerPlugin._split_sessions(msgs, gap_seconds=600)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["count"], 3)

    def test_split_over_gap(self):
        msgs = [(1000.0, "a"), (2000.0, "b")]  # 间隔 1000s > 600s
        sessions = ContextAnalyzerPlugin._split_sessions(msgs, gap_seconds=600)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["count"], 1)
        self.assertEqual(sessions[1]["count"], 1)

    def test_split_long_gap_resets(self):
        # 超长间隔重置：防止全天候误判为同一会话
        msgs = [(1000.0, "a"), (1000.0 + 3600 * 5, "b")]  # 隔 5 小时
        sessions = ContextAnalyzerPlugin._split_sessions(msgs, gap_seconds=600)
        self.assertEqual(len(sessions), 2)

    def test_track_threshold_triggers_once(self):
        p = make_plugin()
        umo = "default:GroupMessage:123"
        ts = 1700000000.0
        for i in range(49):
            p._track_session(umo, ts + i * 60, f"msg{i}")
        sess = p._active_sessions[umo]
        self.assertEqual(sess["count"], 49)
        self.assertFalse(sess["summarized"])
        # 第 50 条触发
        p._track_session(umo, ts + 49 * 60, "msg49")
        self.assertEqual(sess["count"], 50)
        self.assertTrue(sess["summarized"])
        # 防重复：继续追加不再触发
        p._track_session(umo, ts + 50 * 60, "msg50")
        self.assertTrue(sess["summarized"])
        self.assertEqual(sess["count"], 51)

    def test_track_reset_after_gap(self):
        p = make_plugin()
        umo = "default:GroupMessage:123"
        p._track_session(umo, 1000.0, "a")
        p._track_session(umo, 1300.0, "b")
        self.assertEqual(p._active_sessions[umo]["count"], 2)
        # 间隔超过 10 分钟 → 新会话
        p._track_session(umo, 1300.0 + SESSION_GAP_SECONDS + 1, "c")
        sess = p._active_sessions[umo]
        self.assertEqual(sess["count"], 1)
        self.assertEqual(sess["msgs"], ["c"])
        self.assertFalse(sess["summarized"])

    def test_constants(self):
        self.assertEqual(SESSION_GAP_SECONDS, 600)
        self.assertEqual(SESSION_SUMMARY_THRESHOLD, 50)


class TestRuleSummary(unittest.TestCase):
    """无 LLM 时的规则摘要"""

    def test_rule_summary_content(self):
        p = make_plugin()
        msgs = ["今天天气真不错，大家一起去爬山", "爬山好累但很开心", "明天再去一次"]
        text = p._build_rule_summary(msgs)
        self.assertIn("消息要点", text)
        self.assertIn("·", text)
        self.assertIn("高频词", text)

    def test_rule_summary_truncate_30(self):
        p = make_plugin()
        long_msg = "很长很长" * 20  # 80 字
        text = p._build_rule_summary([long_msg])
        self.assertIn("…", text)
        line = next(x for x in text.splitlines() if x.startswith("· "))
        self.assertLessEqual(len(line.replace("· ", "").replace("…", "")), 30)

    def test_rule_summary_empty(self):
        p = make_plugin()
        text = p._build_rule_summary([])
        self.assertIn("无可摘要消息", text)
        self.assertEqual(p._build_rule_summary([None, ""]), "（无可摘要消息）")

    def test_llm_summarize_no_context(self):
        # context=None（无 AstrBot 环境）→ 返回 None，调用方回退规则抽取
        p = make_plugin()
        self.assertIsNone(asyncio.run(p._llm_summarize("test prompt")))
        # 无 LLM 时 _summarize_session 回退规则
        text = asyncio.run(p._summarize_session(["今天天气不错"]))
        self.assertIn("消息要点", text)


class TestMoodTrend(unittest.TestCase):
    """7 天情绪趋势文本图"""

    def test_trend_seven_days(self):
        p = make_plugin()
        now = datetime.now()
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            p._daily_stats[d] = {"msg_count": 10, "pos": 6, "neu": 2, "neg": 2, "words": {}}
        text = p._build_mood_trend(7)
        lines = text.splitlines()
        self.assertEqual(len(lines), 7)
        self.assertIn("█", text)  # 积极块字符
        self.assertIn("░", text)  # 消极块字符
        self.assertIn("积极", text)
        self.assertIn("60%", text)

    def test_trend_no_data(self):
        p = make_plugin()
        text = p._build_mood_trend(7)
        self.assertEqual(len(text.splitlines()), 7)
        self.assertIn("无数据", text)

    def test_trend_ignores_bad_stats(self):
        p = make_plugin()
        now = datetime.now()
        d = now.strftime("%Y-%m-%d")
        p._daily_stats[d] = {"msg_count": "bad", "pos": None, "neu": 0, "neg": 0, "words": {}}
        text = p._build_mood_trend(1)
        self.assertIn("无数据", text)  # 脏数据防御性不崩溃


class TestDailyStatsPersistence(unittest.TestCase):
    """每日统计独立文件持久化（原子写）"""

    def test_save_and_load(self):
        p = make_plugin()
        date = datetime.now().strftime("%Y-%m-%d")
        p._daily_stats[date] = {"msg_count": 5, "pos": 3, "neu": 1, "neg": 1, "words": {"天气": 2}}
        p._save_daily_stats()
        self.assertTrue(os.path.exists(os.path.join(p.data_dir, "daily_stats.json")))
        q = ContextAnalyzerPlugin(None, {"admin_umos": "default:GroupMessage:123"})
        q.data_dir = p.data_dir
        q._load_daily_stats()
        self.assertIn(date, q._daily_stats)
        self.assertEqual(q._daily_stats[date]["msg_count"], 5)
        self.assertEqual(q._daily_stats[date]["words"]["天气"], 2)

    def test_load_corrupted(self):
        p = make_plugin()
        with open(os.path.join(p.data_dir, "daily_stats.json"), "w", encoding="utf-8") as f:
            f.write("{bad json")
        p._load_daily_stats()  # 损坏文件不崩溃
        self.assertEqual(p._daily_stats, {})


class TestRecordChatMessage(unittest.TestCase):
    """群消息实时收集：情绪/话题统计与会话跟踪"""

    def test_record_stats(self):
        p = make_plugin()
        ev = FakeEvent("今天真开心好耶", umo="default:GroupMessage:123")
        p._record_chat_message(ev)
        date = datetime.now().strftime("%Y-%m-%d")
        stat = p._daily_stats[date]
        self.assertEqual(stat["msg_count"], 1)
        self.assertEqual(stat["pos"], 1)
        self.assertEqual(stat["neu"], 0)
        self.assertEqual(p._active_sessions["default:GroupMessage:123"]["count"], 1)

    def test_record_command_skipped(self):
        p = make_plugin()
        p._record_chat_message(FakeEvent("/analyze_mood 2026-08-01"))
        self.assertEqual(p._daily_stats, {})

    def test_record_dirty_message(self):
        p = make_plugin()
        p._record_chat_message(FakeEvent("", umo="default:GroupMessage:123"))
        p._record_chat_message(FakeEvent(None, umo="default:GroupMessage:123"))
        self.assertEqual(p._daily_stats, {})


class TestDailyReportExtension(unittest.TestCase):
    """日报附加分析段落（不影响原有事件日报内容）"""

    def _events(self):
        base = datetime.now() - timedelta(days=1)
        return [{"time": base.replace(hour=8).isoformat(), "type": "loaded", "plugin": "p1", "details": {}}]

    def test_daily_report_includes_analysis(self):
        p = make_plugin()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        p._daily_stats[yesterday] = {
            "msg_count": 10, "pos": 6, "neu": 2, "neg": 2, "words": {"天气": 5, "爬山": 3},
        }
        text = p._build_daily_report(self._events())
        self.assertIn("情绪分布", text)
        self.assertIn("积极 60.0%", text)
        self.assertIn("最近 7 天情绪趋势", text)
        self.assertIn("今日话题 Top5", text)
        self.assertIn("天气", text)
        # 原有内容保留
        self.assertIn("插件事件日报", text)
        self.assertIn("1 条", text)

    def test_daily_report_empty_events_still_has_section(self):
        p = make_plugin()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        p._daily_stats[yesterday] = {
            "msg_count": 10, "pos": 6, "neu": 2, "neg": 2, "words": {},
        }
        text = p._build_daily_report([])
        self.assertIn("没有记录", text)
        self.assertIn("情绪分布", text)

    def test_daily_report_no_data_no_section(self):
        p = make_plugin()
        text = p._build_daily_report([])
        self.assertNotIn("情绪分布", text)
        self.assertIn("没有记录", text)


class TestNewCommands(unittest.TestCase):
    """新命令：/analyze_mood /analyze_topics /analyze_session 权限与输出"""

    def test_analyze_mood_denied(self):
        p = ContextAnalyzerPlugin(None, {"admin_umos": "default:GroupMessage:999"})
        result = asyncio.run(p.analyze_mood(FakeEvent("/analyze_mood")))
        self.assertIn("权限", result[0].text)

    def test_analyze_mood_ok(self):
        p = make_plugin()
        today = datetime.now().strftime("%Y-%m-%d")
        p._daily_stats[today] = {"msg_count": 10, "pos": 6, "neu": 2, "neg": 2, "words": {}}
        result = asyncio.run(p.analyze_mood(FakeEvent("/analyze_mood")))
        text = result[0].text
        self.assertIn("情绪趋势分析", text)
        self.assertIn("积极 60.0%", text)
        self.assertIn("最近 7 天情绪趋势", text)

    def test_analyze_mood_date_arg(self):
        p = make_plugin()
        d = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        p._daily_stats[d] = {"msg_count": 10, "pos": 6, "neu": 2, "neg": 2, "words": {}}
        result = asyncio.run(p.analyze_mood(FakeEvent(f"/analyze_mood {d}")))
        self.assertIn(d, result[0].text)

    def test_analyze_mood_invalid_date_falls_back(self):
        p = make_plugin()
        today = datetime.now().strftime("%Y-%m-%d")
        p._daily_stats[today] = {"msg_count": 10, "pos": 6, "neu": 2, "neg": 2, "words": {}}
        result = asyncio.run(p.analyze_mood(FakeEvent("/analyze_mood 2026-99-99")))
        self.assertIn(today, result[0].text)

    def test_analyze_mood_no_data(self):
        p = make_plugin()
        result = asyncio.run(p.analyze_mood(FakeEvent("/analyze_mood")))
        self.assertIn("没有可用的消息情绪统计", result[0].text)

    def test_analyze_topics_denied(self):
        p = ContextAnalyzerPlugin(None, {"admin_umos": "default:GroupMessage:999"})
        result = asyncio.run(p.analyze_topics(FakeEvent("/analyze_topics")))
        self.assertIn("权限", result[0].text)

    def test_analyze_topics_ok(self):
        p = make_plugin()
        today = datetime.now().strftime("%Y-%m-%d")
        p._daily_stats[today] = {"msg_count": 5, "pos": 0, "neu": 0, "neg": 0, "words": {"天气": 4, "爬山": 3}}
        result = asyncio.run(p.analyze_topics(FakeEvent("/analyze_topics")))
        text = result[0].text
        self.assertIn("话题聚类分析", text)
        self.assertIn("今日话题 Top5", text)
        self.assertIn("天气", text)
        self.assertIn("爬山", text)

    def test_analyze_session_status(self):
        p = make_plugin()
        umo = "default:GroupMessage:123"
        p._track_session(umo, 1000.0, "hi")
        result = asyncio.run(p.analyze_session(FakeEvent("/analyze_session", umo=umo)))
        text = result[0].text
        self.assertIn("会话活跃度分析", text)
        self.assertIn("1 条", text)
        self.assertIn("未触发摘要", text)

    def test_analyze_session_manual_summary(self):
        p = make_plugin()
        umo = "default:GroupMessage:123"
        ts = 1700000000.0
        for i in range(5):
            p._track_session(umo, ts + i * 60, f"今天天气真不错，大家一起去爬山{i}")
        result = asyncio.run(p.analyze_session(FakeEvent("/analyze_session summary", umo=umo)))
        text = result[0].text
        self.assertIn("会话摘要", text)
        self.assertIn("消息要点", text)

    def test_analyze_session_denied(self):
        p = ContextAnalyzerPlugin(None, {"admin_umos": "default:GroupMessage:999"})
        result = asyncio.run(p.analyze_session(FakeEvent("/analyze_session")))
        self.assertIn("权限", result[0].text)

    def test_analyze_session_no_session(self):
        p = make_plugin()
        # 管理员白名单会话内但尚未跟踪到活跃会话
        result = asyncio.run(p.analyze_session(FakeEvent("/analyze_session")))
        self.assertIn("暂未跟踪到活跃会话", result[0].text)


if __name__ == "__main__":
    unittest.main(verbosity=1)