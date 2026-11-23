import pytest

from fund_ai_research.presentation import concise_source_label


@pytest.mark.parametrize(("source", "expected"), [
    ("Yahoo Finance public chart（交叉校验未完成）", "Yahoo Finance public chart"),
    ("演示数据(备用源不可用且主源待核实回退)", "演示数据"),
])
def test_source_label_hides_parenthetical_notes(source, expected):
    assert concise_source_label(source) == expected
