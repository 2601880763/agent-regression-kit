from compare_reports import compare_case


def make_result(status, spec):
    return {
        "status": status,
        "comparison_spec": spec,
    }


spec = {"input": "搜索火锅", "expected": "SUCCEEDED"}

tests = [
    ("PASS", "FAIL", spec, "REGRESSION"),
    ("FAIL", "PASS", spec, "IMPROVEMENT"),
    ("PASS", "PASS", spec, "STABLE_PASS"),
    ("FAIL", "FAIL", spec, "STABLE_FAIL"),
    ("PASS", "ERROR", spec, "UNRESOLVED"),
    (
        "PASS",
        "FAIL",
        {"input": "搜索火锅", "expected": "NO_MATCH"},
        "NOT_COMPARABLE",
    ),
]

for old_status, new_status, new_spec, expected in tests:
    actual, reason = compare_case(
        make_result(old_status, spec),
        make_result(new_status, new_spec),
    )

    assert actual == expected, (actual, expected)
    print(f"{old_status} → {new_status}：{actual}，{reason}")

print("全部比较逻辑检查通过")