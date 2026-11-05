from deepeval.test_case import LLMTestCase, ToolCall


case = LLMTestCase(
    input="帮我找几家火锅店",
    actual_output="为你找到两家火锅店。",
    tools_called=[
        ToolCall(
            name="search_shops",
            input_parameters={"keyword": "火锅"},
        )
    ],
    expected_tools=[
        ToolCall(
            name="search_shops",
            input_parameters={"keyword": "火锅"},
        )
    ],
)

print("用户输入：", case.input)
print("实际回答：", case.actual_output)

print("\n实际工具调用：")
for tool in case.tools_called:
    print("工具名：", tool.name)
    print("参数：", tool.input_parameters)

print("\n预期工具调用：")
for tool in case.expected_tools:
    print("工具名：", tool.name)
    print("参数：", tool.input_parameters)