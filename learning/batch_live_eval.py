import argparse
import getpass
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from live_agent_eval import run_case, save_report


def main():
    parser = argparse.ArgumentParser(
        description="批量执行真实Agent评测"
    )
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    suite_path = Path(args.config)
    if not suite_path.is_absolute():
        suite_path = project_root / suite_path

    try:
        suite = json.loads(
            suite_path.read_text(encoding="utf-8-sig")
        )

        if not isinstance(suite, dict):
            raise ValueError("套件配置必须是JSON对象")

        schema_version = suite.get("schema_version")
        if type(schema_version) is not int or schema_version != 1:
            raise ValueError("目前只支持schema_version为整数1")

        suite_id = suite.get("suite_id")
        if not isinstance(suite_id, str) or not suite_id.strip():
            raise ValueError("suite_id必须是非空字符串")

        files = suite.get("cases")
        if not isinstance(files, list) or not files:
            raise ValueError("cases必须是非空列表")

        for file in files:
            if not isinstance(file, str) or not file.strip():
                raise ValueError("每个场景文件路径必须是非空字符串")

        case_paths = [
            (suite_path.parent / file).resolve()
            for file in files
        ]

        if len(set(case_paths)) != len(case_paths):
            raise ValueError("套件中存在重复的场景文件")

        interval = suite.get("interval_seconds", 30)
        if (
            type(interval) not in [int, float]
            or not math.isfinite(interval)
            or interval < 0
        ):
            raise ValueError("interval_seconds必须是有限的非负数字")

    except (OSError, ValueError) as error:
        print("套件配置错误：", error)
        return 2

    token = getpass.getpass("请输入点评登录Token：").strip()
    if not token:
        print("登录Token不能为空")
        return 2

    summary = {
        "total": 0,
        "PASS": 0,
        "FAIL": 0,
        "ERROR": 0,
        "INCONCLUSIVE": 0,
        "SKIPPED": 0,
    }

    batch_report = {
        "schema_version": 2,
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live_batch",
        "suite_id": suite_id,
        "planned_total": len(case_paths),
        "completed": False,
        "summary": summary,
        "results": [],
    }

    for position, case_path in enumerate(case_paths, start=1):
        print(f"\n正在执行 {position}/{len(case_paths)}：{case_path.name}")

        report = run_case(case_path, token=token)

        batch_report["results"].append(report)
        summary["total"] += 1
        summary[report["status"]] += 1

        batch_report["completed"] = position == len(case_paths)

        try:
            output = save_report(batch_report)
        except OSError as error:
            print("汇总报告保存失败：", error)
            return 2

        print("场景状态：", report["status"])
        print("汇总报告：", output)

        if position < len(case_paths):
            time.sleep(interval)

    print("\n汇总结果：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if summary["ERROR"] or summary["INCONCLUSIVE"]:
        return 2
    if summary["FAIL"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())