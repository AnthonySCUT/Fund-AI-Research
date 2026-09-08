# AI 基金智能投研 MVP

这个原型把项目第一阶段落成一个可运行闭环：

`数据抓取 -> 数据质检 -> 标准化 -> 指标计算 -> 费用后情景 -> 个性化候选 -> 研究卡片`

## 运行

```powershell
cd C:\Users\AIR\Documents\Codex\2026-08-12\new-chat\fund-ai-research
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run app.py
```

浏览器打开终端显示的本地地址即可。页面默认使用“官方披露 + 自动真实行情”：事件优先来自上交所/深交所基金公告，价格历史按 Yahoo Finance -> 东方财富 -> 演示数据回退，并在页面明确标注来源。

## 当前能力

- 5 支示例被动基金：沪深 300、中证 500、创业板、创业板 50、纳指 ETF。
- 统一字段：`trade_date`、`close`、`aum`、`volume`、`source_id`、`fetched_at`。
- 自动检查重复日期、工作日缺失、负值、有效区间和数据质量分。
- 计算累计收益、年化收益、年化波动、最大回撤、收益/回撤比、60 日动量和胜率。
- 费用模型包含单边佣金、单边滑点、年化基金费率和计划持有期。
- 激进程度滑块决定核心仓/战术仓/现金的目标比例；最大回撤由用户确认。
- 研究卡片区分事实、正面证据、风险信号、待验证问题和研究结论。
- AI 分析按 Grok -> DeepSeek 顺序尝试：Grok 请求失败、超时、鉴权失败或返回不完整时自动交给 DeepSeek；两者都不可用时使用离线规则基线。DeepSeek 只分析已抓取的结构化事实和公告链接，不替代官网行情接口。
- 上交所 ETF 披露页和深交所基金公告页作为一级事件来源，保存公告标题、发布日期、发布方和原始链接；页面编码异常时自动修正。
- 配好 `GROK_*` 环境变量后，也可以直接运行 `run_grok.ps1` 启动页面。
- 也可以直接运行 `start.ps1`，脚本会提示输入 Key 并自动配置 Grok。
- 也可以运行 `start_deepseek.ps1`，单独使用 DeepSeek 的 OpenAI-compatible 接口分析研究卡片；生产环境推荐同时配置两套 Secrets 以获得自动兜底。
- `.github/workflows/scheduled_research.yml` 会在工作日北京时间 07:30、12:00、15:30 自动运行，生成 `data/latest_research.json` 和 `data/latest_research.md` 并提交回 GitHub。Streamlit Cloud 会因提交自动重新部署。
- 侧边栏参数放在表单中，修改后点击“运行抓取与分析”才会发起新任务；选中多支基金时会并行抓取，并将 AI 研究卡片合并为一次请求。

## 下一步接组员抓取的多维数据

1. 把组员的 `fund_master`、`fund_nav_daily`、`fund_event` 映射到 `fund_ai_research/connectors.py` 的统一输出字段。
2. 保留 `source_id`、来源 URL、发布时间、抓取时间、批次号和原始文件，不覆盖 raw 数据。
3. 将 `DemoConnector` 替换为 Parquet/DuckDB 读取器，再把抓取任务迁移到 Prefect。
4. 以 10-20 个标注样本建立 prompt 评测集，验证引用覆盖率、事实准确率、风险漏报率和费用计算一致性。

## 边界

当前版本不接券商账户、不自动下单，不把新闻摘要当成一级证据，也不构成投资建议。行情、官网披露和 AI 分析是三个环节：DeepSeek 只负责结构化分析，不负责替代行情接口；生产化必须接入有授权且可追溯的公开披露数据。

## 加载时间说明

首次运行自动真实行情时，系统会并行抓取行情和新闻；网络异常时会尝试另一个真实接口，最后才回退到演示数据。配置 Grok 或 DeepSeek 后，多个基金会合并为一次研究请求，默认最多等待 20 秒；可通过 `LLM_TIMEOUT_SECONDS` 或 `GROK_TIMEOUT_SECONDS` 调整。结果会保存在当前页面会话中，调整页面显示不会再次调用 AI。

中国 ETF 的价格历史默认选择 Yahoo Finance 真实行情，并带有浏览器请求头和 429 重试；也可以手动选择“中国 ETF 真实行情（东方财富）”。两个真实源都失败时，页面会明确提示“演示数据”，此时不能拿图表和实际基金走势比较。

## 后台定时任务所需 Secrets

在 GitHub 仓库的 **Settings -> Secrets and variables -> Actions** 中添加：

```text
GROK_API_KEY       # Grok 主用密钥
GROK_BASE_URL      # 公开可访问的 HTTPS OpenAI-compatible 地址
GROK_MODEL         # 例如 grok-4.5
DEEPSEEK_API_KEY   # DeepSeek 兜底密钥
DEEPSEEK_BASE_URL  # https://api.deepseek.com/v1
DEEPSEEK_MODEL     # deepseek-chat
```

同样的配置需要粘贴到 Streamlit Cloud 的 **App settings -> Secrets**。不要把 Tailscale 内网地址写进云端：云端无法访问你电脑上的 `100.x.x.x` 地址，必须使用公开可访问的 HTTPS 中转端点或官方端点。用户在聊天中发送过的旧密钥应立即撤销并换新。
