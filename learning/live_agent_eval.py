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


def call_hmdp(token, message, observed):
    payload = {
        "conversationId": observed["conversation_id"],
        "message": message,
    }

    observed["request_started"] = True

    with requests.post(
        "http://127.0.0.1:8085/ai/chat/stream",
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

def main():
    token = getpass.getpass("请输入点评登录Token：").strip()

    message = (
        "请只搜索名字包含“火锅”的店铺，"
        "搜索关键词请使用“火锅”，暂时不要查询详情或优惠券。"
    )

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
        "case_id": "search_shops_keyword",
        "input": message,
        "expected_tools": [
            {
                "name": "search_shops",
                "input_parameters": {"keyword": "火锅"},
            }
        ],
        "status": "ERROR",
        "metric": None,
        "error": None,
    }

    try:
        if not token:
            raise ValueError("登录Token不能为空")

        call_hmdp(token, message, observed)

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

            if tool_name == "search_shops":
                if call.get("argumentsTruncated") is not False:
                    raise EvidenceUnavailable("搜索参数记录缺失或已截断")

                arguments = call.get("arguments")
                if not isinstance(arguments, dict):
                    raise EvidenceUnavailable("没有取得搜索参数对象")

                keyword = arguments.get("keyword")
                if not isinstance(keyword, str):
                    raise EvidenceUnavailable("没有取得完整的搜索关键词")

                actual_tools.append(
                    ToolCall(
                        name=tool_name,
                        input_parameters={"keyword": keyword},
                    )
                )
            else:
                actual_tools.append(ToolCall(name=tool_name))

        expected = report["expected_tools"][0]

        case = LLMTestCase(
            input=message,
            actual_output=observed["answer"],
            tools_called=actual_tools,
            expected_tools=[
                ToolCall(
                    name=expected["name"],
                    input_parameters=expected["input_parameters"],
                )
            ],
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

        if isinstance(error, (AgentCallError, ValueError)):
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

    print("\n评测状态：", report["status"])
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