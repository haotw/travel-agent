"""
状态转换工具（Handoffs 中的状态跳转 & 数据记录工具）

本章追加：目的地/交通/住宿/餐饮/行程/预算 共 6 把新工具。
第 05 章还会继续补：回退工具 + 长期记忆工具。
"""
from datetime import datetime, timedelta
from typing import Optional, Literal 

from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.core.state import (
    TravelState,
    UserRequirement,
    ItineraryDay,
    BudgetBreakdown,
)
from app.utils.logger import app_logger


# ============== 1️⃣ 需求收集工具（第 03 章代码保持不变，此处省略以便聚焦） ==============
# 见上一章的完整实现，本章不改动它
# ------------------------------------------------------------------------

@tool
def record_requirement_tool(
        departure_city: str,
        departure_date: str,
        travel_days: int,
        budget_min: float,
        budget_max: float,
        travel_styles: list[str],
        special_needs: str = "",
        adult_count: Optional[int] = 1,
        children_count: Optional[int] = 0,
        destination: Optional[str] = None,
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """记录用户旅行需求，并进入目的地推荐步骤。
    (docstring 与第 03 章一致，此处压缩)
    """
    # ↓↓↓ 与第 03 章完全一致，不再重复注释 ↓↓↓
    try:
        datetime.strptime(departure_date, "%Y-%m-%d")
    except ValueError:
        return Command(update={"messages": [ToolMessage(
            content="❌ 日期格式错误，请使用 YYYY-MM-DD 格式",
            tool_call_id=runtime.tool_call_id
        )]})

    avg_budget = (budget_min + budget_max) / 2
    if avg_budget < 3000:
        budget_level = "economy"
    elif avg_budget < 8000:
        budget_level = "comfort"
    else:
        budget_level = "luxury"

    requirement = UserRequirement(
        departure_city=departure_city,
        destination=destination,
        departure_date=departure_date,
        travel_days=travel_days,
        adult_count=adult_count,
        children_count=children_count,
        budget_min=budget_min,
        budget_max=budget_max,
        budget_level=budget_level,
        travel_styles=travel_styles,
        special_needs=special_needs if special_needs else None,
    )
    app_logger.info(f"[STEP] 需求已记录 → destination_recommendation")
    return Command(update={
        "messages": [ToolMessage(
            content=(f"✅ 需求已记录！\n出发：{departure_city} → 目的地：{destination or '待推荐'}\n"
                     f"{travel_days} 天 | 预算 {budget_min}-{budget_max} 元/人（{budget_level}）"),
            tool_call_id=runtime.tool_call_id
        )],
        "user_requirement": requirement,
        "current_step": "destination_recommendation",
    })


# ============== 2️⃣ 目的地选择工具 ==============

@tool
def select_destination_tool(
        destination: str,
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    确认用户选择的目的地，进入交通规划步骤。

    参数：
    - destination: 目的地名称。单目的地如 "西安"；多目的地按游览顺序用顿号连接，
      如 "杭州、深圳"（多城串联时必须传完整城市串）

    调用时机：
    - 用户明确说出选定的目的地后
    - 严禁在用户还没做出选择时就调用（那是自己替用户做主）
    """
    app_logger.info(f"[STEP] 用户选择目的地: {destination} → transport_planning")

    return Command(update={
        "messages": [ToolMessage(
            content=f"✅ 目的地已确认：{destination}",
            tool_call_id=runtime.tool_call_id
        )],
        "selected_destination": destination,
        "current_step": "transport_planning",
    })


# ============== 3️⃣ 交通方式选择工具 ==============

@tool
def select_transport_tool(
        transport_type: str,   # "flight" | "train" | "driving"
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    确认用户选择的交通方式，进入住宿规划步骤。

    参数：
    - transport_type: 交通方式，可选值：
        * "flight"   （航班）
        * "train"    （高铁/火车）
        * "driving"  （自驾）

    调用时机：
    - 用户明确回复选择哪种方式后
    """
    if transport_type not in ("flight", "train", "driving"):
        return Command(update={"messages": [ToolMessage(
            content="❌ 交通方式无效，请传 flight / train / driving 之一",
            tool_call_id=runtime.tool_call_id
        )]})

    app_logger.info(f"[STEP] 用户选择交通: {transport_type} → accommodation_planning")

    return Command(update={
        "messages": [ToolMessage(
            content=f"✅ 交通方式已确认：{transport_type}",
            tool_call_id=runtime.tool_call_id
        )],
        "selected_transport": transport_type,
        "current_step": "accommodation_planning",
    })


# ============== 4️⃣ 住宿类型选择工具 ==============

@tool
def select_accommodation_tool(
        accommodation_types: list[str],
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    确认用户选择的住宿类型，进入餐饮规划步骤。

    参数：
    - accommodation_types: 住宿类型列表（可多选），可选值：
        * "star_hotel"     （星级酒店）
        * "economy_hotel"  （经济酒店）
        * "hostel"         （民宿）
        * "youth_hostel"   （青年旅社）

    调用时机：
    - 用户明确表达住宿偏好并要求推进后
    """
    valid = {"star_hotel", "economy_hotel", "hostel", "youth_hostel"}
    bad = [x for x in accommodation_types if x not in valid]
    if bad:
        return Command(update={"messages": [ToolMessage(
            content=f"❌ 无效住宿类型: {bad}；可选值 {sorted(valid)}",
            tool_call_id=runtime.tool_call_id
        )]})

    app_logger.info(f"[STEP] 用户选择住宿: {accommodation_types} → food_planning")

    return Command(update={
        "messages": [ToolMessage(
            content=f"✅ 住宿偏好已确认：{', '.join(accommodation_types)}",
            tool_call_id=runtime.tool_call_id
        )],
        "selected_accommodation_types": accommodation_types,
        "current_step": "food_planning",
    })


# ============== 5️⃣ 餐饮类型选择工具 ==============

@tool
def select_food_tool(
        food_types: list[str],
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    确认用户选择的餐饮类型，进入行程生成步骤。

    参数：
    - food_types: 餐饮类型列表（可多选），可选值：
        * "specialty"  （特色美食）
        * "chain"      （连锁快餐）
        * "local"      （本地小吃）
    """
    valid = {"specialty", "chain", "local"}
    bad = [x for x in food_types if x not in valid]
    if bad:
        return Command(update={"messages": [ToolMessage(
            content=f"❌ 无效餐饮类型: {bad}；可选值 {sorted(valid)}",
            tool_call_id=runtime.tool_call_id
        )]})

    app_logger.info(f"[STEP] 用户选择餐饮: {food_types} → itinerary_generation")

    return Command(update={
        "messages": [ToolMessage(
            content=f"✅ 餐饮偏好已确认:{', '.join(food_types)}",
            tool_call_id=runtime.tool_call_id
        )],
        "selected_food_types": food_types,
        "current_step": "itinerary_generation",
    })


# ============== 6️⃣ 行程生成工具（骨架版） ==============

@tool
def generate_itinerary_tool(
        activities_by_day: list[list[str]],
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    落库逐日行程，进入预算汇总步骤。

    参数：
    - activities_by_day: 二维列表，外层长度 = 天数，
      内层每一项是该天的活动列表。
      例如 3 天：
        [
          ["黄鹤楼", "汉口江滩", "户部巷小吃"],
          ["东湖磨山", "湖北省博物馆"],
          ["武汉大学", "光谷步行街"]
        ]

    调用时机：
    - 用户对目的地、交通、住宿、餐饮全部确认完毕
    - 模型基于选定的目的地和天数拟出每日活动后
    """
    state = runtime.state
    req = state.get("user_requirement") or {}
    travel_days = int(req.get("travel_days") or 0)
    destination = state.get("selected_destination") or req.get("destination") or ""

    # 校验：activities_by_day 长度必须与旅行天数匹配
    if len(activities_by_day) != travel_days:
        return Command(update={"messages": [ToolMessage(
            content=(f"❌ 行程天数不匹配：需求是 {travel_days} 天，"
                     f"但你只给了 {len(activities_by_day)} 天的活动"),
            tool_call_id=runtime.tool_call_id
        )]})

    # 构造结构化行程（ItineraryDay 是第 02 章定义的 TypedDict）
    itinerary: list[ItineraryDay] = []
    for i, day_activities in enumerate(activities_by_day, start=1):
        itinerary.append(ItineraryDay(
            day_number=i,
            activities=day_activities,
            meals=[],           # 骨架版不细化到每餐，第 08 章交给 capabilities 出
            accommodation="",   # 骨架版不细化到每晚住哪，同上
        ))

    app_logger.info(
        f"[STEP] 行程已生成: {destination} · {travel_days} 天 → budget_summarization"
    )

    return Command(update={
        "messages": [ToolMessage(
            content=f"✅ 已生成 {travel_days} 天行程，共 {sum(len(x) for x in activities_by_day)} 项活动",
            tool_call_id=runtime.tool_call_id
        )],
        "itinerary": itinerary,
        "current_step": "budget_summarization",
    })


# ============== 7️⃣ 预算汇总工具（骨架版） ==============

@tool
def summarize_budget_tool(
        transport_cost: float,     # 交通（元/人/全程）
        accommodation_cost: float, # 住宿（元/人/全程）
        food_cost: float,          # 餐饮（元/人/全程）
        attractions_cost: float,   # 景点门票（元/人/全程）
        misc_cost: float = 0.0,    # 其他（元/人/全程）
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    汇总预算，进入报告生成步骤（最终步）。

    参数说明（全部按"每人全程"口径填）：
    - transport_cost: 交通费（含所有城际段）
    - accommodation_cost: 住宿费（全部晚数合计）
    - food_cost: 餐饮费
    - attractions_cost: 景点门票
    - misc_cost: 其他（保险、装备等，可缺省）

    调用时机：
    - 行程已经生成（itinerary 字段非空）
    - 模型基于选定的目的地/交通/住宿/餐饮档位估算出各项费用后
    """
    total = (transport_cost + accommodation_cost +
             food_cost + attractions_cost + misc_cost)

    budget = BudgetBreakdown(
        transport=transport_cost,
        accommodation=accommodation_cost,
        food=food_cost,
        attractions=attractions_cost,
        misc=misc_cost,
        total=total,
    )

    # 与需求预算做个简单对比
    req = runtime.state.get("user_requirement") or {}
    b_min = float(req.get("budget_min") or 0)
    b_max = float(req.get("budget_max") or 0)
    overrun_note = ""
    if b_max and total > b_max:
        overrun_note = f"（超出预算上限 {total - b_max:.0f} 元）"
    elif b_min and total < b_min:
        overrun_note = f"（低于预算下限 {b_min - total:.0f} 元）"

    app_logger.info(
        f"[STEP] 预算已汇总: {total:.0f} 元/人 {overrun_note} → report_generation"
    )

    return Command(update={
        "messages": [ToolMessage(
            content=(f"✅ 预算已汇总（人均全程）：\n"
                     f"  交通 {transport_cost:.0f} + 住宿 {accommodation_cost:.0f} + "
                     f"餐饮 {food_cost:.0f} + 景点 {attractions_cost:.0f} + "
                     f"其他 {misc_cost:.0f}\n"
                     f"  合计 {total:.0f} 元/人 {overrun_note}"),
            tool_call_id=runtime.tool_call_id
        )],
        "budget": budget,
        "current_step": "report_generation",
    })




# ============== 回退工具 ==============
# 全部流程步骤
ALL_STEPS = [
    "requirement_collection",       # 步骤1：需求收集
    "destination_recommendation",   # 步骤2：目的地推荐
    "transport_planning",           # 步骤3：交通规划
    "accommodation_planning",       # 步骤4：住宿规划
    "food_planning",                # 步骤5：餐饮规划
    "itinerary_generation",         # 步骤6：行程生成
    "budget_summarization",         # 步骤7：预算汇总
    "report_generation"              # 步骤8：报告生成
]

# 步骤-中文名称映射
STEP_LABELS = {
    "requirement_collection": "需求收集",
    "destination_recommendation": "目的地推荐",
    "transport_planning": "交通规划",
    "accommodation_planning": "住宿规划",
    "food_planning": "餐饮规划",
    "itinerary_generation": "行程生成",
    "budget_summarization": "预算汇总",
    "report_generation": "报告生成"
}

# 各步骤对应的状态字段，执行回退时级联清除
STEP_STATE_FIELDS = {
    "requirement_collection": ["user_requirement"],
    "destination_recommendation": ["selected_destination", "destination_options"],
    "transport_planning": [
        "selected_transport", "transport_options",
        "selected_transport_legs", "leg_cursor", "leg_selections", "leg_prices",
    ],
    "accommodation_planning": [
        "selected_accommodation_types", "accommodation_options",
        "selected_hotels", "stay_cursor", "stay_prices",
    ],
    "food_planning": ["selected_food_types", "food_options"],
    "itinerary_generation": ["itinerary", "itinerary_body"],
    "budget_summarization": ["budget"],
    "report_generation": ["report"]
}

# ============== 通用回退工具 ==============

@tool
def go_back_to_step(
        target_step: Literal[
            "requirement_collection",
            "destination_recommendation",
            "transport_planning",
            "accommodation_planning",
            "food_planning",
            "itinerary_generation",
            "budget_summarization"
        ],
        reason: str,
        clear_subsequent_data: bool = True,
        runtime: ToolRuntime = None
) -> Command:
    """
    回退到指定的历史步骤，允许用户重新进行规划。

    使用场景示例：
    - 用户说"我想重新选择目的地" -> target_step="destination_recommendation"
    - 用户说"我想重新制定旅行计划" -> target_step="requirement_collection"
    - 用户说"换个交通方式" -> target_step="transport_planning"
    - 用户说"住宿要求改一下" -> target_step="accommodation_planning"
    - 用户说"餐饮偏好不对" -> target_step="food_planning"
    - 用户说"行程安排需要调整" -> target_step="itinerary_generation"
    - 用户说"预算超了，重新算" -> target_step="budget_summarization"

    参数说明：
    - target_step: 要回退到的目标步骤
        * "requirement_collection" - 重新收集旅行需求（出发日期、人数、预算等）
        * "destination_recommendation" - 重新选择目的地
        * "transport_planning" - 重新选择交通方式（航班/高铁/自驾）
        * "accommodation_planning" - 重新选择住宿类型
        * "food_planning" - 重新选择餐饮偏好
        * "itinerary_generation" - 重新生成行程安排
        * "budget_summarization" - 重新计算预算

    - reason: 回退原因，用于记录和展示给用户
        示例："用户希望更换目的地为三亚"
        示例："预算超出用户预期，需要调整住宿标准"

    - clear_subsequent_data: 是否清除目标步骤之后的所有数据（默认 True）
        * True: 回退时清除后续步骤产生的选择和数据
        * False: 保留后续数据（谨慎使用，可能导致数据不一致）

    返回：
        Command 对象，包含状态更新和步骤跳转指令

    注意：
    - 不能回退到 "report_generation"（报告生成是最终步骤）
    - 回退会在消息历史中记录，方便追溯
    """

    app_logger.info(f"回退请求: target_step={target_step}, reason={reason}, clear_data={clear_subsequent_data}")

    # 验证目标步骤
    if target_step not in ALL_STEPS:
        app_logger.warning(f"无效的目标步骤: {target_step}")
        return Command(update={
            "messages": [
                ToolMessage(
                    content=f"无效的目标步骤: {target_step}",
                    tool_call_id=runtime.tool_call_id
                )
            ]
        })

    # 不允许回退到报告生成（最终步骤）
    # ★ 终态明确拒绝，不靠默认参数偷偷放行
    if target_step == "report_generation":
        app_logger.warning("尝试回退到报告生成步骤，已拒绝")
        return Command(update={
            "messages": [
                ToolMessage(
                    content="报告生成是最终步骤，无法回退到此步骤。如需修改，请回退到更早的步骤。",
                    tool_call_id=runtime.tool_call_id
                )
            ]
        })

    # 获取当前步骤（用于日志）
    current_step = runtime.state.get("current_step", "unknown") if runtime.state else "unknown"
    app_logger.info(f"执行回退: {current_step} -> {target_step}")

    # 构建状态更新
    state_update = {
        "current_step": target_step
    }

    # 如果需要清除后续数据
    cleared_fields = []
    if clear_subsequent_data:
        # 级联清除：目标步及之后每一步登记的字段全部置 None。
        # 当前先与课程代码保持一致；itinerary / budget 的 reducer 清空问题
        # 等后续章节按老师给出的方案统一处理。
        target_index = ALL_STEPS.index(target_step)
        for step in ALL_STEPS[target_index:]:
            for field in STEP_STATE_FIELDS.get(step, []):
                state_update[field] = None
                cleared_fields.append(field)

        if cleared_fields:
            app_logger.debug(f"清除的状态字段: {cleared_fields}")

    # 获取步骤标签
    step_label = STEP_LABELS.get(target_step, target_step)

    # 构建响应消息
    response_parts = [
        f"已回退到【{step_label}】阶段",
        f"原因: {reason}"
    ]
    if clear_subsequent_data and cleared_fields:
        response_parts.append("已清除后续步骤的数据")

    state_update["messages"] = [
        ToolMessage(
            content="\n".join(response_parts),
            tool_call_id=runtime.tool_call_id
        )
    ]

    app_logger.info(f"回退完成: {target_step}, 清除字段数: {len(cleared_fields)}")

    return Command(update=state_update)



# ============== 快捷回退工具 ==============

@tool
def go_back_to_requirement(
        reason: str = "用户希望重新规划",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到需求收集步骤，重新开始规划。

    使用场景：
    - 用户说"我想重新规划"
    - 用户说"出发日期要改"
    - 用户说"预算变了"
    - 用户说"人数不对"
    - 用户说"从头开始"

    效果：
    - 清除所有已收集的数据
    - 返回到最初的需求收集阶段
    """
    app_logger.info(f"[快捷回退→需求] {reason}")
    return go_back_to_step.invoke({
        "target_step": "requirement_collection",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })


@tool
def go_back_to_destination(
        reason: str = "用户希望更换目的地",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到目的地推荐步骤。

    使用场景：
    - 用户说"换个目的地"
    - 用户说"这个地方不想去了"
    - 用户说"有没有其他推荐"
    - 用户说"目的地选错了"

    效果：
    - 保留用户需求
    - 清除目的地及后续所有数据
    """
    app_logger.info(f"[快捷回退→目的地] {reason}")
    return go_back_to_step.invoke({
        "target_step": "destination_recommendation",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })


@tool
def go_back_to_transport(
        reason: str = "用户希望更换交通方式",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到交通规划步骤。

    使用场景：
    - 用户说"不坐飞机了"
    - 用户说"改成高铁"
    - 用户说"还是自驾吧"
    """
    app_logger.info(f"[快捷回退→交通] {reason}")
    return go_back_to_step.invoke({
        "target_step": "transport_planning",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })


@tool
def go_back_to_accommodation(
        reason: str = "用户希望调整住宿",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到住宿规划步骤。

    使用场景：
    - 用户说"住宿要求改一下"
    - 用户说"想住民宿"
    - 用户说"酒店太贵了"
    """
    app_logger.info(f"[快捷回退→住宿] {reason}")
    return go_back_to_step.invoke({
        "target_step": "accommodation_planning",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })


@tool
def go_back_to_food(
        reason: str = "用户希望调整餐饮偏好",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到餐饮规划步骤。

    使用场景：
    - 用户说"餐饮偏好改一下"
    - 用户说"想多吃特色美食"
    """
    app_logger.info(f"[快捷回退→餐饮] {reason}")
    return go_back_to_step.invoke({
        "target_step": "food_planning",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })


@tool
def go_back_to_itinerary(
        reason: str = "用户希望调整行程",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到行程生成步骤。

    使用场景：
    - 用户说"行程安排不合理"
    - 用户说"想加点景点"
    - 用户说"太累了，减少活动"
    """
    app_logger.info(f"[快捷回退→行程] {reason}")
    return go_back_to_step.invoke({
        "target_step": "itinerary_generation",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })


@tool
def go_back_to_budget(
        reason: str = "用户希望重新计算预算",
        runtime: ToolRuntime[None, TravelState] = None
) -> Command:
    """
    快捷回退：返回到预算汇总步骤。

    使用场景：
    - 用户说"预算超了"
    - 用户说"重新算一下费用"
    """
    app_logger.info(f"[快捷回退→预算] {reason}")
    return go_back_to_step.invoke({
        "target_step": "budget_summarization",
        "reason": reason,
        "clear_subsequent_data": True,
        "runtime": runtime,
    })



# ============== 查询进度工具 ==============

@tool
def check_current_progress(
        runtime: ToolRuntime[None, TravelState] = None
) -> str:
    """
    查询当前规划进度，展示已完成 / 当前 / 待完成的步骤。

    使用场景：
    - 用户问"现在到哪一步了"
    - 用户问"还有几步"
    - 用户问"进度如何"
    - 需要向用户汇报当前状态
    """
    state = runtime.state
    current_step = state.get("current_step", "requirement_collection")

    try:
        current_index = ALL_STEPS.index(current_step)
    except ValueError:
        current_index = 0

    lines = ["📊 当前规划进度：", ""]

    for i, step in enumerate(ALL_STEPS):
        label = STEP_LABELS.get(step, step)
        step_num = i + 1
        if i < current_index:
            lines.append(f"  ✅ [{step_num}] {label}")
        elif i == current_index:
            lines.append(f"  🔄 [{step_num}] {label}  ← 当前")
        else:
            lines.append(f"  ⭕ [{step_num}] {label}")

    # 追加已收集的关键信息
    lines.append("")
    lines.append("已收集信息：")
    if state.get("user_requirement"):
        req = state["user_requirement"]
        lines.append(
            f"  - 需求: {req.get('departure_date', '?')} "
            f"出发 {req.get('travel_days', '?')} 天 "
            f"| {req.get('adult_count', 0)} 成人 + {req.get('children_count', 0)} 儿童"
        )
    if state.get("selected_destination"):
        lines.append(f"  - 目的地: {state['selected_destination']}")
    if state.get("selected_transport"):
        trans_map = {"flight": "航班", "train": "高铁", "driving": "自驾"}
        lines.append(f"  - 交通: {trans_map.get(state['selected_transport'], state['selected_transport'])}")
    if state.get("selected_accommodation_types"):
        lines.append(f"  - 住宿: {', '.join(state['selected_accommodation_types'])}")
    if state.get("selected_food_types"):
        lines.append(f"  - 餐饮: {', '.join(state['selected_food_types'])}")

    return "\n".join(lines)


# ============== 导出所有回退相关工具 ==============

ALL_ROLLBACK_TOOLS = [
    go_back_to_step,            # 通用回退
    go_back_to_requirement,     # 快捷：回到需求
    go_back_to_destination,     # 快捷：回到目的地
    go_back_to_transport,       # 快捷：回到交通
    go_back_to_accommodation,   # 快捷：回到住宿
    go_back_to_food,            # 快捷：回到餐饮
    go_back_to_itinerary,       # 快捷：回到行程
    go_back_to_budget,          # 快捷：回到预算
    check_current_progress,     # 查询进度
]
