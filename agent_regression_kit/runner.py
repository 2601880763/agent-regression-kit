from datetime import datetime, timezone
from uuid import uuid4

from .checks import check_tool_used


def summarize_status(checks):
    """把多个检查结果汇总为一个场景结果。"""
    statuses = [check["status"] for check in checks]

    for status in ["ERROR", "FAIL", "INCONCLUSIVE"]:
        if status in statuses:
            return status

    return "PASS"


def run_suite(suite, observations):
    """使用模拟记录执行检查，不调用真实模型。"""
    results = []

    for case in suite["cases"]:
        if len(case["messages"]) != 1:
            results.append({
                "case_id": case["id"],
                "status": "ERROR",
                "checks": [],
                "reason": "当前模拟运行器只支持单轮场景",
            })
            continue

        observation = observations.get(case["id"])

        if observation is None:
            tools_called = None
        elif not isinstance(observation, dict):
            results.append({
                "case_id": case["id"],
                "status": "ERROR",
                "checks": [],
                "reason": "模拟记录必须是 JSON 对象",
            })
            continue
        else:
            tools_called = observation.get("tools_called")

        check_results = []

        for check in case["checks"]:
            result = check_tool_used(
                check["expected"]["name"],
                tools_called,
            )
            check_results.append(result)

        results.append({
            "case_id": case["id"],
            "status": summarize_status(check_results),
            "checks": check_results,
        })

    counts = {
        status: 0
        for status in [
            "PASS",
            "FAIL",
            "ERROR",
            "INCONCLUSIVE",
            "SKIPPED",
        ]
    }

    for result in results:
        counts[result["status"]] += 1

    return {
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "mock",
        "suite": suite["name"],
        "evaluation_executed": True,
        "agent_invoked": False,
        "summary": {
            "total": len(results),
            **counts,
        },
        "results": results,
    }