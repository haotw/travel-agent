"""行程质量的在线质检

把 evaluation/ 里的评测核心（Qwen 当裁判 + 三项 GEval 打分）搬成一个业务服务，两个地方用：
1. 清单存好以后在后台打分（本文件的 run_quality_check）；
2. evaluation/ 里的离线评测集也用它（评测依赖业务服务，不反过来）。

三项打分标准，都是从以前出过的问题里总结的：
- 完整性（行程正文被删减规则删没了）
- 需求匹配度（用户要文化探索，却推了游乐园）
- 真实性（编票价、编景点）
"""
import asyncio  # asyncio：丢后台任务

from deepeval.metrics import GEval  # GEval：模型按判据打分
from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # 评测用例和裁判要看的字段
from langchain_community.chat_models.tongyi import ChatTongyi  # 千问客户端，当裁判用
from langchain_core.messages import BaseMessage  # 消息基类，给类型提示用

from app.config import settings  # 模型名和 key 从配置里拿
from app.utils.logger import app_logger  # 全项目共用的日志对象
from deepeval.models import DeepEvalBaseLLM  # 自定义裁判要继承它


class QwenJudge(DeepEvalBaseLLM):  # 把千问包成 DeepEval 能用的裁判
    """用千问当 GEval 的裁判（项目里没有 OpenAI 的 key，替掉默认的 gpt-4o）"""

    def __init__(self, model_name: str | None = None):  # 构造方法，模型名可以指定
        """默认用配置里的千问模型"""
        self._model_name = model_name or settings.qwen_model_name  # 没传就用配置里的模型
        super().__init__()  # 基类初始化时会自己调 self.model = self.load_model()

    def load_model(self) -> ChatTongyi:  # DeepEval 要用时调这里取模型
        """建裁判用的模型（基类初始化时会调它）"""
        # 裁判温度设成 0：同一份行程每次打分一样
        return ChatTongyi(
            model=self._model_name,  # 模型名
            temperature=0,  # 温度 0，裁判要稳
            dashscope_api_key=settings.dashscope_api_key,  # key
        )  # 客户端参数配完了

    def generate(self, prompt: str) -> str:  # 同步打分时调
        """同步打分时 DeepEval 调这个"""
        result: BaseMessage = self.model.invoke(prompt)  # 调模型
        return result.content  # 只要文字

    async def a_generate(self, prompt: str) -> str:  # 异步打分时调
        """异步打分时 DeepEval 调这个"""
        result: BaseMessage = await self.model.ainvoke(prompt)  # 调模型
        return result.content  # 只要文字

    def get_model_name(self) -> str:  # 裁判的名字，显示在结果里
        """日志和报告里显示的裁判名字"""
        return f"qwen-judge({self._model_name})"  # 带上模型名
    # 注意不要重写 model 属性：基类 __init__ 里会执行 self.model = load_model()


# 给裁判看的：INPUT 是需求清单，ACTUAL_OUTPUT 是行程正文
_PARAMS = [LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT]


# "完整性"里"有没有预算明细"这一条，要看给裁判的是什么材料
# 预算明细只在聊天里那段 Markdown 正文里有（summarize_budget_tool / _build_budget 拼的），
# 存进数据库的清单 TravelItinerary 只有 title 和 itinerary_list，没有预算。
# 离线评测给的是 Markdown 正文（带预算表），这条判据成立；
# 在线质检给的是 plan_to_text 转出来的清单（没有预算），这条永远不满足，每次都会被扣分。
# 所以用一个开关明确告诉它，不让裁判自己去猜"这段文字里有没有预算"
_BUDGET_CLAUSE = ("2) 正文末尾附有预算明细（交通/住宿/餐饮/门票等构成）。缺任一项即扣分。")  # 离线：材料是带预算表的正文
_BUDGET_CLAUSE_NA = ("《本条不适用》当前待判内容为结构化行程清单，本身不含预算明细，"  # 在线：材料是没有预算的清单
                     # 判据接上一行
                     "因此不得因缺少预算而扣分；只需判断第 1 项（天数与上午/下午/晚上时段）是否完整。")

