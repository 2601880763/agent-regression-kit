# agent-regression-kit
轻量级业务 Agent 回归评测工具，支持多轮对话、工具调用与业务结果验证。
## 安装

推荐使用 Python 3.11 独立环境。

在仓库根目录进行开发安装：

```powershell
python -m pip install -e ".[eval]"
```

也可以从 GitHub Release 下载 wheel 后安装：

```powershell
python -m pip install "./agent_regression_kit-0.1.0-py3-none-any.whl[eval]"
```

## 使用

单场景评测：

```powershell
agent-eval-live --config examples/live_search.json
```

批量评测：

```powershell
agent-eval-batch --config examples/live_suite.json
```

回归比较：

```powershell
agent-eval-compare --baseline reports/baseline.json --current reports/current.json --output reports/comparison.json
```

示例配置位于仓库的 examples 目录。用户可以下载示例或编写自己的配置。

## 接口适配

目前支持：

- spring_sse：约定的 Spring SSE 事件格式。
- json_v1：约定的同步 JSON 响应格式。

其他接口格式需要实现对应适配器。




