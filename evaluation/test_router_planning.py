"""行程规划路由专项评测。

只运行 planning=True 的用例，覆盖三类规则：
1. 需求收集短回答：planning=True，skills 必须为空；
2. 明确生成或修改行程：planning=True，必须包含 itinerary_planning；
3. 已展示完整行程后的确认定稿：planning=True，必须包含 itinerary_planning。

运行：python -m pytest evaluation/test_router_planning.py -v
"""
import pytest

from evaluation.router_cases import PLANNING_CASES, RouterCase
from evaluation.test_router import assert_chat_router_case


@pytest.mark.parametrize(
    "case",
    PLANNING_CASES,
    ids=[case.note for case in PLANNING_CASES],
)
def test_planning_router(case: RouterCase) -> None:
    """仅验证行程规划相关的路由和技能选择。"""
    assert_chat_router_case(case)
