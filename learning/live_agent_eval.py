import getpass
import json
from uuid import uuid4

import requests
from deepeval.metrics import ToolCorrectnessMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import argparse
from urllib.parse import urlparse


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

class AgentCallError(RuntimeError):
    """应用请求没有正常完成。"""


class EvidenceUnavailable(ValueError):
    """请求完成，但没有取得足够的评测证据。"""


def read_events(response):
    """把SSE文本行组合成一个个事件。"""
    event_name = "message"
    data_lines = []

    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8")

        if line == "":
            if data_lines:
                yield event_name, json.loads("\n".join(data_lines))

            event_name = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].removeprefix(" "))


def call_hmdp(token, endpoint, message, observed):
    payload = {
        "conversationId": observed["conversation_id"],
        "message": message,
    }

    observed["request_started"] = True

    with requests.post(
        endpoint,
        headers={
            "Authorization": token,
            "Accept": "text/event-stream",
        },
        json=payload,
        stream=True,
        timeout=(5, 150),
    ) as response:
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            raise AgentCallError("后端没有返回SSE响应")

        for event_name, data in read_events(response):
            if not isinstance(data, dict):
                raise ValueError("SSE事件内容必须是JSON对象")

            if event_name == "token":
                content = data.get("content")
                if not isinstance(content, str):
                    raise ValueError("回答片段格式错误")
                observed["answer"] += content

            elif event_name == "tool_trace":
                observed["trace_received"] = True
                observed["calls"] = data.get("calls")
                observed["truncated"] = data.get("truncated")

            elif event_name == "error":
                raise AgentCallError(
                    data.get("content") or "应用返回错误事件"
                )

            elif event_name == "done":
                observed["completed"] = True
                break

    if not observed["completed"]:
        raise AgentCallError("连接结束时没有收到done事件")


def save_report(report):
    project_root = Path(__file__).resolve().parents[1]
    output = (
        project_root
        / "reports"
        / f"live-{report['run_id']}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

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

    return config

def main():
    parser = argparse.ArgumentParser(
        description="通过配置执行真实Agent工具调用评测"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="配置文件路径，相对项目根目录或使用绝对路径",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = project_root / config_path

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
        "error": None,
    }

    try:
        config = load_live_config(config_path)

        report["case_id"] = config["case_id"]
        report["endpoint"] = config["endpoint"]
        report["input"] = config["input"]
        report["expected_tools"] = config["expected_tools"]

        token = getpass.getpass("请输入点评登录Token：").strip()
        if not token:
            raise ValueError("登录Token不能为空")

        call_hmdp(
            token,
            config["endpoint"],
            config["input"],
            observed,
        )

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

    try:
        output = save_report(report)
    except OSError as error:
        print("报告保存失败：", error)
        return 2

    print("\n场景编号：", report["case_id"])
    print("评测状态：", report["status"])
    print("评分详情：", report["metric"])
    print("错误详情：", report["error"])
    print("报告已保存：", output)

    if report["status"] == "PASS":
        return 0
    if report["status"] == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())