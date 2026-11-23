AI 基金智能投研 · Windows 桌面版

启动
1. 双击 FundAIResearch.exe。
2. 等待本地研究窗口打开。
3. 关闭窗口即可停止本地服务。

AI 接口配置
首次启动会创建：
%LOCALAPPDATA%\FundAIResearch\secrets.toml

用记事本打开该文件，填写 Grok 或 DeepSeek API Key。该文件仅保存在本机，不要分享或提交到 GitHub。
没有配置 API Key 时，应用使用项目现有的离线规则基线。

应用需要联网获取行情、公告和配置的 AI 服务；运行日志位于：
%LOCALAPPDATA%\FundAIResearch\desktop.log

WebView2 Runtime 需已安装在 Windows 中。
