import argparse
import json
import sys
from pathlib import Path

from . import __version__

def validate_case(case, seen_ids, position):
    """校验单个场景，同时检查编号是否重复。"""
    prefix = f"第 {position} 个场景"

    if not isinstance(case, dict):
        raise ValueError(f"{prefix}必须是 JSON 对象")

    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"{prefix}的 id 必须是非空字符串")

    if case_id != case_id.strip():
        raise ValueError(f"{prefix}的 id 首尾不能有空格")

    if case_id in seen_ids:
        raise ValueError(f"场景 id 重复：{case_id}")

    seen_ids.add(case_id)

    description = case.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{prefix}的 description 必须是非空字符串")

    messages = case.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{prefix}的 messages 必须是非空列表")

    for message in messages:
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"{prefix}的每条消息必须是非空字符串")

    checks = case.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"{prefix}的 checks 必须是非空列表")

    for check in checks:
        if not isinstance(check, dict):
            raise ValueError(f"{prefix}的每个检查项必须是 JSON 对象")

        if check.get("kind") != "tool_used":
            raise ValueError(f"{prefix}目前只支持 tool_used 检查类型")

        expected = check.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"{prefix}的 expected 必须是 JSON 对象")

        tool_name = expected.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError(f"{prefix}的 expected.name 必须是非空字符串")

def load_suite(path):
    """读取场景文件，检查当前版本要求的基本结构。"""
    content = Path(path).read_text(encoding="utf-8-sig")
    suite = json.loads(content)

    if not isinstance(suite, dict):
        raise ValueError("场景文件最外层必须是一个 JSON 对象")

    version = suite.get("schema_version")
    if type(version) is not int or version != 1:
        raise ValueError("目前只支持 schema_version 为整数 1")

    name = suite.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name 必须是非空字符串")

    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases 必须是非空列表")

    seen_ids = set()

    for position, case in enumerate(cases, start=1):
        validate_case(case, seen_ids, position)

    return suite


def main():
    parser = argparse.ArgumentParser(
        description="业务 Agent 回归评测工具"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )
    validate_command = commands.add_parser(
        "validate",
        help="检查场景文件的基本结构",
    )
    validate_command.add_argument("suite", help="场景文件路径")

    args = parser.parse_args()

    try:
        suite = load_suite(args.suite)
    except (OSError, ValueError) as error:
        print(f"校验失败：{error}", file=sys.stderr)
        return 2

    result = {
        "validation": "VALID",
        "suite": suite["name"],
        "case_count": len(suite["cases"]),
        "evaluation_executed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())