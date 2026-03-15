"""Tests for live_agent — voice pipeline unit tests (no credentials needed)."""

import asyncio
import unittest
from unittest.mock import patch, MagicMock

from schedule_analyst.live_agent import (
    handle_tool_call,
    TOOL_FUNCTIONS,
    TOOL_DECLARATIONS,
    SYSTEM_INSTRUCTION,
    BRAIN_RULES,
)


class TestToolDeclarations(unittest.TestCase):
    """Verify tool declarations match the actual tool functions."""

    def test_all_tools_declared(self):
        """Every function in TOOL_FUNCTIONS has a declaration."""
        declared_names = {
            fd.name for fd in TOOL_DECLARATIONS.function_declarations
        }
        self.assertEqual(declared_names, set(TOOL_FUNCTIONS.keys()))

    def test_three_tools_registered(self):
        self.assertEqual(len(TOOL_FUNCTIONS), 3)
        self.assertIn("get_calendar_events", TOOL_FUNCTIONS)
        self.assertIn("find_conflicts", TOOL_FUNCTIONS)
        self.assertIn("suggest_optimizations", TOOL_FUNCTIONS)


class TestSystemInstruction(unittest.TestCase):
    """Verify system instruction quality."""

    def test_instruction_not_empty(self):
        self.assertGreater(len(SYSTEM_INSTRUCTION), 100)

    def test_brain_rules_loaded(self):
        """Brain rules should be loaded from the brain file."""
        self.assertGreater(len(BRAIN_RULES), 0)

    def test_brain_rules_in_instruction(self):
        """Brain rules should be embedded in the system instruction."""
        # Brain file uses "protected" (lowercase) in rule text
        self.assertIn("protected", SYSTEM_INSTRUCTION.lower())

    def test_no_raw_json_instruction(self):
        """System instruction should tell agent not to output JSON."""
        self.assertIn("Never output raw JSON", SYSTEM_INSTRUCTION)

    def test_voice_tone_instruction(self):
        """System instruction should set conversational tone."""
        self.assertIn("conversational", SYSTEM_INSTRUCTION.lower())


class TestHandleToolCall(unittest.TestCase):
    """Test tool call handler — patches TOOL_FUNCTIONS dict directly."""

    def _make_fc(self, name, args=None):
        fc = MagicMock()
        fc.name = name
        fc.args = args
        return fc

    def test_unknown_tool_returns_error(self):
        fc = self._make_fc("nonexistent_tool")
        result = asyncio.run(handle_tool_call(fc))
        self.assertIn("error", result)
        self.assertIn("Unknown tool", result["error"])

    def test_get_calendar_events_called(self):
        mock_fn = MagicMock(return_value={"events": [], "count": 0})
        with patch.dict(TOOL_FUNCTIONS, {"get_calendar_events": mock_fn}):
            fc = self._make_fc("get_calendar_events", {"time_range": "today"})
            result = asyncio.run(handle_tool_call(fc))
            mock_fn.assert_called_once_with(time_range="today")
            self.assertEqual(result["count"], 0)

    def test_find_conflicts_called(self):
        mock_fn = MagicMock(return_value={"conflicts": [], "conflict_count": 0})
        with patch.dict(TOOL_FUNCTIONS, {"find_conflicts": mock_fn}):
            fc = self._make_fc("find_conflicts", {"time_range": "this week"})
            result = asyncio.run(handle_tool_call(fc))
            mock_fn.assert_called_once_with(time_range="this week")

    def test_suggest_optimizations_called(self):
        mock_fn = MagicMock(return_value={"suggestions": [], "suggestion_count": 0})
        with patch.dict(TOOL_FUNCTIONS, {"suggest_optimizations": mock_fn}):
            fc = self._make_fc("suggest_optimizations", {"focus": "deep work"})
            result = asyncio.run(handle_tool_call(fc))
            mock_fn.assert_called_once_with(focus="deep work")

    def test_tool_exception_returns_error(self):
        mock_fn = MagicMock(side_effect=RuntimeError("Calendar API down"))
        with patch.dict(TOOL_FUNCTIONS, {"get_calendar_events": mock_fn}):
            fc = self._make_fc("get_calendar_events", {"time_range": "today"})
            result = asyncio.run(handle_tool_call(fc))
            self.assertIn("error", result)
            self.assertIn("Calendar API down", result["error"])

    def test_empty_args_handled(self):
        """Tool call with no args should not crash."""
        mock_fn = MagicMock(return_value={"events": [], "count": 0})
        with patch.dict(TOOL_FUNCTIONS, {"get_calendar_events": mock_fn}):
            fc = self._make_fc("get_calendar_events", None)
            result = asyncio.run(handle_tool_call(fc))
            mock_fn.assert_called_once_with()


class TestAudioConstants(unittest.TestCase):
    """Verify audio configuration matches Live API requirements."""

    def test_send_sample_rate(self):
        from schedule_analyst.live_agent import SEND_SAMPLE_RATE
        self.assertEqual(SEND_SAMPLE_RATE, 16000)

    def test_receive_sample_rate(self):
        from schedule_analyst.live_agent import RECEIVE_SAMPLE_RATE
        self.assertEqual(RECEIVE_SAMPLE_RATE, 24000)

    def test_mono_channel(self):
        from schedule_analyst.live_agent import CHANNELS
        self.assertEqual(CHANNELS, 1)


class TestCheckApiKey(unittest.TestCase):
    """Test API key validation."""

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key-123"})
    def test_returns_key_when_set(self):
        from schedule_analyst.live_agent import _check_api_key
        key = _check_api_key()
        self.assertEqual(key, "test-key-123")

    @patch.dict("os.environ", {}, clear=True)
    def test_exits_when_missing(self):
        from schedule_analyst.live_agent import _check_api_key
        with self.assertRaises(SystemExit):
            _check_api_key()


class TestMainEntryPoint(unittest.TestCase):
    """Test CLI mode selection."""

    def test_modes_mapping(self):
        """All three modes should be available."""
        from schedule_analyst.live_agent import run_voice_agent, run_text_agent, run_demo_agent
        # Just verify they're callable
        self.assertTrue(callable(run_voice_agent))
        self.assertTrue(callable(run_text_agent))
        self.assertTrue(callable(run_demo_agent))


if __name__ == "__main__":
    unittest.main()
