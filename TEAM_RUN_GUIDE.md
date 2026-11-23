# AI 基金智能投研：运行教程

## 1. 项目内容

本压缩包是第一阶段可运行原型，闭环如下：

`数据抓取 -> 数据质检 -> 标准化 -> 指标计算 -> 费用后情景 -> 个性化候选 -> AI 研究卡片`

当前版本默认使用“官方披露 + 自动真实行情”：事件优先抓取上交所/深交所基金公告，价格历史按 Yahoo Finance -> 东方财富 -> 演示数据回退。系统不会自动下单。

## 2. 环境要求

- Windows 10/11
- Python 3.11 或 3.12
- PowerShell
- 能访问 PyPI 镜像或互联网

检查 Python：

```powershell
py -3 --version
```

如果提示找不到 Python，请先安装 Python，并在安装时勾选“Add Python to PATH”。

## 3. 安装依赖

解压后进入项目目录：

```powershell
cd .\fund-ai-research
```

建议为项目创建独立虚拟环境：

```powershell
py -3 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果团队使用国内镜像，可以执行：

```powershell
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 4. 启动页面

```powershell
python -m streamlit run app.py
```

浏览器打开：

```text
http://localhost:8501
```

如果 8501 端口被占用：

```powershell
python -m streamlit run app.py --server.port 8502
```

## 5. 页面怎么用

1. 左侧默认选择“官方披露 + 自动真实行情（推荐）”；程序优先抓交易所官方公告，价格历史按 Yahoo Finance -> 东方财富回退。也可以手动选择单一真实接口或“演示数据（离线可用）”。
2. 在“研究基金”中选择要比较的基金。
3. 设置历史起点、终点和计划持有期。
4. 调整“激进程度”：数值越高，战术仓目标越高，波动和回撤风险也越高。
5. 设置可接受最大回撤、佣金、滑点和年化基金费率。
6. 点击“运行抓取与分析”。
7. 在“个性化建议”查看核心仓、战术仓、现金缓冲、净收益情景和风险信号。
8. 在“基金对比”查看收益、波动、回撤、净值曲线和回撤曲线。
9. 在“事件与证据”查看自动抓取的事件线索。新闻只作为线索，必须回到正式公告或定期报告核验。
10. 在“数据质检”查看重复、缺失、负值、数据质量分和标准化后的样例。

参数修改后请点击“运行抓取与分析”再提交。网络数据抓取会并行处理选中的基金；自定义兼容接口失败或返回不完整时会自动改用 DeepSeek，最后使用规则化基线。首次运行或切换数据源时等待时间较长属于正常现象，页面显示结果后，普通交互不会重复请求 AI。

## 6. 测试代码

在项目目录执行：

```powershell
python -m pytest -q
```

预期结果：5 个测试通过。

## 7. 测试真实行情抓取

默认自动模式即可测试真实行情；也可在页面左侧手动选择“中国 ETF 真实行情（东方财富）”或“Yahoo Finance 公共接口”，点击“运行抓取与分析”。

注意：

- Yahoo 接口可能受网络、频率和代码覆盖范围影响。
- Yahoo 限流时会优先回退到东方财富；两个真实接口都失败时才会使用演示数据，页面会显示红色警告，不能把这类图表与真实基金走势比较。
- Yahoo 新闻属于二级信息，不是一级公开披露证据。

## 8. AI 研究接口

项目默认使用 DeepSeek；配置 `LLM_*` 后优先调用用户指定的 OpenAI-compatible 接口，失败时回退到 DeepSeek。两类服务都不可用时使用规则化研究卡片。

首次启动可运行：

```powershell
.\start.ps1
```

脚本会可选地隐藏输入 DeepSeek Key；已有 `.streamlit/secrets.toml` 或环境变量时直接启动。桌面版可在 `%LOCALAPPDATA%\FundAIResearch\secrets.toml` 配置。

自定义接口可用环境变量配置：

```powershell
$env:LLM_API_KEY = "你的 API Key"
$env:LLM_BASE_URL = "https://你的兼容接口/v1"
$env:LLM_MODEL = "你的模型名称"
$env:LLM_TIMEOUT_SECONDS = "20"
python -m streamlit run app.py
```

只配置 DeepSeek 时使用 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。AI 只分析已抓取的结构化事实和事件线索，不替代行情数据源。

## 9. 目录说明

```text
app.py                         Streamlit 页面入口
fund_ai_research/models.py     数据模型
fund_ai_research/connectors.py 数据连接器和演示数据
fund_ai_research/analytics.py  标准化、质检和指标计算
fund_ai_research/recommender.py个性化权重与候选建议
fund_ai_research/analysis.py   规则化/可选大模型研究卡片
fund_ai_research/pipeline.py   抓取到建议的总流水线
scripts/scheduled_research.py  GitHub Actions 定时抓取与快照生成
.github/workflows/              工作日三次后台调度
tests/test_mvp.py              核心测试
requirements.txt               Python 依赖
```

## 10. 当前边界和下一步

- 当前不接券商账户，不自动下单，不构成投资建议。
- 真实生产数据应由 CPF 按统一字段交付，并保留来源 URL、发布时间、抓取时间、批次号和原始文件。
- 下一步优先把 CPF 的 `fund_master`、`fund_nav_daily`、`fund_event` 接入 Parquet/DuckDB。
- 当前已用 GitHub Actions 完成工作日三次调度和一级公开披露引用；后续再增加 Prompt 评测集、权限控制和人工批准流程。
