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

推荐同时配置 Grok 主用和 DeepSeek 兜底：

```toml
GROK_API_KEY = "在 Streamlit Cloud 控制台填写"
GROK_BASE_URL = "公开可访问的 HTTPS OpenAI-compatible 地址"
GROK_MODEL = "grok-4.5"
DEEPSEEK_API_KEY = "在 Streamlit Cloud 控制台填写"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
LLM_TIMEOUT_SECONDS = "20"
```

如果只测试 DeepSeek，可以只保留 DeepSeek 三项。如果只测试 Grok，可以只保留 Grok 三项。Grok 和 DeepSeek 的请求失败时，代码会自动尝试下一供应商，最后回到离线规则分析。

Grok 中转端点必须能从 Streamlit Cloud 和 GitHub Actions 访问。Tailscale 的 `100.x.x.x` 内网地址只能在加入同一 Tailnet 的设备使用，不能直接作为云端 Secrets。

不要把真实 Key 写进仓库文件；只粘贴到 Secrets。已经在聊天或截图里暴露过的 Key 应先在供应商后台撤销，再生成新 Key。

## 定时后台抓取

仓库中的 `.github/workflows/scheduled_research.yml` 使用 GitHub Actions 在工作日北京时间 07:30、12:00、15:30 运行 `scripts/scheduled_research.py`。任务会抓取交易所官方公告和价格数据，执行质检与 AI 分析，将结果写到 `data/latest_research.json` / `data/latest_research.md`，然后自动提交。第一次可在 GitHub 的 **Actions -> Scheduled fund research -> Run workflow** 手动验证。

Actions Secrets 与 Streamlit Secrets 是两套独立配置，必须分别填写。

## 数据源

页面默认使用“官方披露 + 自动真实行情”：官方公告优先来自上交所/深交所，价格历史按 Yahoo Finance -> 东方财富 -> 演示数据回退。真实交易仍需人工确认。
