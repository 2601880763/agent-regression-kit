import copy
import unittest

from agent_regression_kit.__main__ import validate_case


class CaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "search_shops",
            "description": "搜索门店时调用搜索工具",
            "messages": ["帮我找几家火锅店"],
            "checks": [
                {
                    "kind": "tool_used",
                    "expected": {"name": "search_shops"},
                }
            ],
        }

    def test_valid_case(self):
        seen_ids = set()

        validate_case(self.case, seen_ids, 1)

        self.assertIn("search_shops", seen_ids)

    def test_duplicate_id_is_rejected(self):
        seen_ids = {"search_shops"}

        with self.assertRaisesRegex(ValueError, "场景 id 重复"):
            validate_case(self.case, seen_ids, 2)

    def test_invalid_fields_are_rejected(self):
        invalid_cases = [
            ("id", ""),
            ("id", " search_shops "),
            ("description", ""),
            ("messages", []),
            ("messages", [" "]),
            ("messages", [123]),
            ("checks", []),
            ("checks", [{"kind": "unknown", "expected": {}}]),
            ("checks", [{"kind": "tool_used", "expected": {}}]),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field, value=value):
                case = copy.deepcopy(self.case)
                case[field] = value

                with self.assertRaises(ValueError):
                    validate_case(case, set(), 1)


if __name__ == "__main__":
    unittest.main()