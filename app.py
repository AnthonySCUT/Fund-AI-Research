from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from fund_ai_research.analysis import OpenAICompatibleAnalyzer, ResearchCard, analyze_metrics
from fund_ai_research.connectors import DEFAULT_FUNDS
from fund_ai_research.pipeline import PipelineResult, run_pipeline


st.set_page_config(page_title="AI 基金智能投研 MVP", page_icon="📊", layout="wide")

APP_VERSION = "official-disclosure-auto-v3"
if st.session_state.get("_app_version") != APP_VERSION:
    for _key in ("result", "cards", "params"):
        st.session_state.pop(_key, None)
    st.session_state["_app_version"] = APP_VERSION


def pct(value: float) -> str:
    return f"{value:.1%}"


def profile_label(profile) -> str:
    return f"{profile.code} · {profile.name} · {profile.category}"


def load_snapshot_cards(path: Path) -> dict[str, ResearchCard]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cards = {}
    for item in payload.get("research_cards", []):
        code = item.get("code")
        if not code:
            continue
        cards[code] = ResearchCard(
            code=code,
            status=item.get("status", "黄灯"),
            facts=item.get("facts", []),
            positive_evidence=item.get("positive_evidence", []),
            risk_signals=item.get("risk_signals", []),
            verification_questions=item.get("verification_questions", []),
            conclusion=item.get("conclusion", "等待人工复核。"),
            source=item.get("source", "后台快照"),
        )
    return cards


def run_once(codes, source_mode, start, end, aggression, max_drawdown, horizon_days, commission_bps, slippage_bps, annual_fee_rate):
    return run_pipeline(
        codes=codes,
        source_mode=source_mode,
        start=start,
        end=end,
        aggression=aggression,
        max_drawdown=max_drawdown,
        horizon_days=horizon_days,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        annual_fee_rate=annual_fee_rate,
    )


profiles = {profile.code: profile for profile in DEFAULT_FUNDS}
grok_config = OpenAICompatibleAnalyzer(provider="grok")
deepseek_config = OpenAICompatibleAnalyzer(provider="deepseek")
snapshot_path = Path(__file__).parent / "data" / "latest_research.json"
scheduled_cards = load_snapshot_cards(snapshot_path) if snapshot_path.exists() else {}
with st.sidebar:
    st.header("研究参数")
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            st.caption(f"后台快照：{snapshot.get('fetched_at', '未知时间')}")
        except (OSError, ValueError):
            st.caption("后台快照：读取失败")
    if grok_config.enabled and deepseek_config.enabled:
        st.success(f"AI 分析：{grok_config.label} 主用，{deepseek_config.label} 兜底")
    elif grok_config.enabled:
        st.success(f"AI 分析：{grok_config.label}（未配置 DeepSeek 兜底）")
    elif deepseek_config.enabled:
        st.warning(f"AI 分析：{deepseek_config.label}（Grok 不可用）")
    else:
        st.info("AI 分析：离线规则基线")
    with st.form("research_parameters"):
        source_label = st.radio(
            "数据源",
            ["官方披露 + 自动真实行情（推荐）", "演示数据（离线可用）", "中国 ETF 真实行情（东方财富）", "Yahoo Finance 公共接口"],
            index=0,
        )
        if source_label.startswith(("官方", "自动")):
            source_mode = "auto"
        elif source_label.startswith("中国"):
            source_mode = "eastmoney"
        elif source_label.startswith("Yahoo"):
            source_mode = "yahoo"
        else:
            source_mode = "demo"
        default_codes = list(profiles)[:4]
        selected_codes = st.multiselect(
            "研究基金",
            options=list(profiles),
            default=default_codes,
            format_func=lambda code: profile_label(profiles[code]),
        )
        today = date.today()
        start = st.date_input("历史起点", value=max(date(2017, 1, 1), today - timedelta(days=365 * 8)))
        end = st.date_input("历史终点", value=today)
        st.divider()
        aggression = st.slider("激进程度", 0, 100, 45, help="主要个性化参数：越高，战术仓目标越高，允许的波动和回撤也越大。")
        max_drawdown = st.slider("可接受最大回撤（%）", 5.0, 50.0, 15.0, 1.0)
        horizon_days = st.select_slider("计划持有期（交易日）", options=[1, 5, 20, 60, 252], value=20)
        st.caption("成本参数用于净收益情景，不是收益保证。")
        commission_bps = st.number_input("单边佣金（bps）", 0.0, 100.0, 2.5, 0.5)
        slippage_bps = st.number_input("单边滑点（bps）", 0.0, 200.0, 5.0, 0.5)
        annual_fee_rate = st.number_input("年化基金费率（%）", 0.0, 10.0, 0.5, 0.1) / 100
        run_button = st.form_submit_button("运行抓取与分析", type="primary", width="stretch")

