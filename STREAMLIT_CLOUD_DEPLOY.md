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

默认 AI 服务为 DeepSeek；如需其他 OpenAI-compatible 服务，可同时添加 `LLM_*` 配置。自定义接口优先，失败时自动回退到 DeepSeek。

```toml
DEEPSEEK_API_KEY = "在 Streamlit Cloud 控制台填写"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
# Optional custom OpenAI-compatible provider.
LLM_API_KEY = ""
LLM_BASE_URL = ""
LLM_MODEL = ""
LLM_TIMEOUT_SECONDS = "20"
```

不使用大模型时无需配置 Secrets，页面会使用规则化研究。自定义端点需能从 Streamlit Cloud 和 GitHub Actions 访问。

不要把真实 Key 写进仓库文件；只粘贴到 Secrets。已经在聊天或截图里暴露过的 Key 应先在供应商后台撤销，再生成新 Key。

## 定时后台抓取

仓库中的 `.github/workflows/scheduled_research.yml` 使用 GitHub Actions 在工作日北京时间 07:30、12:00、15:30 运行 `scripts/scheduled_research.py`。任务会抓取交易所官方公告和价格数据，执行质检与 AI 分析，将结果写到 `data/latest_research.json` / `data/latest_research.md`，然后自动提交。第一次可在 GitHub 的 **Actions -> Scheduled fund research -> Run workflow** 手动验证。

Actions Secrets 与 Streamlit Secrets 是两套独立配置，必须分别填写。

## 数据源

页面默认使用“官方披露 + 自动真实行情”：官方公告优先来自上交所/深交所，价格历史按 Yahoo Finance -> 东方财富 -> 演示数据回退。真实交易仍需人工确认。
