"""判断用户这句话要干什么：要不要走规划，前端要显示哪几个技能

用 ChatTongyi.with_structured_output 直接拿到结构化结果，不用自己从文字里抠 JSON。
结果只用在两个地方：1. 发给前端的 skills 状态帧  2. 决定走不走规划 Agent
"""
from pydantic import BaseModel, Field  # BaseModel 定义模型要返回的结构；Field 的说明模型也看得到
from langchain_community.chat_models import ChatTongyi  # 千问客户端，结构化输出用它

from app.config import settings  # 模型名和 key 从配置里拿
from app.utils.logger import app_logger  # 全项目共用的日志对象

# 技能列表（就是前端 skills 帧能显示的那几种，和规划 Agent 能做的事对应）
SKILL_CATALOG = [
    "search_destination_guide(目的地攻略)", "flight_query(航班查询)",  # 括号前的英文名是技能 id，括号里是给人看的名字
    "train_query(高铁查询)", "hotel_query(酒店住宿)",  # 查高铁和酒店的技能
    "food_recommendation(美食推荐)", "weather_query(天气查询)",  # 美食和天气的技能
    "map_navigation(地图导航)", "itinerary_planning(行程规划)",  # 地图和行程规划的技能
]  # 技能目录写完了


class SelectedSkill(BaseModel):  # 模型选中的一个技能
    """前端 skills 帧里的一项（字段名和前端约定好了，不能改）"""
    skill_name: str = Field(description="技能唯一标识，取自技能目录括号前的英文名")  # 技能 id，要和目录里的英文名对上
    title: str = Field(description="技能展示标题，中文")  # 前端状态条上显示的标题
    desc: str = Field(description="一句话说明本轮用该技能做什么，中文")  # 一句话说明这轮用它干嘛


class RouterResult(BaseModel):  # 路由的完整结果，模型必须按这个结构返回
    """意图判断的结果"""
    # description 会被放进提示词里：它是写给模型看的判断规则，不是给人看的注释
    is_itinerary_planning: bool = Field(
        description="用户是否在发起、继续补充、修改或确认行程规划"
    )
    inference_log: str = Field(description="意图判断的推导过程，中文，供前端展示")  # 判断依据：排错时看模型为什么这么判
    skills: list[SelectedSkill] = Field(
        description=(
            "本轮预计执行的技能；闲聊或仅补充规划需求时为空列表；"
            "生成、修改或确认提交完整行程时包含 itinerary_planning"
        )
    )


_ROUTER_PROMPT = (  # 路由提示词，拼好放模块级，每次调用都用这一份
    "你是旅行助手的意图路由器。判断用户消息是否为行程规划请求，"  # 第一件事：判断是不是规划
    "并从技能目录中选出本轮预计用到的技能。\n"  # 第二件事：挑出要用的技能
    f"技能目录：{'、'.join(SKILL_CATALOG)}\n"  # 把技能目录塞进提示词
    "规则：1. 闲聊、问候不算行程规划，技能列表留空；"  # 闲聊不算规划，防止模型判过头
    "2. 对正在收集行程需求时的短回答（如补充目的地、人数、预算、交通或餐饮偏好），"
    "is_itinerary_planning 必须为 true，但这一步只是在补充信息，skills 必须为空；"
    "3. 用户明确要求生成或修改完整行程时，is_itinerary_planning 必须为 true，"
    "skills 必须包含 itinerary_planning；"
    "4. 用户对已经展示的完整行程表示确认、满意或要求定稿时，会触发行程提交，"
    "is_itinerary_planning 必须为 true，skills 必须包含 itinerary_planning。"
)  # 提示词拼完了


async def chat_route(content: str, history: list[str] | None = None) -> RouterResult:  # 问模型这句话要干什么，返回结构化的路由结果
    """判断意图，顺便挑出要显示的技能

    history：最近几轮对话（用户和助手都有），用户只回"确认"这种短话时，靠它接上前面的需求收集。
    以前只看这一条消息，需求收集到一半就被当成闲聊了
    """
    prompt = _ROUTER_PROMPT  # 从固定提示词开始拼
    if history:  # 带了历史才拼
        # 带上最近几条对话：这样用户只回一句"确认"，也能看出是在接着做规划
        prompt += "\n\n最近对话记录（供上下文参考）：\n" + "\n".join(history)
    prompt += f"\n\n用户消息：{content}"  # 最后放用户这句话，模型判断的就是它

    llm = ChatTongyi(  # 建千问客户端
        model=settings.qwen_model_name,  # 用配置里的模型
        api_key=settings.dashscope_api_key,  # 用配置里的 key
        temperature=0,  # 温度 0：分类要稳，同一句话别一会儿一个结果
    )  # 客户端参数配完了
    # 这一行做了四件事：把 schema 放进提示词 → 让模型按函数调用的格式返回 → 自动检查 → 变成 RouterResult
    structured = llm.with_structured_output(RouterResult)
    result = await structured.ainvoke(prompt)  # 调模型，等结构化结果回来
    # 记下判断结果，排查走错路时看这条
    app_logger.info(f"路由结果: planning={result.is_itinerary_planning}, skills={[s.skill_name for s in result.skills]}")
    return result  # 把路由结果交回去
