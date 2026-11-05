from deepeval.metrics import ToolCorrectnessMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams


class NoJudgeModel(DeepEvalBaseLLM):
    """本轮不允许调用评审模型；如果意外调用，立即报错。"""

    def load_model(self):
        return self

    def generate(self, *args, **kwargs):
        raise RuntimeError("本轮不应调用评审模型")

    async def a_generate(self, *args, **kwargs):
        raise RuntimeError("本轮不应调用评审模型")

    def get_model_name(self):
        return "no-judge-model"


samples = [
    (
        "工具名和参数都正确",
        ToolCall(
            name="search_shops",
            input_parameters={"keyword": "火锅"},
        ),
        1.0,
    ),
    (
        "工具名错误",
        ToolCall(
            name="get_shop_detail",
            input_parameters={"shopId": 5},
        ),
        0.0,
    ),
    (
        "工具名正确，但参数错误",
        ToolCall(
            name="search_shops",
            input_parameters={"keyword": "咖啡"},
        ),
        0.0,
    ),
]


for title, actual_tool, expected_score in samples:
    case = LLMTestCase(
        input="帮我找几家火锅店",
        actual_output="这是手工构造的模拟回答。",
        tools_called=[actual_tool],
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

    print(f"\n场景：{title}")
    print("分数：", metric.score)
    print("是否通过：", metric.is_successful())
    print("原因：", metric.reason)

    assert metric.score == expected_score