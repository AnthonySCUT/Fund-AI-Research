from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from fund_ai_research.analysis import (
        FIVE_YEAR_TEN_X_ANNUALIZED,
        OpenAICompatibleAnalyzer,
        ResearchCard,
        analyze_metrics,
    )
except ImportError as exc:
    # Streamlit redacts startup tracebacks; expose only the import type/message
    # so a missing cloud dependency can be fixed without revealing secrets.
    st.set_page_config(page_title="AI 基金智能投研 MVP", page_icon="📊")
    st.error("应用依赖加载失败，暂时无法启动分析页面。")
    st.code(f"{type(exc).__name__}: {exc}")
    st.stop()

from fund_ai_research.connectors import DEFAULT_FUNDS
from fund_ai_research.pipeline import PipelineResult, run_pipeline

try:
    from fund_ai_research.analytics import max_drawdown_recovery_days, rolling_returns
except ImportError:
    # A short-lived mixed-version Streamlit deployment can load app.py before
    # the updated analytics.py. Keep the UI usable while the source cache
    # converges; the normal path still uses the shared analytics functions.
    def rolling_returns(history, windows=(21, 63, 252)):
        frame = history.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
        output = frame[["trade_date"]].copy()
        for window in windows:
            output[f"rolling_{window}d"] = frame["close"].pct_change(window)
        return output

    def max_drawdown_recovery_days(history):
        frame = history.copy()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["close"]).reset_index(drop=True)
        if frame.empty:
            return None
        drawdown = frame["close"] / frame["close"].cummax() - 1
        trough_index = int(drawdown.idxmin())
        recovered = drawdown.iloc[trough_index + 1 :]
        recovered = recovered[recovered >= -1e-12]
        return int(recovered.index[0] - trough_index) if not recovered.empty else None


st.set_page_config(page_title="AI 基金智能投研 MVP", page_icon="📊", layout="wide")

APP_VERSION = "expanded-universe-reports-v5"
if st.session_state.get("_app_version") != APP_VERSION:
    for _key in ("result", "cards", "params"):
        st.session_state.pop(_key, None)
    st.session_state["_app_version"] = APP_VERSION


def pct(value: float) -> str:
    return f"{value:.1%}"


def profile_label(profile) -> str:
    return f"{profile.code} · {profile.name} · {profile.category}"


def source_status(source: str) -> tuple[str, str]:
    """Classify provenance for display and recommendation guardrails."""
    if "演示数据" in source:
        return "演示数据", "不可用于实际走势比较"
    if "回退" in source:
        return "真实行情（回退）", "建议核对主数据源"
    return "真实行情", "可进入研究流程"


def as_display_number(value: float, suffix: str = "") -> str:
    if pd.isna(value):
        return "暂无"
    return f"{value:,.2f}{suffix}"


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
            goal_fit=item.get("goal_fit", ""),
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
        default_codes = list(profiles)[:12]
        selected_codes = st.multiselect(
            "研究基金",
            options=list(profiles),
            default=default_codes,
            format_func=lambda code: profile_label(profiles[code]),
        )
        st.caption("默认纳入 12 支被动 ETF；可继续勾选最多 15 支研究标的。")
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
        flex-direction: column;
        align-items: flex-start;
        gap: 0.5rem;
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
        <span class="project-team">参与者：<a href="https://github.com/AnthonySCUT" target="_blank" rel="noopener noreferrer">潘逸航</a> · <a href="https://github.com/May-the-first" target="_blank" rel="noopener noreferrer">陈朴凡</a> · 李金洁</span>
        <span class="project-affiliation">华南理工大学 · 2024级本科生</span>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption("数据抓取、质检、指标计算、证据式研究卡片和个性化持仓候选。任何真实交易都需要人工确认。")
st.info(
    f"五年十倍目标的数学门槛约为 {FIVE_YEAR_TEN_X_ANNUALIZED:.1%} 年化收益。"
    "本页面将其作为压力测试基准，与历史指标和风险信号对照，不代表预测或收益承诺。"
)
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
        missing_codes = {metric.code for metric in result.metrics if metric.code not in st.session_state.cards}
        if missing_codes:
            st.session_state.cards.update(
                analyze_metrics(
                    [metric for metric in result.metrics if metric.code in missing_codes],
                    [item for item in result.quality if item.code in missing_codes],
                    result.events,
                )
            )
        st.info("当前使用 GitHub Actions 最近一次后台 AI 快照；新增标的暂以离线规则基线补齐，配置 Streamlit Secrets 后可实时分析全部标的。")
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
source_rows = []
for item in result.metrics:
    status, note = source_status(item.source)
    source_rows.append({"code": item.code, "status": status, "note": note, "source": item.source})
