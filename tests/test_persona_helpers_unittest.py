"""Run with: python -m unittest tests.test_persona_helpers_unittest -v"""
from __future__ import annotations

import unittest

from api.core import (
    ACTIVE_PERSONA_METADATA_KEY,
    ChatMessage,
    _detect_explicit_persona_request,
    _detect_ongoing_activity,
    _infer_persona_from_history,
    _is_activity_continuation,
    extract_math_expressions,
    format_math_tool_context,
    looks_like_web_search_request,
    resolve_manual_persona,
    run_math_tool_for_message,
)


class PersonaHelperTests(unittest.TestCase):
    def test_explicit_triggers(self):
        self.assertEqual(_detect_explicit_persona_request("باش معلم"), "teacher")
        self.assertEqual(_detect_explicit_persona_request("قصه بگو"), "storyteller")
        self.assertEqual(
            _detect_explicit_persona_request(
                "باش معلم، نه باش داستان‌گو، در واقع بازی کنیم"
            ),
            "gamer",
        )
        self.assertIsNone(_detect_explicit_persona_request("سلام!"))

    def test_manual_sources(self):
        self.assertEqual(resolve_manual_persona(user_persona="teacher"), "teacher")
        self.assertEqual(
            resolve_manual_persona(body={"metadata": {"yarkids_persona": "gamer"}}),
            "gamer",
        )
        self.assertIsNone(resolve_manual_persona(user_persona="auto"))

    def test_word_chain_keeps_gamer(self):
        messages = [
            ChatMessage(role="assistant", content="بریم بازی کلمات! نوبت تو، کلمه بگو."),
            ChatMessage(role="user", content="داستان"),
        ]
        self.assertIsNotNone(_detect_ongoing_activity(messages, "gamer"))
        self.assertTrue(_is_activity_continuation("داستان", "gamer"))
        self.assertEqual(_infer_persona_from_history(messages), "gamer")

    def test_continuations(self):
        self.assertTrue(_is_activity_continuation("سوال بعد", "homework"))
        self.assertTrue(_is_activity_continuation("ادامه بده", "storyteller"))
        self.assertTrue(_is_activity_continuation("مثال دیگر", "teacher"))
        self.assertTrue(_is_activity_continuation("ایده دیگر", "creative"))

    def test_math(self):
        self.assertEqual(extract_math_expressions("۲ به توان ۱۰"), ["2**10"])
        self.assertEqual(extract_math_expressions("جذر ۱۴۴"), ["sqrt(144)"])
        usages = run_math_tool_for_message("۱۰ تقسیم بر ۰", persona="teacher")
        self.assertEqual(len(usages), 1)
        self.assertFalse(usages[0].ok)
        self.assertIn("تقسیم بر صفر نمیشه", usages[0].result)
        self.assertIn("تقسیم بر صفر نمیشه", format_math_tool_context(usages) or "")
        self.assertEqual(run_math_tool_for_message("۱۲ + ۱۷", persona="gamer"), [])

    def test_web_and_meta(self):
        self.assertTrue(looks_like_web_search_request("ماینکرفت چطور الماس پیدا کنم؟"))
        self.assertFalse(looks_like_web_search_request("داستان یه ربات فضایی بگو"))
        self.assertEqual(ACTIVE_PERSONA_METADATA_KEY, "yarkids_active_persona")


if __name__ == "__main__":
    unittest.main()
