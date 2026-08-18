# -*- coding: utf-8 -*-
"""context_analyzer 插件单元测试：导出、日报/周报、事件聚合"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, r"D:\astrbot\data\plugins")

from astrbot_plugin_context_analyzer.main import ContextAnalyzerPlugin  # noqa: E402


class FakeSession:
    def __init__(self, umo="default:GroupMessage:123"):
        self.umo = umo

    def __str__(self):
        return self.umo


class FakeEvent:
    """最小事件替身：仅支持 session 与 send"""
    def __init__(self, message_str="", umo="default:GroupMessage:123", admin_umos=""):
        self.session = FakeSession(umo)
        self.message_str = message_str
        self.sent = []

    def chain_result(self, chain):
        return chain

    async def send(self, chain):
        self.sent.append(chain)
        return None


def make_plugin(admin_umos="default:GroupMessage:123"):
    return ContextAnalyzerPlugin(None, {"admin_umos": admin_umos})


class TestAggEvents(unittest.TestCase):
    def setUp(self):
        base = datetime.now() - timedelta(days=1)
        self.events = [
            {"time": base.replace(hour=8).isoformat(), "type": "loaded", "plugin": "p1", "details": {}},
            {"time": base.replace(hour=9).isoformat(), "type": "error", "plugin": "p2",
             "details": {"error": "boom"}},
            {"time": base.replace(hour=10).isoformat(), "type": "unloaded", "plugin": "p1", "details": {}},
            {"time": (datetime.now() - timedelta(days=3)).isoformat(), "type": "loaded", "plugin": "p3", "details": {}},
        ]

    def test_agg_counts_and_filters(self):
        total, by_type, errors = ContextAnalyzerPlugin._agg_events(self.events, f"{datetime.now().strftime('%Y-%m-%d')}T00:00:00")
        self.assertEqual(total, 0)

    def test_agg_yesterday_window(self):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        total, by_type, errors = ContextAnalyzerPlugin._agg_events(self.events, f"{yesterday}T00:00:00")
        self.assertEqual(total, 3)
        self.assertEqual(by_type.get("loaded"), 1)
        self.assertEqual(by_type.get("error"), 1)
        self.assertEqual(by_type.get("unloaded"), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["plugin"], "p2")


class TestReports(unittest.TestCase):
    def _events(self):
        base = datetime.now() - timedelta(days=1)
        return [
            {"time": base.replace(hour=8).isoformat(), "type": "loaded", "plugin": "p1", "details": {}},
            {"time": base.replace(hour=9).isoformat(), "type": "error", "plugin": "p2",
             "details": {"error": "boom: long error message here"}},
            {"time": base.replace(hour=10).isoformat(), "type": "unloaded", "plugin": "p1", "details": {}},
        ]

    def test_daily_empty(self):
        text = make_plugin()._build_daily_report([])
        self.assertIn("日报", text)
        self.assertIn("没有记录", text)

    def test_daily_content(self):
        text = make_plugin()._build_daily_report(self._events())
        self.assertIn("3 条", text)
        self.assertIn("插件加载: 1 条", text)
        self.assertIn("运行错误: 1 条", text)
        self.assertIn("p2", text)
        self.assertIn("boom", text)

    def test_weekly_content(self):
        text = make_plugin()._build_weekly_report(self._events())
        self.assertIn("7 天", text)
        self.assertIn("3 条", text)

    def test_error_detail_truncated(self):
        text = make_plugin()._build_daily_report(self._events())
        self.assertLessEqual(len("boom: long error message here"), 40)


class TestExport(unittest.TestCase):
    def test_build_export_data(self):
        p = make_plugin()
        history = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]
        data = p._build_export_data(history, "会话上下文")
        self.assertEqual(data["message_count"], 2)
        self.assertEqual(data["source"], "会话上下文")
        self.assertEqual(len(data["messages"]), 2)

    def test_write_json(self):
        p = make_plugin()
        with tempfile.TemporaryDirectory() as tmp:
            p.data_dir = tmp
            path = p._write_export_file(p._build_export_data(
                [{"role": "user", "text": "hi"}], "src"), "json")
            self.assertTrue(path.endswith(".json"))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["messages"][0]["text"], "hi")

    def test_write_csv(self):
        p = make_plugin()
        with tempfile.TemporaryDirectory() as tmp:
            p.data_dir = tmp
            path = p._write_export_file(p._build_export_data(
                [{"role": "user", "text": "你好\n世界"}, {"role": "assistant", "text": "ok"}], "src"), "csv")
            self.assertTrue(path.endswith(".csv"))
            with open(path, encoding="utf-8-sig") as f:
                rows = [line.strip().split(",") for line in f if line.strip()]
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0][0], "role")

    def test_export_denied(self):
        p = ContextAnalyzerPlugin(None, {"admin_umos": "default:GroupMessage:999"})
        event = FakeEvent("context export")
        result = p._export_history(event)
        # 非管理员：直接返回拒绝文本（同步返回 coroutine 需先运行）
        import asyncio
        result = asyncio.run(p._export_history(event))
        self.assertIn("权限", result[0].text)

    def test_export_sends_file(self):
        import asyncio
        p = make_plugin()
        async def fake_history(event):  # noqa: ARG001
            return ([{"role": "user", "text": "a"}, {"role": "assistant", "text": "b"}], "会话上下文")
        p._get_session_history = fake_history
        event = FakeEvent("context export")
        asyncio.run(p._export_history(event))
        self.assertEqual(len(event.sent), 1)
        chain = event.sent[0]
        comps = getattr(chain, "chain", [chain])
        self.assertGreaterEqual(len(comps), 2)
        self.assertTrue(any(getattr(c, "name", None) for c in comps))

    def test_export_limit_keeps_recent(self):
        import asyncio
        p = make_plugin()
        async def fake_history(event):  # noqa: ARG001
            return ([{"role": "user", "text": f"msg{i}"} for i in range(10)], "会话上下文")
        p._get_session_history = fake_history
        event = FakeEvent("context export json 3")
        asyncio.run(p._export_history(event))
        chain = event.sent[0]
        plain = next(c for c in chain.chain if hasattr(c, "text"))
        self.assertIn("3/10", plain.text)
        self.assertIn("最近 3 条", plain.text)

    def test_export_limit_zero_means_all(self):
        import asyncio
        p = make_plugin()
        async def fake_history(event):  # noqa: ARG001
            return ([{"role": "user", "text": f"msg{i}"} for i in range(5)], "会话上下文")
        p._get_session_history = fake_history
        event = FakeEvent("context export csv")
        asyncio.run(p._export_history(event))
        chain = event.sent[0]
        plain = next(c for c in chain.chain if hasattr(c, "text"))
        self.assertIn("5/5", plain.text)
        self.assertNotIn("最近", plain.text)

    def test_export_parses_csv_and_limit(self):
        import asyncio
        p = make_plugin()
        async def fake_history(event):  # noqa: ARG001
            return ([{"role": "user", "text": f"msg{i}"} for i in range(6)], "会话上下文")
        p._get_session_history = fake_history
        event = FakeEvent("context export csv 2")
        asyncio.run(p._export_history(event))
        chain = event.sent[0]
        comps = getattr(chain, "chain", [chain])
        file_comp = next(c for c in comps if getattr(c, "name", None))
        self.assertTrue(file_comp.name.endswith(".csv"))
        plain = next(c for c in comps if hasattr(c, "text"))
        self.assertIn("2/6", plain.text)


class TestReportTargets(unittest.TestCase):
    def test_parse_list(self):
        p = make_plugin()
        p.config["report_umo"] = "default:GroupMessage:1, default:GroupMessage:2"
        self.assertEqual(p._report_targets(), ["default:GroupMessage:1", "default:GroupMessage:2"])

    def test_empty(self):
        self.assertEqual(make_plugin()._report_targets(), [])


class TestManual(unittest.TestCase):
    def test_daily_denied(self):
        import asyncio
        p = ContextAnalyzerPlugin(None, {"admin_umos": ""})
        result = asyncio.run(p._manual_daily(FakeEvent("context daily")))
        self.assertIn("admin_umos", result[0].text)

    def test_daily_allowed(self):
        import asyncio
        p = make_plugin()
        p._plugin_events = [{
            "time": (datetime.now() - timedelta(days=1)).replace(hour=8).isoformat(),
            "type": "loaded", "plugin": "p1", "details": {},
        }]
        result = asyncio.run(p._manual_daily(FakeEvent("context daily")))
        self.assertIn("日报", result[0].text)
        self.assertIn("1 条", result[0].text)


class FakeStar:
    def __init__(self, name, version="1.0.0", activated=True, desc="d"):
        self.name = name
        self.version = version
        self.activated = activated
        self.desc = desc


class FakeContext:
    def __init__(self, stars):
        self._stars = stars

    def get_all_stars(self):
        return self._stars


class TestCommands(unittest.TestCase):
    """命令处理器：/status /plugins /reset /log 的权限与行为"""

    def _plugin(self, stars=None, admin_umos="default:GroupMessage:123"):
        import tempfile
        p = ContextAnalyzerPlugin(FakeContext(stars or []), {"admin_umos": admin_umos})
        # 数据落盘重定向到临时目录，避免污染真实插件数据
        tmp = tempfile.mkdtemp(prefix="ctx_cmd_test_")
        p.data_dir = tmp
        return p

    def test_status_denied_for_non_admin(self):
        import asyncio
        p = self._plugin()
        ev = FakeEvent("/status", umo="default:GroupMessage:999")
        result = asyncio.run(p.analyze_status(ev))
        self.assertIn("没有执行此命令的权限", result[0].text)

    def test_status_disabled_by_config(self):
        import asyncio
        p = self._plugin()
        p.config["enable_system_status"] = False
        ev = FakeEvent("/status", umo="default:GroupMessage:123")
        result = asyncio.run(p.analyze_status(ev))
        self.assertIn("enable_system_status=false", result[0].text)

    def test_reset_all_clears(self):
        import asyncio
        p = self._plugin()
        p._plugin_events = [{"time": "t", "type": "loaded", "plugin": "p1", "details": {}}]
        p._plugin_snapshots = {"p1": {"version": "1.0.0"}}
        p._session_cache = {"k": "v"}
        result = asyncio.run(p.reset_plugin(FakeEvent("reset")))
        self.assertIn("已重置", result[0].text)
        self.assertEqual(p._plugin_events, [])
        self.assertEqual(p._plugin_snapshots, {})
        self.assertEqual(p._session_cache, {})

    def test_reset_single_plugin(self):
        import asyncio
        p = self._plugin()
        p._plugin_events = [
            {"time": "t", "type": "loaded", "plugin": "p1", "details": {}},
            {"time": "t", "type": "error", "plugin": "p2", "details": {}},
        ]
        p._plugin_snapshots = {"p1": {}, "p2": {}}
        result = asyncio.run(p.reset_plugin(FakeEvent("reset p1")))
        self.assertIn("已重置插件: p1", result[0].text)
        self.assertEqual(len(p._plugin_events), 1)
        self.assertEqual(p._plugin_events[0]["plugin"], "p2")
        self.assertNotIn("p1", p._plugin_snapshots)

    def test_log_shows_and_filters(self):
        import asyncio
        p = self._plugin()
        p._plugin_events = [
            {"time": "2026-08-01T08:30:00", "type": "loaded", "plugin": "p1", "details": {}},
            {"time": "2026-08-01T09:00:00", "type": "error", "plugin": "p2", "details": {}},
        ]
        result = asyncio.run(p.show_log(FakeEvent("log")))
        self.assertIn("共 2 条", result[0].text)
        self.assertIn("p1", result[0].text)
        result2 = asyncio.run(p.show_log(FakeEvent("log p1")))
        self.assertIn("共 1 条", result2[0].text)
        self.assertNotIn("p2", result2[0].text)

    def test_log_tolerates_bad_entries(self):
        # 结构校验修复：坏条目（缺 type/time/plugin）不导致 /log 崩溃
        import asyncio
        p = self._plugin()
        p._plugin_events = [{"foo": 1}, {"time": "2026-08-01T08:30:00", "type": "loaded", "plugin": "p1", "details": {}}]
        result = asyncio.run(p.show_log(FakeEvent("log")))
        self.assertIn("共 2 条", result[0].text)

    def test_log_empty(self):
        import asyncio
        p = self._plugin()
        p._plugin_events = []
        result = asyncio.run(p.show_log(FakeEvent("log")))
        self.assertIn("没有事件日志记录", result[0].text)

    def test_plugins_reports_changes(self):
        import asyncio
        p = self._plugin(stars=[FakeStar("p1", "1.0.0", True), FakeStar("p2", "2.0.0", False)])
        p._plugin_snapshots = {}
        result = asyncio.run(p.analyze_plugins(FakeEvent("/plugins")))
        text = result[0].text
        self.assertIn("插件总数: 2", text)
        self.assertIn("新增", text)
        # 快照已更新，二次调用不再报"新增"
        result2 = asyncio.run(p.analyze_plugins(FakeEvent("/plugins")))
        self.assertNotIn("🆕 新增", result2[0].text)


if __name__ == "__main__":
    unittest.main(verbosity=1)