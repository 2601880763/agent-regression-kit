import requests
import json

class AgentCallError(RuntimeError):
    """应用请求没有正常完成。"""
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

def call_spring_sse(token, endpoint, message, observed):
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

def call_json_agent(token, endpoint, message, observed):
    """接入本轮约定的同步JSON接口。"""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = token

    observed["request_started"] = True

    response = requests.post(
        endpoint,
        headers=headers,
        json={
            "conversation_id": observed["conversation_id"],
            "input": message,
        },
        timeout=(5, 150),
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise AgentCallError("JSON接口响应必须是对象")

    if payload.get("success") is not True:
        raise AgentCallError("JSON接口返回业务失败")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise AgentCallError("JSON接口缺少data对象")

    answer = data.get("answer")
    if not isinstance(answer, str):
        raise AgentCallError("JSON接口缺少有效answer")

    observed["answer"] = answer

    # 没有记录就不能假装有记录，交给评分入口判断证据是否充分。
    observed["trace_received"] = "calls" in data
    observed["calls"] = data.get("calls")
    observed["truncated"] = data.get("truncated")
    observed["completed"] = True


def execute_agent(adapter, token, endpoint, message, observed):
    if adapter == "spring_sse":
        return call_spring_sse(
            token, endpoint, message, observed
        )

    if adapter == "json_v1":
        return call_json_agent(
            token, endpoint, message, observed
        )

    raise ValueError(f"不支持的adapter：{adapter}")