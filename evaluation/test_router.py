"""
意图路由评测入口
两种运行方式任选：
- uv run pytest evaluation/test_router.py -v        # 原生pytest执行
- deepeval test run evaluation/test_router.py      # DeepEval CLI，结果可以上传Confident平台

逻辑：遍历所有测试用例，调用真实的 chat_route 路由函数。
把返回的强类型RouterResult转成JSON字符串，交给自定义指标做固定规则校验。
"""
import asyncio  # asyncio：跑异步的路由
import json  # json：把结果转成文本
import os  # os：判断操作系统

# Windows环境下异步客户端需要Selector事件循环，和项目app/run.py保持一致
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # Windows 要换事件循环

from deepeval import assert_test  # 跑指标并断言
from deepeval.test_case import LLMTestCase  # 一条评测用例
import pytest  # 测试框架
from app.agents.routers.chat_router import chat_route  # 真正被测的路由
from evaluation.router_cases import CASES, RouterCase  # 路由用例
from evaluation.router_metric import RouterCorrectnessMetric  # 路由指标


def assert_chat_router_case(case: RouterCase) -> None:
    """调用真实路由并按用例断言，供完整评测和规划专项评测复用。"""
    # 执行路由函数，async方法用asyncio.run转为同步调用；history用于对话上下文接续
    result = asyncio.run(chat_route(case.msg, history=case.history or None))

    # 将路由返回对象序列化JSON，作为deepeval测试的实际输出
    actual_output = json.dumps({
        "is_itinerary_planning": result.is_itinerary_planning,  # 是否规划
        "skills": [s.model_dump() for s in result.skills],  # 命中的技能
    }, ensure_ascii=False)  # 转成 JSON 文本

    test_case = LLMTestCase(  # 建评测用例
        input=case.msg,  # 输入和线上一样
        actual_output=actual_output,  # 实际输出
    )  # 用例写完了

    # 初始化自定义校验指标，必须全部匹配才能通过
    metric = RouterCorrectnessMetric(
        expected_planning=case.planning,  # 期望走不走规划
        expected_skills_any=case.skills,  # 期望命中的技能
        expect_empty_skills=case.expect_empty_skills,  # 期望技能为空
    )  # 指标写完了
    metric.threshold = 1.0  # 分类只有对错，及格线设成 1
    assert_test(test_case, [metric])  # 打分，不及格测试就失败


@pytest.mark.parametrize("case", CASES, ids=[c.note for c in CASES])  # 每条用例跑一遍，名字用备注
def test_chat_router(case: RouterCase):  # 一条路由评测
    """单条路由测试：调用真实路由，校验planning和skills结果"""
    assert_chat_router_case(case)
