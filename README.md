# AI 基金智能投研 MVP

这个原型把项目第一阶段落成一个可运行闭环：

`数据抓取 -> 数据质检 -> 标准化 -> 指标计算 -> 费用后情景 -> 个性化候选 -> 研究卡片`

## 运行

```powershell
cd C:\Users\AIR\Documents\Codex\2026-08-12\new-chat\fund-ai-research
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run app.py
```

浏览器打开终端显示的本地地址即可。页面默认自动选择真实行情：优先 Yahoo Finance，失败后尝试东方财富，两个真实接口都不可用时才回退到演示数据并显示警告。

## 当前能力

- 5 支示例被动基金：沪深 300、中证 500、创业板、创业板 50、纳指 ETF。
- 统一字段：`trade_date`、`close`、`aum`、`volume`、`source_id`、`fetched_at`。
- 自动检查重复日期、工作日缺失、负值、有效区间和数据质量分。
- 计算累计收益、年化收益、年化波动、最大回撤、收益/回撤比、60 日动量和胜率。
- 费用模型包含单边佣金、单边滑点、年化基金费率和计划持有期。
- 激进程度滑块决定核心仓/战术仓/现金的目标比例；最大回撤由用户确认。
- 研究卡片区分事实、正面证据、风险信号、待验证问题和研究结论。
- 若配置 `LLM_API_KEY`，可通过 `LLM_BASE_URL` 接入 OpenAI-compatible 的 JSON 分析器；也支持 `GROK_API_KEY`、`GROK_BASE_URL`、`GROK_MODEL` 别名。未配置时使用离线规则基线。
- 配好 `GROK_*` 环境变量后，也可以直接运行 `run_grok.ps1` 启动页面。
- 也可以直接运行 `start.ps1`，脚本会提示输入 Key 并自动配置 Grok。
- 也可以运行 `start_deepseek.ps1`，使用 DeepSeek 的 OpenAI-compatible 接口分析研究卡片。
- 侧边栏参数放在表单中，修改后点击“运行抓取与分析”才会发起新任务；选中多支基金时会并行抓取，并将 AI 研究卡片合并为一次请求。

## 下一步接 CPF 数据

1. 把 CPF 的 `fund_master`、`fund_nav_daily`、`fund_event` 映射到 `fund_ai_research/connectors.py` 的统一输出字段。
2. 保留 `source_id`、来源 URL、发布时间、抓取时间、批次号和原始文件，不覆盖 raw 数据。
3. 将 `DemoConnector` 替换为 Parquet/DuckDB 读取器，再把抓取任务迁移到 Prefect。
4. 以 10-20 个标注样本建立 prompt 评测集，验证引用覆盖率、事实准确率、风险漏报率和费用计算一致性。

## 边界

当前版本不接券商账户、不自动下单，不把新闻摘要当成一级证据，也不构成投资建议。行情数据与 AI 分析是两个环节：DeepSeek 只负责结构化分析，不负责替代行情接口；生产化必须接入有授权且可追溯的公开披露数据。

## 加载时间说明

首次运行自动真实行情时，系统会并行抓取行情和新闻；网络异常时会尝试另一个真实接口，最后才回退到演示数据。配置 Grok 或 DeepSeek 后，多个基金会合并为一次研究请求，默认最多等待 20 秒；可通过 `LLM_TIMEOUT_SECONDS` 或 `GROK_TIMEOUT_SECONDS` 调整。结果会保存在当前页面会话中，调整页面显示不会再次调用 AI。

中国 ETF 默认选择 Yahoo Finance 真实行情，并带有浏览器请求头和 429 重试；也可以手动选择“中国 ETF 真实行情（东方财富）”。两个真实源都失败时，页面会明确提示“演示数据”，此时不能拿图表和实际基金走势比较。
