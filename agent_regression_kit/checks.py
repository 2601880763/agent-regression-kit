def check_tool_used(expected_name, tools_called):
    """检查调用记录中是否包含预期工具；不判断工具执行是否成功。"""
    if not isinstance(expected_name, str) or not expected_name.strip():
        raise ValueError("预期工具名必须是非空字符串")

    if tools_called is None:
        return {
            "kind": "tool_used",
            "status": "INCONCLUSIVE",
            "reason": "未取得工具调用记录",
        }

    if not isinstance(tools_called, list):
        return {
            "kind": "tool_used",
            "status": "ERROR",
            "reason": "工具调用记录必须是列表",
        }

    for name in tools_called:
        if not isinstance(name, str) or not name.strip():
            return {
                "kind": "tool_used",
                "status": "ERROR",
                "reason": "调用记录中的工具名必须是非空字符串",
            }

    matched = expected_name in tools_called

    return {
        "kind": "tool_used",
        "status": "PASS" if matched else "FAIL",
        "reason": (
            f"已调用预期工具：{expected_name}"
            if matched
            else f"未调用预期工具：{expected_name}"
        ),
        "observed_tools": list(tools_called),
    }