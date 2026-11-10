"""验证路由评测的打分规则：planning 必须对、技能三种查法、返回的不是 JSON 直接 0 分（纯逻辑，不调模型；需要 deepeval 装好）"""
import json  # json：JSON 和 Python 对象互相转换
import os  # os：拼路径、读环境变量都靠它
import sys  # sys：改 sys.path、拿 stdout 都靠它
from collections import Counter  # Counter 计数器，数每样有几个
from pathlib import Path  # Path 面向对象的路径操作
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # 往上跳两级到项目根，项目里的模块才 import 得到
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")      # 和 evaluation/conftest.py 一样，先关遥测

from deepeval.test_case import LLMTestCase  # 一条评测用例

from app.utils.logger import app_logger  # 全项目共用的日志对象
from evaluation.router_cases import CASES  # 从 evaluation.router_cases 拿 CASES
from evaluation.router_metric import RouterCorrectnessMetric  # 路由指标


def _out(planning: bool, *skills: str) -> str:  # 定义函数 _out：收 planning、*skills，返回 str
    """拼一份路由结果：和 test_router.py 序列化出来的是同一个形状"""
    # 返回 把 一个字典 转成 JSON 文本
    return json.dumps({"is_itinerary_planning": planning, "skills": [{"skill_name": s} for s in skills]}, ensure_ascii=False)


# (说明, 指标的期望, 假装路由返回了什么)
TRIALS = [
    ("闲聊判对了", {"expected_planning": False, "expect_empty_skills": True}, _out(False)),  # 一组：「闲聊判对了」、一个字典、_out 的结果
    # 一组：「闲聊却带了技能」、一个字典、_out 的结果
    ("闲聊却带了技能", {"expected_planning": False, "expect_empty_skills": True}, _out(False, "weather_query")),
    ("短回答被当成闲聊", {"expected_planning": True}, _out(False)),  # 一组：「短回答被当成闲聊」、一个字典、_out 的结果
    # 一组：「单项查询命中一个就算」、一个字典、_out 的结果
    ("单项查询命中一个就算", {"expected_planning": False, "expected_skills_any": ["train_query"]}, _out(False, "train_query", "map_navigation")),
    # 一组：「单项查询一个没命中」、一个字典、_out 的结果
    ("单项查询一个没命中", {"expected_planning": False, "expected_skills_any": ["train_query"]}, _out(False, "flight_query")),
    ("路由返回的不是 JSON", {"expected_planning": True}, "抱歉，我没理解"),  # 一组：「路由返回的不是 JSON」、一个字典、「抱歉，我没理解」
]  # 列表写完了


def main() -> None:  # 定义函数 main：不用传参，不返回值
    """先看用例集怎么分组，再拿几份假结果过一遍打分"""
    # 建一个 Counter 对象，存到 groups
    groups = Counter("闲聊" if c.expect_empty_skills else ("规划" if c.planning else "单项查询") for c in CASES)
    # 记一条日志：用例 … 条：…带历史的 … 条
    app_logger.info("用例 {} 条：{}；带历史的 {} 条", len(CASES), dict(groups), sum(bool(c.history) for c in CASES))
    for label, expect, actual in TRIALS:  # 挨个遍历 TRIALS，每次拿到 label、expect、actual
        metric = RouterCorrectnessMetric(**expect)  # 建一个 RouterCorrectnessMetric 对象，存到 metric
        metric.measure(LLMTestCase(input="（演示）", actual_output=actual))  # 调 metric.measure
        # 记一条日志：…：score… 通过… 理由：…
        app_logger.info("{}：score={} 通过={} 理由：{}", label, metric.score, metric.is_successful(), metric.reason)
    try:  # 下面这段可能出错，先兜着
        # 建 RouterCorrectnessMetric
        RouterCorrectnessMetric(expected_planning=False, expected_skills_any=["x"], expect_empty_skills=True)
    except ValueError as e:  # ValueError 报错走这里，错误对象叫 e
        app_logger.info("两种技能要求同时给：{}", type(e).__name__)  # 记一条日志：两种技能要求同时给：…


if __name__ == "__main__":  # 直接运行这个文件才走这里，被 import 时不走
    # 脚本输出要每次一样：去掉时间戳和颜色，只留级别、模块名和消息
    app_logger.remove()
    app_logger.add(sys.stdout, format="{level} | {name} | {message}")  # 只留级别、模块名和消息，输出才对得上课件
    main()  # 跑主函数