import unittest

from agent_regression_kit.checks import check_tool_used


class ToolUsedTests(unittest.TestCase):
    def test_matching_tool_passes(self):
        result = check_tool_used(
            "search_shops",
            ["search_shops", "get_shop_detail"],
        )

        self.assertEqual("PASS", result["status"])

    def test_wrong_tool_fails(self):
        result = check_tool_used(
            "search_shops",
            ["get_shop_detail"],
        )

        self.assertEqual("FAIL", result["status"])

    def test_observed_empty_list_fails(self):
        result = check_tool_used("search_shops", [])

        self.assertEqual("FAIL", result["status"])

    def test_missing_record_is_inconclusive(self):
        result = check_tool_used("search_shops", None)

        self.assertEqual("INCONCLUSIVE", result["status"])

    def test_malformed_record_is_error(self):
        for record in ["search_shops", [123], [""]]:
            with self.subTest(record=record):
                result = check_tool_used("search_shops", record)

                self.assertEqual("ERROR", result["status"])

    def test_invalid_expected_name_is_rejected(self):
        with self.assertRaises(ValueError):
            check_tool_used("", ["search_shops"])


if __name__ == "__main__":
    unittest.main()