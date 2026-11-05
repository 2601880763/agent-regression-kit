import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MockCliTests(unittest.TestCase):
    def test_report_and_exit_code_match_result(self):
        scenarios = [
            (["search_shops"], "PASS", 0),
            (["get_shop_detail"], "FAIL", 1),
            (None, "INCONCLUSIVE", 2),
        ]

        for tools_called, expected_status, expected_code in scenarios:
            with self.subTest(expected_status=expected_status):
                with tempfile.TemporaryDirectory() as directory:
                    directory = Path(directory)
                    observations_path = directory / "observations.json"
                    report_path = directory / "reports" / "result.json"

                    observation = {}
                    if tools_called is not None:
                        observation["tools_called"] = tools_called

                    observations_path.write_text(
                        json.dumps({"search_shops": observation}),
                        encoding="utf-8",
                    )

                    process = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "agent_regression_kit",
                            "run-mock",
                            "examples/starter_suite.json",
                            "--observations",
                            str(observations_path),
                            "--output",
                            str(report_path),
                        ],
                        cwd=ROOT,
                        capture_output=True,
                    )

                    self.assertEqual(
                        expected_code,
                        process.returncode,
                        msg=repr(process.stderr),
                    )
                    self.assertTrue(report_path.is_file())

                    report = json.loads(
                        report_path.read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        expected_status,
                        report["results"][0]["status"],
                    )


if __name__ == "__main__":
    unittest.main()