st.markdown(
    """
    <style>
    .project-heading {
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 0.9rem;
        margin: 0 0 0.35rem;
    }
    .project-heading h1 {
        margin: 0;
        font-size: 2.65rem;
        line-height: 1.15;
        letter-spacing: 0;
    }
    .project-team {
        display: inline-block;
        padding: 0.28rem 0.75rem;
        border: 1px solid #b7d4f7;
        border-radius: 999px;
        background: #eef6ff;
        color: #165a9e;
        font-size: 1.05rem;
        font-weight: 650;
        line-height: 1.5;
        white-space: normal;
    }
    .project-team a {
        color: #0b63b6;
        text-decoration: none;
        border-bottom: 1px solid currentColor;
    }
    .project-team a:hover,
    .project-team a:focus {
        color: #084b8a;
    }
    .project-affiliation {
        display: inline-block;
        padding: 0.26rem 0.7rem;
        border: 1px solid #ead9ad;
        border-radius: 999px;
        background: #fff9eb;
        color: #775b21;
        font-size: 0.98rem;
        font-weight: 600;
        line-height: 1.5;
        white-space: normal;
    }
    @media (max-width: 720px) {
        .project-heading h1 { font-size: 2rem; }
        .project-team,
        .project-affiliation { font-size: 0.95rem; }
    }
    </style>
    <div class="project-heading">
        <h1>AI 基金智能投研 MVP</h1>
        <span class="project-team">（协作者：<a href="https://github.com/AnthonySCUT" target="_blank" rel="noopener noreferrer">潘逸航</a> · <a href="https://github.com/May-the-first" target="_blank" rel="noopener noreferrer">陈朴凡</a> · 李金洁）</span>
        <span class="project-affiliation">华南理工大学 · 2024级本科生</span>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption("数据抓取、质检、指标计算、证据式研究卡片和个性化持仓候选。任何真实交易都需要人工确认。")
if not selected_codes:
    st.warning("请至少选择一支基金。")
    st.stop()

params = {
    "codes": tuple(selected_codes),
    "source_mode": source_mode,
    "start": start,
    "end": end,
    "aggression": aggression,
    "max_drawdown": max_drawdown,
    "horizon_days": horizon_days,
    "commission_bps": commission_bps,
    "slippage_bps": slippage_bps,
    "annual_fee_rate": annual_fee_rate,
}
if run_button or "result" not in st.session_state:
    with st.spinner("正在抓取、质检并计算候选组合…"):
        st.session_state.result = run_once(**params)
        st.session_state.params = params
    st.session_state.pop("cards", None)

result: PipelineResult = st.session_state.result
if "cards" not in st.session_state:
    if grok_config.enabled or deepseek_config.enabled:
        with st.spinner("正在生成研究卡片（所有基金合并为一次 AI 请求）…"):
            st.session_state.cards = analyze_metrics(result.metrics, result.quality, result.events)
    elif scheduled_cards:
        st.session_state.cards = {code: card for code, card in scheduled_cards.items() if code in profiles}
        st.info("当前使用 GitHub Actions 最近一次后台 AI 快照；配置 Streamlit Secrets 后可在页面内实时分析。")
    else:
        with st.spinner("正在生成离线规则研究卡片…"):
            st.session_state.cards = analyze_metrics(result.metrics, result.quality, result.events)
cards = st.session_state.cards

profile = result.profile
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("研究基金", len(result.metrics))
kpi2.metric("核心仓目标", f"{profile['core_weight']}%")
kpi3.metric("战术仓目标", f"{profile['tactical_weight']}%")
kpi4.metric("现金缓冲", f"{profile['cash_weight']}%")
st.caption(f"截至 {result.fetched_at} · 数据源：{result.metrics[0].source if result.metrics else '无'} · 口径：{profile['cost_assumption']}")
fallback_codes = [item.code for item in result.metrics if "演示数据" in item.source]
if fallback_codes and params["source_mode"] != "demo":
    st.error(
        "真实行情抓取失败，以下标的使用了随机演示数据，不能与实际基金走势比较："
        + "、".join(fallback_codes)
        + "。请检查网络或改用东方财富接口。"
    )

tab_reco, tab_metrics, tab_events, tab_quality = st.tabs(["个性化建议", "基金对比", "事件与证据", "数据质检"])

with tab_reco:
    st.subheader("候选组合")
    st.info("AI 负责统一执行数据整理、规则计算和证据结构化；使用者负责选择研究假设、风险偏好和最终行动。")
    if result.recommendations:
        display = result.recommendations_frame[["role", "code", "name", "target_weight", "action", "net_return_range", "max_drawdown"]].copy()
        display["target_weight"] = display["target_weight"].map(lambda x: f"{x:.0f}%")
        display["max_drawdown"] = display["max_drawdown"].map(pct)
        display.columns = ["仓位角色", "代码", "基金", "目标权重", "研究状态", "净收益情景（低/中/高）", "历史最大回撤"]
        st.dataframe(display, hide_index=True, width="stretch")
        allocation = pd.DataFrame(
            {"目标权重": [profile["core_weight"], profile["tactical_weight"], profile["cash_weight"]]},
            index=["核心仓", "战术仓", "现金"],
        )
        st.bar_chart(allocation, horizontal=True)
        for item in result.recommendations:
            with st.expander(f"{item.role} · {item.code} {item.name} · {item.action}"):
                st.write(item.reason)
                st.write("**证据与口径**")
                for evidence in item.evidence:
                    st.markdown(f"- {evidence}")
                st.write("**风险信号 / 待核实**")
                for flag in item.risk_flags:
                    st.markdown(f"- {flag}")
    else:
        st.warning("当前筛选没有形成候选建议，请检查数据质量。")

    st.subheader("AI 研究卡片")
    for code, card in cards.items():
        with st.expander(f"{code} · {profiles[code].name} · {card.status} · {card.source}"):
            st.write(card.conclusion)
            col_a, col_b = st.columns(2)
            with col_a:
                st.write("**已披露/可计算事实**")
                for fact in card.facts:
                    st.markdown(f"- {fact}")
                st.write("**正面证据**")
                for item in card.positive_evidence or ["暂无足够正面证据，需继续核验。"]:
                    st.markdown(f"- {item}")
            with col_b:
                st.write("**风险信号**")
                for item in card.risk_signals:
                    st.markdown(f"- {item}")
                st.write("**仍需验证**")
                for item in card.verification_questions:
                    st.markdown(f"- {item}")

with tab_metrics:
    st.subheader("历史指标对比")
    frame = result.metrics_frame.copy()
    shown = frame[["code", "name", "category", "total_return", "annualized_return", "annualized_volatility", "max_drawdown", "calmar_ratio", "quality_score", "as_of"]].copy()
    shown.columns = ["代码", "基金", "类型", "累计收益", "年化收益", "年化波动", "最大回撤", "收益/回撤", "质量分", "截至"]
    for column in ["累计收益", "年化收益", "年化波动", "最大回撤", "质量分"]:
        shown[column] = shown[column].map(pct)
    shown["收益/回撤"] = shown["收益/回撤"].map(lambda x: f"{x:.2f}")
    st.dataframe(shown, hide_index=True, width="stretch")
    compare = frame.set_index("name")[["total_return", "annualized_return", "max_drawdown"]].rename(
        columns={"total_return": "累计收益", "annualized_return": "年化收益", "max_drawdown": "最大回撤"}
    )
    st.bar_chart(compare)
    selected_chart = st.selectbox("查看净值与回撤", options=list(result.histories), format_func=lambda code: profile_label(profiles[code]))
    history = result.histories[selected_chart].set_index("trade_date")
    st.line_chart(history[["close"]].rename(columns={"close": "净值/收盘价"}))
    st.line_chart(history[["drawdown"]].rename(columns={"drawdown": "回撤"}))

with tab_events:
    st.subheader("自动抓取的事件线索")
    st.caption("事件线索必须回到原始公告、定期报告或监管文件核验；新闻摘要不直接作为交易依据。")
    if result.events:
        events = pd.DataFrame([event.as_dict() for event in result.events])
        events = events.rename(columns={"code": "代码", "title": "标题", "publisher": "发布方", "published_at": "发布时间", "url": "链接", "source": "来源"})
        try:
            st.dataframe(events, hide_index=True, width="stretch", column_config={"链接": st.column_config.LinkColumn("链接")})
        except AttributeError:
            st.dataframe(events, hide_index=True, width="stretch")
    else:
        st.info("当前数据源没有返回事件。")

with tab_quality:
    st.subheader("数据质检")
    st.dataframe(result.quality_frame, hide_index=True, width="stretch")
    for report in result.quality:
        if report.warnings:
            st.warning(f"{report.code}：" + "；".join(report.warnings))
    selected_raw = st.selectbox("查看标准化样例", options=list(result.histories), key="raw_select")
    st.dataframe(result.histories[selected_raw].tail(100), hide_index=True, width="stretch")

st.divider()
st.caption("研究原型不构成证券或基金投资建议，不自动下单，不承诺收益。生产化前应补充授权数据、公开披露引用、账户隔离、权限控制、审计日志与人工审批。")
