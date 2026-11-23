AI 基金智能投研 · Windows 桌面版

启动
1. 双击 FundAIResearch.exe。
2. 等待本地研究窗口打开。
3. 关闭窗口即可停止本地服务。

AI 接口配置
首次启动会创建：
%LOCALAPPDATA%\FundAIResearch\secrets.toml

用记事本打开该文件，填写 DEEPSEEK_API_KEY。应用默认使用 DeepSeek；也可以填写 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL 来连接自定义兼容接口。
没有配置 API Key 时，应用使用规则化研究。

应用需要联网获取行情、公告和配置的 AI 服务；运行日志位于：
%LOCALAPPDATA%\FundAIResearch\desktop.log

WebView2 Runtime 需已安装在 Windows 中。