source_frame = pd.DataFrame(source_rows)
demo_codes = [item.code for item in result.metrics if "演示数据" in item.source]
fallback_codes = [item.code for item in result.metrics if "回退" in item.source and "演示数据" not in item.source]
latest_as_of = max((item.as_of for item in result.metrics), default=None)
freshness_days = (date.today() - latest_as_of).days if latest_as_of else None
if demo_codes:
    st.error(
        "以下标的使用了随机演示数据，不能与实际基金走势比较，也不能形成可执行候选："
        + "、".join(demo_codes)
        + "。请检查网络或改用东方财富接口。"
    )
elif fallback_codes:
    st.warning("部分标的使用了真实行情回退接口：" + "、".join(fallback_codes) + "；建议核对来源和更新时间。")
else:
    st.success("当前结果全部来自真实行情接口，可进入研究流程；仍需人工核对公告原文。")
freshness_label = "暂无有效日期"
if freshness_days is not None:
    freshness_label = f"最新交易日 {latest_as_of.isoformat()}（距今天 {freshness_days} 个日历日）"
st.caption(
    f"抓取完成 {result.fetched_at} · {freshness_label} · "
    f"口径：{profile['cost_assumption']}"
)
with st.expander("查看数据来源状态"):
    if not source_frame.empty:
        source_frame = source_frame.rename(columns={"code": "代码", "status": "状态", "note": "说明", "source": "接口标签"})
        st.dataframe(source_frame, hide_index=True, width="stretch")

tab_reco, tab_metrics, tab_detail, tab_events, tab_quality = st.tabs(["个性化建议", "基金对比", "基金详情", "事件与证据", "数据质检"])

with tab_reco:
    st.subheader("候选组合")
    st.info("AI 负责统一执行数据整理、规则计算和证据结构化；使用者负责选择研究假设、风险偏好和最终行动。")
    if demo_codes:
        st.warning("当前组合含演示数据，以下候选只用于验证页面流程，不代表真实基金判断。")
    if result.recommendations:
        display = result.recommendations_frame[["role", "code", "name", "target_weight", "action", "net_return_range", "max_drawdown"]].copy()
        if demo_codes:
            display["action"] = "仅演示，不可执行"
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
            if card.goal_fit:
                st.write("**五年目标压力测试**")
                st.caption(card.goal_fit)

with tab_metrics:
    st.subheader("历史指标对比")
    frame = result.metrics_frame.copy()
    frame["goal_gap"] = frame["annualized_return"] - FIVE_YEAR_TEN_X_ANNUALIZED
    frame["goal_status"] = frame["annualized_return"].map(
        lambda value: "达到压力门槛（历史样本）" if value >= FIVE_YEAR_TEN_X_ANNUALIZED else "未达到压力门槛"
    )
    shown = frame[["code", "name", "category", "total_return", "annualized_return", "goal_gap", "goal_status", "annualized_volatility", "max_drawdown", "calmar_ratio", "quality_score", "as_of"]].copy()
    shown.columns = ["代码", "基金", "类型", "累计收益", "年化收益", "距58.5%门槛", "压力测试口径", "年化波动", "最大回撤", "收益/回撤", "质量分", "截至"]
    for column in ["累计收益", "年化收益", "年化波动", "最大回撤", "质量分"]:
        shown[column] = shown[column].map(pct)
    shown["距58.5%门槛"] = shown["距58.5%门槛"].map(pct)
    shown["收益/回撤"] = shown["收益/回撤"].map(lambda x: f"{x:.2f}")
    st.dataframe(shown, hide_index=True, width="stretch")
    st.caption("“达到压力门槛”只表示历史样本年化收益不低于五年十倍所需约 58.5%，不代表未来可重复，也不等于建议买入。")
    compare = frame.set_index("name")[["total_return", "annualized_return", "max_drawdown"]].rename(
        columns={"total_return": "累计收益", "annualized_return": "年化收益", "max_drawdown": "最大回撤"}
    )
    st.bar_chart(compare)
    selected_chart = st.selectbox("查看净值与回撤", options=list(result.histories), format_func=lambda code: profile_label(profiles[code]))
    history = result.histories[selected_chart].set_index("trade_date")
    st.line_chart(history[["close"]].rename(columns={"close": "净值/收盘价"}))
    st.line_chart(history[["drawdown"]].rename(columns={"drawdown": "回撤"}))

