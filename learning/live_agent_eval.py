import getpass
import json
from uuid import uuid4

import requests
from deepeval.metrics import ToolCorrectnessMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams


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


def call_hmdp(token, message):
    payload = {
        "conversationId": str(uuid4()),
        "message": message,
    }

    answer_parts = []
    trace = None
    completed = False

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
            raise ValueError("后端没有返回SSE，请检查接口或登录状态")

        for event_name, data in read_events(response):
            if event_name == "token":
                answer_parts.append(data["content"])
            elif event_name == "tool_trace":
                trace = data
            elif event_name == "error":
                raise RuntimeError(
                    f"本轮请求未完成：{data.get('content', '未知错误')}"
                )
            elif event_name == "done":
                completed = True
                break

    if not completed:
        raise RuntimeError("没有收到done事件，不能把中断的请求当作完成")

    if not isinstance(trace, dict):
        raise ValueError("缺少工具记录，本轮无法评测")

    if trace.get("truncated") is not False:
        raise ValueError("工具记录不完整，本轮无法评测")

    calls = trace.get("calls")
    if not isinstance(calls, list):
        raise ValueError("工具记录格式错误")

    for call in calls:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("toolName"), str)
            or not call["toolName"].strip()
        ):
            raise ValueError("工具记录缺少有效工具名")

    return "".join(answer_parts), calls


def main():
    token = getpass.getpass("请输入点评登录Token：").strip()
    if not token:
        print("没有输入Token")
        return 2

    message = (
        "请只搜索名字包含“火锅”的店铺，"
        "搜索关键词请使用“火锅”，暂时不要查询详情或优惠券。"
    )

    try:
        answer, calls = call_hmdp(token, message)

        print("\n真实回答：")
        print(answer)

        print("\n后端实际工具记录：")

        actual_tools = []

        for call in calls:
            tool_name = call["toolName"]

            print("工具名：", tool_name)
            print("公开参数：", call.get("arguments"))
            print("结果状态：", call.get("outcome"))

            if tool_name == "search_shops":
                if call.get("argumentsTruncated") is not False:
                    raise ValueError("搜索参数记录缺失、已隐藏或已截断")

                arguments = call.get("arguments")
                if not isinstance(arguments, dict):
                    raise ValueError("搜索参数记录格式错误")

                keyword = arguments.get("keyword")
                if not isinstance(keyword, str):
                    raise ValueError("没有取得完整的搜索关键词证据")

                actual_tools.append(
                    ToolCall(
                        name=tool_name,
                        input_parameters={"keyword": keyword},
                    )
                )
            else:
                actual_tools.append(
                    ToolCall(name=tool_name)
                )

        case = LLMTestCase(
            input=message,
            actual_output=answer,
            tools_called=actual_tools,
            expected_tools=[
                ToolCall(
                    name="search_shops",
                    input_parameters={"keyword": "火锅"},
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

        print("\n工具调用匹配分数：", metric.score)
        print("是否通过：", metric.is_successful())
        print("原因：", metric.reason)

        return 0 if metric.is_successful() else 1

    except (
        requests.RequestException,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"本轮未获得有效评测结果：{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())