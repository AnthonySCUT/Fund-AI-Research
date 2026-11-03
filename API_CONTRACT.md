# Fund AI Research API

本仓库同时包含 Streamlit 研究网站和公开 API 客户端/数据结构。客户端面向实现 `POST /v1/research` 的 HTTPS 服务。

## 请求

```json
{
  "codes": ["510300", "510500"],
  "start": "2018-01-01",
  "end": "2026-09-21",
  "aggression": 45,
  "max_drawdown": 15,
  "horizon_days": 20,
  "commission_bps": 2.5,
  "slippage_bps": 5,
  "annual_fee_rate": 0.005
}
```

## 响应字段

客户端读取以下字段，并将完整 JSON 保存在 `raw` 中：

- `fetched_at`：数据和报告生成时间。
- `cache_hit`：本次是否命中缓存。
- `cache_expires_at`：缓存预计过期时间。
- `recommendations`：个性化持仓候选。
- `research_cards`：研究卡片。
- `sources`：来源信息；客户端也兼容 `data_sources` 字段。

## Python 客户端

```powershell
py -3 -m pip install -r requirements.txt
$env:FUND_RESEARCH_API_URL = "https://your-service.example.com"
$env:FUND_RESEARCH_API_TOKEN = "your-token"
py -3 examples\basic_request.py
```

调用代码示例位于 `examples/basic_request.py`，客户端实现位于 `fund_api/`。