with tab_detail:
    st.subheader("基金详情与风险画像")
    detail_code = st.selectbox(
        "选择基金",
        options=list(result.histories),
        format_func=lambda code: profile_label(profiles[code]),
        key="detail_select",
    )
    detail_metric = next(item for item in result.metrics if item.code == detail_code)
    detail_profile = profiles[detail_code]
    detail_history = result.histories[detail_code]
    detail_col1, detail_col2, detail_col3, detail_col4 = st.columns(4)
    detail_col1.metric("最新值", as_display_number(detail_metric.latest_value))
    detail_col2.metric("年化收益", pct(detail_metric.annualized_return))
    detail_col3.metric("最大回撤", pct(detail_metric.max_drawdown))
    recovery_days = max_drawdown_recovery_days(detail_history)
    detail_col4.metric("最大回撤恢复", f"{recovery_days} 个交易日" if recovery_days is not None else "尚未恢复")
    detail_info = pd.DataFrame(
        [
            {
                "代码": detail_profile.code,
                "基金": detail_profile.name,
                "类别": detail_profile.category,
                "市场": detail_profile.market,
                "跟踪基准": detail_profile.benchmark,
                "成立日期": detail_profile.inception_date.isoformat(),
                "样本截至": detail_metric.as_of.isoformat(),
                "数据源": detail_metric.source,
                "质量分": pct(detail_metric.quality_score),
                "平均成交量（60日）": as_display_number(detail_metric.avg_volume),
            }
        ]
    )
    st.dataframe(detail_info, hide_index=True, width="stretch")
    detail_roll = rolling_returns(detail_history).set_index("trade_date")
    detail_roll.columns = ["21日滚动收益", "63日滚动收益", "252日滚动收益"]
    st.line_chart(detail_roll)
    st.caption("滚动收益用于观察不同持有期的稳定性；缺少完整窗口的前段数据会显示为空。")
    if len(result.histories) >= 2:
        close_series = {}
        for code, history_frame in result.histories.items():
            close_series[profiles[code].name] = history_frame.set_index("trade_date")["close"].pct_change()
        correlation = pd.DataFrame(close_series).corr().round(2)
        st.subheader("研究样本收益相关性")
        st.dataframe(correlation.style.format("{:.2f}"), width="stretch")
        st.caption("相关性高不等于风险低；它只说明样本期内收益变化的同步程度。")

with tab_events:
    st.subheader("自动抓取的事件线索")
    st.caption("事件线索必须回到原始公告、定期报告或监管文件核验；新闻摘要不直接作为交易依据。")
    if result.events:
        events = pd.DataFrame([event.as_dict() for event in result.events])
        report_types = {"年报", "半年报", "季报", "招募说明书/基金合同"}
        report_count = int(events["document_type"].isin(report_types).sum())
        public_count = int(events["evidence_level"].str.contains("公开披露|交易所", regex=True, na=False).sum())
        event_kpi1, event_kpi2, event_kpi3 = st.columns(3)
        event_kpi1.metric("公开信息条数", len(events))
        event_kpi2.metric("报告/合同类", report_count)
        event_kpi3.metric("公开披露来源", public_count)
        type_counts = events["document_type"].value_counts().rename("条数")
        if not type_counts.empty:
            st.bar_chart(type_counts)
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            event_codes = st.multiselect("筛选基金", options=sorted(events["code"].unique()), default=sorted(events["code"].unique()))
        with filter_col2:
            event_types = st.multiselect("筛选文档类型", options=sorted(events["document_type"].unique()), default=sorted(events["document_type"].unique()))
        events = events[events["code"].isin(event_codes) & events["document_type"].isin(event_types)]
        events = events.rename(columns={"code": "代码", "title": "标题", "publisher": "发布方", "published_at": "发布时间", "url": "链接", "source": "来源", "document_type": "文档类型", "evidence_level": "证据级别"})
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