# 造三项打分：完整性、需求匹配度、真实性
def build_itinerary_metrics(threshold: float = 0.5, require_budget: bool = True) -> list[GEval]:
    """建三项 GEval 打分（每次新建，免得 DeepEval 内部状态互相影响）

    require_budget：给裁判的材料里有没有预算明细
    - True（默认）：材料是模型输出的 Markdown 正文，带预算表，要认真查预算是否完整（离线评测用）
    - False：材料是 plan_to_text 转出来的清单，没有预算，这一条不适用，不扣分（在线质检用）
    """
    judge = QwenJudge()  # 每次都新建，免得 DeepEval 内部状态互相影响
    # 时段要和代码拼出来的正文对上：_render_itinerary_body 拼的是
    # 上午 / 中午 / 下午 / 晚上四个时段，加每天的小贴士。以前的判据只写了三个时段，
    # 和实际内容对不上；最后一天返程之后的时段是空的（人已经走了），不能因为这个判成不完整
    completeness = ("判断行程正文是否完整：1) 每天都有『Day X』标题，且当天包含上午/中午/"
                    # 判据接上一行
                    "下午/晚上四个时段（交通日按城际班次的时刻排：出发之前、在车上、返程之后的时段没有安排属于正常，写着「乘「车次 A→B」」的那一条就是城际交通，都不算缺项），"
                    "天数覆盖需求里的全部出行天数；"  # 判据接上一行
                    + (_BUDGET_CLAUSE if require_budget else _BUDGET_CLAUSE_NA))  # 用一个开关切换两版判据
    return [  # 返回三项指标
        GEval(name="行程完整性",  # 第一项：行程完整性
              criteria=completeness,  # 判据
              evaluation_params=_PARAMS, model=judge, threshold=threshold),  # 裁判看的字段、用哪个模型、及格线
        GEval(name="需求匹配度",  # 第二项：需求匹配度
              # 判据：对照需求清单
              criteria=("对照需求清单判断行程是否匹配：目的地正确；每天行程数量与出行天数一致；"
                        "交通方式与需求一致；行程设计体现旅行风格；按人数与预算给出合理的"  # 判据接上一行
                        "餐饮住宿档次。明显偏离即扣分。"),  # 判据接上一行
              evaluation_params=_PARAMS, model=judge, threshold=threshold),  # 裁判看的字段、用哪个模型、及格线
        GEval(name="真实性（无编造）",  # 第三项：有没有编造
              # 判据：景点餐厅要真实
              criteria=("判断行程中的景点、餐厅、门票价格是否真实可信：景点应为目的地真实存在"
                        "的知名景点；餐厅应为当地真实特色；门票价格应与常识一致（如灵隐寺约"  # 判据接上一行
                        " 30 元），不应出现明显虚构的名称或离谱价格。发现编造嫌疑即扣分。"),  # 判据接上一行
              evaluation_params=_PARAMS, model=judge, threshold=threshold),  # 裁判看的字段、用哪个模型、及格线
    ]  # 列表写完了

# ============ 在线质检：清单存好以后在后台打分，只记日志告警，不影响主流程 ============

# 后台任务要自己存一份引用，不然 create_task 出来的任务可能被垃圾回收掉
_BG_TASKS: set = set()


