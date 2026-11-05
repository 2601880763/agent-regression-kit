import unittest

from agent_regression_kit.runner import run_suite


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.suite = {
            "schema_version": 1,
            "name": "运行器测试",
            "cases": [
                {
                    "id": "search",
                    "description": "调用搜索工具",
                    "messages": ["帮我找火锅店"],
                    "checks": [
                        {
                            "kind": "tool_used",
                            "expected": {"name": "search_shops"},
                        }
                    ],
                }
            ],
        }

    def test_observations_produce_correct_status(self):
        scenarios = [
            (
                {"search": {"tools_called": ["search_shops"]}},
                "PASS",
            ),
            (
                {"search": {"tools_called": ["get_shop_detail"]}},
                "FAIL",
            ),
            (
                {"search": {"tools_called": []}},
                "FAIL",
            ),
            (
                {},
                "INCONCLUSIVE",
            ),
            (
                {"search": {}},
                "INCONCLUSIVE",
            ),
            (
                {"search": "格式错误的记录"},
                "ERROR",
            ),
        ]

        for observations, expected_status in scenarios:
            with self.subTest(observations=observations):
                report = run_suite(self.suite, observations)

                self.assertEqual(
                    expected_status,
                    report["results"][0]["status"],
                )
                self.assertEqual(1, report["summary"][expected_status])
                self.assertEqual(1, report["summary"]["total"])

                counted = sum(
                    report["summary"][status]
                    for status in [
                        "PASS",
                        "FAIL",
                        "ERROR",
                        "INCONCLUSIVE",
                        "SKIPPED",
                    ]
                )
                self.assertEqual(report["summary"]["total"], counted)

    def test_mock_report_does_not_claim_real_agent_execution(self):
        report = run_suite(
            self.suite,
            {"search": {"tools_called": ["search_shops"]}},
        )

        self.assertEqual("mock", report["mode"])
        self.assertTrue(report["evaluation_executed"])
        self.assertFalse(report["agent_invoked"])
        self.assertTrue(report["run_id"])
        self.assertTrue(report["created_at"])

    def test_multiple_checks_are_aggregated(self):
        self.suite["cases"][0]["checks"].append({
            "kind": "tool_used",
            "expected": {"name": "get_shop_detail"},
        })

        report = run_suite(
            self.suite,
            {"search": {"tools_called": ["search_shops"]}},
        )

        self.assertEqual(
            ["PASS", "FAIL"],
            [
                check["status"]
                for check in report["results"][0]["checks"]
            ],
        )
        self.assertEqual("FAIL", report["results"][0]["status"])

    def test_unsupported_multi_turn_is_not_reported_as_pass(self):
        self.suite["cases"][0]["messages"].append("第二家的详情")

        report = run_suite(
            self.suite,
            {"search": {"tools_called": ["search_shops"]}},
        )

        self.assertEqual("ERROR", report["results"][0]["status"])
        self.assertEqual(0, report["summary"]["PASS"])


if __name__ == "__main__":
    unittest.main()