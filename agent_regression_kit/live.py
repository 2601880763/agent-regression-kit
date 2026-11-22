import getpass
import json
from uuid import uuid4

from deepeval.metrics import ToolCorrectnessMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import argparse
from urllib.parse import urlparse

from .adapters import AgentCallError, execute_agent


class NoJudgeModel(DeepEvalBaseLLM):
    """沿用上一轮的保护对象，不调用评审模型。"""

    def load_model(self):
        return self

    def generate(self, *args, **kwargs):
        raise RuntimeError("本轮不应调用评审模型")

    async def a_generate(self, *args, **kwargs):
        raise RuntimeError("本轮不应调用评审模型")

    def get_model_name(self):
        return "no-judge-model"


class EvidenceUnavailable(ValueError):
    """请求完成，但没有取得足够的评测证据。"""

def save_report(report):
    project_root = Path(__file__).resolve().parents[1]
    output = (
            Path.cwd()
            / "reports"
            / f"live-{report['run_id']}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary = output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)

    return output

def load_live_config(path):
    content = Path(path).read_text(encoding="utf-8-sig")
    config = json.loads(content)

    if not isinstance(config, dict):
        raise ValueError("配置最外层必须是JSON对象")

    schema_version = config.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("目前只支持schema_version为整数1")

    for field in ["case_id", "endpoint", "input"]:
        value = config.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field}必须是非空字符串")

    endpoint = urlparse(config["endpoint"])
    if endpoint.scheme not in ["http", "https"] or not endpoint.hostname:
        raise ValueError("endpoint必须是有效的HTTP或HTTPS地址")

    expected_tools = config.get("expected_tools")
    if not isinstance(expected_tools, list) or not expected_tools:
        raise ValueError("expected_tools必须是非空列表")

    for tool in expected_tools:
        if not isinstance(tool, dict):
            raise ValueError("每个预期工具必须是JSON对象")

        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("预期工具名必须是非空字符串")

        if not isinstance(tool.get("input_parameters"), dict):
            raise ValueError("input_parameters必须是JSON对象")

    business_checks = config.get("business_checks", [])
    if not isinstance(business_checks, list):
        raise ValueError("business_checks必须是列表")

    for check in business_checks:
        if not isinstance(check, dict):
            raise ValueError("每个业务检查必须是JSON对象")

        if check.get("kind") != "tool_outcome":
            raise ValueError("目前只支持tool_outcome业务检查")

        index = check.get("call_index")
        if type(index) is not int or index < 0:
            raise ValueError("call_index必须是大于等于0的整数")

        name = check.get("tool_name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool_name必须是非空字符串")

        if check.get("expected") not in {
            "SUCCEEDED", "NO_MATCH", "FAILED"
        }:
            raise ValueError(
                "expected必须是SUCCEEDED、NO_MATCH或FAILED"
            )

    adapter = config.get("adapter", "spring_sse")
    if adapter not in {"spring_sse", "json_v1"}:
        raise ValueError("adapter必须是spring_sse或json_v1")

    return config


def check_tool_outcomes(checks, calls):
    """根据真实工具记录，逐项检查业务返回状态。"""
    results = []

    for check in checks:
        index = check["call_index"]

        result = {
            "kind": check["kind"],
            "call_index": index,
            "tool_name": check["tool_name"],
            "expected": check["expected"],
            "actual": None,
            "status": "INCONCLUSIVE",
            "reason": "",
        }

        if index >= len(calls):
            result["status"] = "FAIL"
            result["reason"] = "没有发生预期位置的工具调用"
        else:
            call = calls[index]
            actual = call.get("outcome")
            result["actual"] = actual

            if call["toolName"] != check["tool_name"]:
                result["status"] = "FAIL"
                result["reason"] = "该位置调用的工具与预期不一致"

            elif actual not in {
                "SUCCEEDED", "NO_MATCH", "FAILED"
            }:
                result["reason"] = "工具结果缺失或无法确定"

            elif actual == check["expected"]:
                result["status"] = "PASS"
                result["reason"] = "工具返回状态符合预期"

            else:
                result["status"] = "FAIL"
                result["reason"] = "工具返回状态与预期不一致"

        results.append(result)

    return results