def plan_to_text(plan_data: dict) -> str:  # 把清单转成文字，给裁判看
    """把存在数据库里的清单 JSON 转回一段裁判能读的行程文字（尽量和模型输出的样子一致）"""
    lines: list[str] = [plan_data.get("title", "行程")]  # 第一行是标题
    for day in plan_data.get("itinerary_list", []):  # 三层：itinerary_list → itinerary → scenic_spots_list
        lines.append(f"\n{day.get('day', '')}：")  # 每天的小标题
        for item in day.get("itinerary", []):  # 每个时段
            spots = item.get("scenic_spots_list", [])  # 这个时段的条目
            parts = [  # 拼成"景点（说明）"
                f"{s.get('toponym', '')}（{str(s.get('toponym_desc', ''))[:60]}）"  # 说明只取前 60 个字
                for s in spots  # 每个条目
            ]  # 列表写完了
            lines.append(f"{item.get('time', '')}：{'、'.join(parts)}")  # 写一行
    return "\n".join(lines)  # 拼成完整文字


# 跑一次在线质检：只告警，不拦截
async def run_quality_check(plan_data: dict, threshold: float = 0.5, confirmed: str = "") -> None:
    """给一份存好的行程打三项分：通过记 INFO，不通过记 WARNING 和裁判给的理由

    只是事后告警：行程已经发给用户了，质检不会重新生成，也不会拦住什么。
    出了任何错都吞掉，不能影响对话

    confirmed：正文开头代码写的"已确认的交通与住宿"，是裁判的对照基准。以前只给标题，而标题是从行程本身取的城市：
    多了一座没订票的石家庄，标题里也有，裁判照样打 0.9；北京出发的车又被判成"额外添加的北京段"
    """
    title = plan_data.get("title", "未命名行程")  # 取标题
    try:  # 出任何错都吞掉，不能影响用户
        case = LLMTestCase(  # 建评测用例
            input=f"{title}\n{confirmed}".strip(),  # 输入：标题和已确认的内容
            actual_output=plan_to_text(plan_data),  # 实际输出：清单转成的文字
        )  # 用例写完了
        scores: dict[str, float] = {}  # 每项的分数
        reasons: list[str] = []  # 不及格的理由
        all_reasons: list[str] = []  # 全部理由
        # 在线质检拿到的是 plan_to_text 转出来的清单（没有预算），
        # 所以 require_budget=False，不然"完整性"每次都因为缺预算被扣分，刷出一堆没用的告警
        for metric in build_itinerary_metrics(threshold=threshold, require_budget=False):
            await metric.a_measure(case)  # 裁判打分
            scores[metric.name] = metric.score  # 记分数
            # 每一项的裁判理由都记下来，通过的也记（方便看分数为什么波动）
            all_reasons.append(f"{metric.name}: {metric.reason}")
            if metric.score < threshold:  # 低于及格线
                reasons.append(f"{metric.name}: {metric.reason}")  # 记下理由

        low = {k: v for k, v in scores.items() if v < threshold}  # 挑出不及格的
        if low:  # 有不及格的
            app_logger.warning(  # 记警告
                f"⚠️ 行程质检未达标: {title} | 分数: {scores} | 问题: {'；'.join(reasons)}"  # 分数和问题
            )  # 日志写完了
        else:  # 都及格
            # 通过时也带上裁判理由（截短一点，免得日志太长），哪一项分低能查到原因
            brief = "；".join(all_reasons)
            if len(brief) > 500:  # 理由太长
                brief = brief[:500] + "……"  # 截断
            app_logger.info(f"✅ 行程质检通过: {title} | 分数: {scores} | 理由: {brief}")  # 记一条
    except Exception as e:  # 质检本身出错了
        # 质检自己出错（网络、限流、解析失败）只记一下，不影响业务
        app_logger.warning(f"行程质检执行异常（已忽略）: {title} | {type(e).__name__}: {e}")


def schedule_quality_check(plan_data: dict, confirmed: str = "") -> None:  # 把质检丢到后台跑，用户不用等
    """清单存好以后调：起一个后台任务去打分，不耽误回复"""
    task = asyncio.create_task(run_quality_check(plan_data, confirmed=confirmed))  # 起一个后台任务，马上返回
    _BG_TASKS.add(task)  # 自己留一份引用，防止被回收
    task.add_done_callback(_BG_TASKS.discard)  # 任务结束时把引用删掉