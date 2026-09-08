# AI 基金智能投研 MVP：组员运行教程

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

参数修改后请点击“运行抓取与分析”再提交。网络数据抓取会并行处理选中的基金；Grok 研究卡片失败或不完整时会自动改用 DeepSeek，最后才使用离线规则基线。首次运行或切换数据源时等待时间较长属于正常现象，页面显示结果后，普通交互不会重复请求 AI。

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

## 8. 可选：接入大模型研究卡片

默认使用离线规则化研究卡片，不需要 API Key。只有在团队明确配置后，才会调用 OpenAI-compatible 接口。

PowerShell 临时配置示例：

```powershell
$env:LLM_API_KEY = "你的 API Key"
$env:LLM_BASE_URL = "https://你的兼容接口/v1"
$env:LLM_MODEL = "你的模型名称"
python -m streamlit run app.py
```

当前只把公开行情指标和事件线索发送给接口，不要把账号、密码、身份证、券商 Token 或未脱敏持仓信息放进输入。生产化前必须增加权限、脱敏、审计和人工审批。

Grok 不可用时，代码会把同一批已抓取事实交给 DeepSeek；DeepSeek 不会自动替代交易所/行情接口，也不会凭空补全财报。官网公告链接仍需人工回看。

### 8.1 使用 Tailscale + CC Switch 的 Grok 中转

你的 Grok 配置属于 OpenAI Chat Completions 兼容端点，项目不需要 Anthropic SDK，也不需要把 CC Switch 的配置文件复制进项目。只要运行页面的电脑能通过 Tailscale 访问该地址，就可以直接使用。Streamlit Cloud 和 GitHub Actions 无法直接访问 `100.x.x.x` 内网地址，云端必须改成公开可访问的 HTTPS 端点：

```powershell
$env:GROK_API_KEY = "重新生成的 Key"
$env:GROK_BASE_URL = "http://100.94.190.42:18080/v1"
$env:GROK_MODEL = "grok-4.5"
.\run_grok.ps1
```

推荐直接运行交互式启动器，免去手动配置环境变量：

```powershell
.\start.ps1
```

脚本会用英文提示输入新的 API Key，输入时隐藏显示，并自动设置 Grok 地址和模型。启动后保持 PowerShell 窗口打开。

两个启动脚本均使用纯 ASCII 字符，兼容 Windows PowerShell 5.1。旧版脚本含有无 BOM 的 UTF-8 中文，可能在中文 Windows 上被错误解码，出现乱码、字符串未终止或缺少右括号等解析错误；请使用修复后的脚本。

也可以使用项目通用变量：

```powershell
$env:LLM_API_KEY = "重新生成的 Key"
$env:LLM_BASE_URL = "http://100.94.190.42:18080/v1"
$env:LLM_MODEL = "grok-4.5"
python -m streamlit run app.py
```

检查连通性（不会发送 API Key）：

```powershell
Test-NetConnection 100.94.190.42 -Port 18080
```

如果 `TcpTestSucceeded` 为 `False`，先确认 Tailscale 已登录、设备在线，并且 ACL 允许访问 18080 端口。不要把该地址改成带末尾 `/` 的形式；程序会自动拼接 `/chat/completions`。

安全要求：你在聊天中粘贴过的 Key 已经暴露，必须在供应商侧撤销并重新生成。不要把新 Key 写进 `app.py`、README、Git、截图或 ZIP；只在当前 PowerShell 会话用 `$env:GROK_API_KEY` 临时注入。

### 8.2 使用 DeepSeek

DeepSeek 使用 OpenAI-compatible Chat Completions，只替换 AI 分析服务，不替换行情数据源。推荐直接运行：

```powershell
.\start_deepseek.ps1
```

脚本会隐藏输入 Key，并自动设置：

```text
https://api.deepseek.com/v1
deepseek-chat
```

如需缩短模型等待时间，可在当前 PowerShell 会话设置：

```powershell
$env:GROK_TIMEOUT_SECONDS = "10"
```

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
