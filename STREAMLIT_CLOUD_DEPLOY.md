# Streamlit Community Cloud 部署清单

## 仓库要求

- GitHub 仓库根目录包含 `app.py`、`requirements.txt` 和 `fund_ai_research/`。
- 不要提交 `.env`、`.streamlit/secrets.toml` 或任何真实 API Key。
- 本项目已包含 `.gitignore`、`.streamlit/config.toml` 和 `runtime.txt`。

## 创建应用

1. 将本项目推送到 GitHub。
2. 登录 `https://share.streamlit.io/`，点击 **Create app**。
3. 选择仓库、分支和入口文件 `app.py`。
4. 在 Advanced settings 的 Secrets 中粘贴需要的配置。
5. 点击 Deploy，等待应用完成构建。

## Secrets 示例

不使用大模型时无需配置 Secrets，页面会使用离线规则基线。

接入 DeepSeek 时配置：

```toml
DEEPSEEK_API_KEY = "在 Streamlit Cloud 控制台填写"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
LLM_TIMEOUT_SECONDS = "20"
```

接入 Grok 中转时配置：

```toml
GROK_API_KEY = "在 Streamlit Cloud 控制台填写"
GROK_BASE_URL = "你的 OpenAI-compatible 地址"
GROK_MODEL = "grok-4.5"
LLM_TIMEOUT_SECONDS = "20"
```

不要把上述内容写进 GitHub 文件。Streamlit Cloud 会将 Secrets 注入运行环境，代码通过环境变量读取。

## 数据源

页面默认使用“自动选择真实行情”：优先 Yahoo Finance，失败后尝试东方财富，两个真实接口都失败时才回退到演示数据并显示警告。真实交易仍需人工确认。