def run_case(config_path, token=None):
    config_path = Path(config_path).resolve()

    observed = {
        "conversation_id": str(uuid4()),
        "request_started": False,
        "completed": False,
        "answer": "",
        "trace_received": False,
        "calls": None,
        "truncated": None,
    }

    report = {
        "schema_version": 1,
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live",
        "deepeval_version": version("deepeval"),
        "config_file": str(config_path),
        "case_id": None,
        "endpoint": None,
        "input": None,
        "expected_tools": [],
        "status": "ERROR",
        "metric": None,
        "business_checks": [],
        "error": None,
    }

    try:
        config = load_live_config(config_path)

        report["case_id"] = config["case_id"]
        report["endpoint"] = config["endpoint"]
        report["input"] = config["input"]
        report["expected_tools"] = config["expected_tools"]
        report["comparison_spec"] = {
            "version": 1,
            "endpoint": config["endpoint"],
            "input": config["input"],
            "expected_tools": config["expected_tools"],
            "business_checks": config.get("business_checks", []),
            "tool_matching": "exact_name_type_and_input_parameters",
            "threshold": 1.0,
            "deepeval_version": version("deepeval"),
            "adapter": config.get("adapter", "spring_sse"),
        }


        adapter = config.get("adapter", "spring_sse")

        if adapter == "spring_sse":
            if token is None:
                token = getpass.getpass(
                    "请输入业务系统登录Token："
                ).strip()
            if not token:
                raise ValueError("登录Token不能为空")

        execute_agent(
            adapter,
            token,
            config["endpoint"],
            config["input"],
            observed,
        )

        # print("适配器填写的实际工具记录：")
        # print(json.dumps(observed["calls"], ensure_ascii=False, indent=2))

        if not observed["trace_received"]:
            raise EvidenceUnavailable("没有取得工具调用记录")

        if observed["truncated"] is not False:
            raise EvidenceUnavailable("工具记录缺失完整性标记或已截断")

        calls = observed["calls"]
        if not isinstance(calls, list):
            raise ValueError("工具调用记录必须是列表")

        actual_tools = []

        for call in calls:
            if (
                not isinstance(call, dict)
                or not isinstance(call.get("toolName"), str)
                or not call["toolName"].strip()
            ):
                raise ValueError("工具调用记录缺少有效工具名")

            tool_name = call["toolName"]

            if call.get("argumentsTruncated") is not False:
                raise EvidenceUnavailable(
                    f"{tool_name}的参数记录缺失或已截断"
                )

            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                raise EvidenceUnavailable(
                    f"没有取得{tool_name}的参数对象"
                )

            for expected in config["expected_tools"]:
                if expected["name"] == tool_name:
                    for parameter in expected["input_parameters"]:
                        if parameter not in arguments:
                            raise EvidenceUnavailable(
                                f"{tool_name}缺少参数证据：{parameter}"
                            )

            actual_tools.append(
                ToolCall(
                    name=tool_name,
                    input_parameters=arguments,
                )
            )

        expected_tools = [
            ToolCall(
                name=tool["name"],
                input_parameters=tool["input_parameters"],
            )
            for tool in config["expected_tools"]
        ]

        case = LLMTestCase(
            input=config["input"],
            actual_output=observed["answer"],
            tools_called=actual_tools,
            expected_tools=expected_tools,
        )

        metric = ToolCorrectnessMetric(
            model=NoJudgeModel(),
            eval_mode="llm",
            async_mode=False,
            should_exact_match=True,
            evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
            threshold=1.0,
        )
        metric.measure(case)

        report["status"] = (
            "PASS" if metric.is_successful() else "FAIL"
        )
        report["metric"] = {
            "name": "ToolCorrectnessMetric",
            "score": metric.score,
            "threshold": metric.threshold,
            "reason": metric.reason,
            "matching": "exact_name_type_and_input_parameters",
        }

        business_results = check_tool_outcomes(
            config.get("business_checks", []),
            calls,
        )
        report["business_checks"] = business_results

        statuses = [
            report["status"],
            *[item["status"] for item in business_results],
        ]

        if "FAIL" in statuses:
            report["status"] = "FAIL"
        elif "INCONCLUSIVE" in statuses:
            report["status"] = "INCONCLUSIVE"
        else:
            report["status"] = "PASS"

    except EvidenceUnavailable as error:
        report["status"] = "INCONCLUSIVE"
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }

    except Exception as error:
        report["status"] = "ERROR"

        if isinstance(error, (AgentCallError, ValueError, OSError)):
            public_message = str(error)
        else:
            public_message = "执行异常，请查看本机终端"

        report["error"] = {
            "type": type(error).__name__,
            "message": public_message,
        }
        print("本机错误详情：", error)

    report["observation"] = observed

    counts = {
        "PASS": 0,
        "FAIL": 0,
        "ERROR": 0,
        "INCONCLUSIVE": 0,
        "SKIPPED": 0,
    }
    counts[report["status"]] = 1
    report["summary"] = {"total": 1, **counts}

    return report

def main():
    parser = argparse.ArgumentParser(
        description="通过配置执行真实Agent工具调用评测"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="配置文件路径",
    )
    args = parser.parse_args()

    report = run_case(args.config)

    try:
        output = save_report(report)
    except OSError as error:
        print("报告保存失败：", error)
        return 2

    print("评测状态：", report["status"])
    print("评分详情：", report["metric"])
    print(
        "业务检查：",
        json.dumps(
            report["business_checks"],
            ensure_ascii=False,
            indent=2,
        ),
    )
    print("错误详情：", report["error"])
    print("报告已保存：", output)

    if report["status"] == "PASS":
        return 0
    if report["status"] == "FAIL":
        return 1
    return 2

if __name__ == "__main__":
    raise SystemExit(main())