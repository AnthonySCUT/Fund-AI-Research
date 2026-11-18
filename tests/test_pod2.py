"""Offline Pod2 regressions: malformed providers and snapshot reuse."""
from dataclasses import asdict
from datetime import date
import json
import os
from unittest.mock import patch

import pytest

from fund_ai_research.analysis import OpenAICompatibleAnalyzer, analyze_metrics
from fund_ai_research.analytics import calculate_metrics, validate_history
from fund_ai_research.connectors import DEFAULT_FUNDS, DemoConnector
from fund_ai_research.incremental import fingerprints_for_records, fingerprints_for_snapshot


def inputs():
    profile = DEFAULT_FUNDS[0]
    history = DemoConnector().fetch_history(profile.code, date(2025, 1, 1), date(2026, 1, 1))
    quality = validate_history(history, profile.code)
    metric = calculate_metrics(history, profile.code, profile.name, profile.category, quality, 'demo')
    return metric, quality


def valid_card():
    return dict(code='510300', status='黄灯', facts=['输入事实'], positive_evidence=[],
                risk_signals=[], verification_questions=['核查原文'], conclusion='等待核验')


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return {'choices': [{'message': {'content': json.dumps(self.payload)}}]}


@pytest.mark.parametrize('payload', [[], None, {'cards': None}, {'cards': [None]},
    {'cards': [dict(valid_card(), status='买入')]},
    {'cards': [dict(valid_card(), facts='不是数组')]},
    {'cards': [dict(valid_card(), facts=[{}])]},
    {'cards': [dict(valid_card(), conclusion=None)]},
    {'cards': [dict(valid_card(), code='other')]},
    {'cards': [valid_card(), valid_card()]}])
def test_invalid_primary_output_falls_back(payload):
    metric, quality = inputs()
    with patch.dict(os.environ, {'GROK_API_KEY': 'test', 'DEEPSEEK_API_KEY': 'test'}), patch(
        'fund_ai_research.analysis.requests.post', side_effect=[Response(payload), Response({'cards': [valid_card()]})]
    ) as post:
        cards = analyze_metrics([metric], [quality], [])
    assert cards[metric.code].source.startswith('Deepseek:')
    assert post.call_count == 2


def test_both_malformed_providers_use_rule_baseline():
    metric, quality = inputs()
    with patch.dict(os.environ, {'GROK_API_KEY': 'test', 'DEEPSEEK_API_KEY': 'test'}), patch(
        'fund_ai_research.analysis.requests.post', return_value=Response({'cards': [None]})
    ):
        assert analyze_metrics([metric], [quality], [])[metric.code].source == '规则化基线'


@pytest.mark.parametrize('payload', [None, [], dict(valid_card(), facts=1)])
def test_single_analyzer_handles_malformed_output(payload):
    metric, quality = inputs()
    with patch('fund_ai_research.analysis.requests.post', return_value=Response(payload)):
        assert OpenAICompatibleAnalyzer(api_key='test').analyze(metric, quality, []) is None


@pytest.mark.parametrize('warnings', [[], ['字段缺失', '请核查']])
def test_snapshot_quality_shape_preserves_fingerprint(warnings):
    metric, quality = inputs()
    quality.warnings = warnings
    row = asdict(quality)
    row['warnings'] = '；'.join(warnings) or '无'
    row['status'] = quality.status
    # Match the date serialization in the scheduled JSON writer.
    snapshot = json.loads(json.dumps(dict(metrics=[metric.as_dict()], quality=[row], events=[]), default=str))
    assert fingerprints_for_records([metric], [quality], []) == fingerprints_for_snapshot(snapshot)
    snapshot['quality'][0]['warnings'] = '新增警告'
    assert fingerprints_for_records([metric], [quality], []) != fingerprints_for_snapshot(snapshot)
