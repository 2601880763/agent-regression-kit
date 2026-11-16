import argparse
import json
from collections import Counter
from pathlib import Path
from datetime import datetime

VALID_STATUSES = {
    "PASS", "FAIL", "ERROR", "INCONCLUSIVE", "SKIPPED"
}


def load_report(path):
    """只接受完整执行完毕的批量报告。"""
    report = json.loads(
        Path(path).read_text(encoding="utf-8-sig")
    )

    if not isinstance(report, dict):
        raise ValueError("报告必须是JSON对象")

    if (
        report.get("schema_version") != 2
        or report.get("mode") != "live_batch"
    ):
        raise ValueError("目前只支持版本2的批量报告")

    if report.get("completed") is not True:
        raise ValueError("报告尚未执行完毕，不能进行完整回归比较")

    suite_id = report.get("suite_id")
    if not isinstance(suite_id, str) or not suite_id.strip():
        raise ValueError("报告缺少有效suite_id")

    results = report.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("报告中的results必须是非空列表")

    if report.get("planned_total") != len(results):
        raise ValueError("实际结果数量与计划数量不一致")

    index = {}

    for result in results:
        if not isinstance(result, dict):
            raise ValueError("每条场景结果必须是JSON对象")

        case_id = result.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("存在缺少case_id的结果，无法可靠对齐")

        if case_id in index:
            raise ValueError(f"case_id重复：{case_id}")

        if result.get("status") not in VALID_STATUSES:
            raise ValueError(f"{case_id}的状态不合法")

        index[case_id] = result

    return report, index


def compare_case(before, after):
    """规则一致、证据充分时，才判断退步或改善。"""
    before_spec = before.get("comparison_spec")
    after_spec = after.get("comparison_spec")

    if not isinstance(before_spec, dict) or not isinstance(
        after_spec, dict
    ):
        return "NOT_COMPARABLE", "缺少评测规则快照"

    if before_spec != after_spec:
        return "NOT_COMPARABLE", "输入或评测设置发生变化"

    old_status = before["status"]
    new_status = after["status"]

    if old_status not in {"PASS", "FAIL"} or new_status not in {
        "PASS", "FAIL"
    }:
        return "UNRESOLVED", "存在执行异常、证据不足或跳过的结果"

    if old_status == "PASS" and new_status == "FAIL":
        return "REGRESSION", "原来通过，本次失败"

    if old_status == "FAIL" and new_status == "PASS":
        return "IMPROVEMENT", "原来失败，本次通过"

    if new_status == "PASS":
        return "STABLE_PASS", "两次均通过"

    return "STABLE_FAIL", "两次均失败"


def compare_reports(baseline_path, current_path):
    baseline, old_cases = load_report(baseline_path)
    current, new_cases = load_report(current_path)

    if baseline["suite_id"] != current["suite_id"]:
        raise ValueError("两份报告的suite_id不同")

    changes = []

    for case_id in sorted(old_cases.keys() | new_cases.keys()):
        before = old_cases.get(case_id)
        after = new_cases.get(case_id)

        if before is None:
            change, reason = "ADDED", "本次新增场景"
        elif after is None:
            change, reason = "REMOVED", "本次未包含该场景"
        else:
            change, reason = compare_case(before, after)

        changes.append({
            "case_id": case_id,
            "before": before["status"] if before else None,
            "after": after["status"] if after else None,
            "change": change,
            "reason": reason,
        })

    return {
        "schema_version": 1,
        "mode": "regression_comparison",
        "suite_id": baseline["suite_id"],
        "baseline_file": str(baseline_path),
        "current_file": str(current_path),
        "baseline_run_id": baseline.get("run_id"),
        "current_run_id": current.get("run_id"),
        "summary": dict(Counter(
            item["change"] for item in changes
        )),
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="比较两次批量Agent评测报告"
    )
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        baseline = Path(args.baseline).resolve()
        current = Path(args.current).resolve()
        output = Path(args.output).resolve()

        if output in {baseline, current}:
            raise ValueError("输出路径不能覆盖输入报告")

        comparison = compare_reports(baseline, current)

        # 生成时间标签，例如：20241116_143052
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 在原文件名基础上加时间标签
        # 假设 output 原来是 Path("xxx/comparison.json")
        stem = output.stem  # "comparison"
        suffix = output.suffix  # ".json"
        new_output = output.with_name(f"{stem}_{timestamp}{suffix}")

        new_output.parent.mkdir(parents=True, exist_ok=True)
        new_output.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    except (OSError, ValueError) as error:
        print("比较失败：", error)
        return 2

    for item in comparison["changes"]:
        print(
            f"{item['case_id']}："
            f"{item['before']} → {item['after']}，"
            f"{item['change']}，{item['reason']}"
        )

    print("汇总：", comparison["summary"])
    print("比较报告：", output)

    changes = {item["change"] for item in comparison["changes"]}

    if "REGRESSION" in changes:
        return 1

    if changes & {
        "UNRESOLVED", "NOT_COMPARABLE", "ADDED", "REMOVED"
    }:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())