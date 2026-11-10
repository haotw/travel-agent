from jinja2 import Template
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from typing import Callable, Any
from app.core.state import TravelState
from app.core.store import get_user_memory_service
from app.utils.logger import app_logger

def _leg_query_date(state: dict, legs: list, cursor: int) -> str:
    """ 多段行程的"段日期"按时序分配（代码算，不由模型猜）

    实测多城会话三段城际全按出发日查询（重庆→北京、北京→天津都查 2026-09-18），
    与实际时序矛盾（人不可能同一天既在重庆又在北京又在天津）。规则：
      ① 出发地→首城 = 出发日；
      ② 城市 i-1 → 城市 i = 出发日 + 前 i 站累计晚数（即下一城的首日）；
      ③ 返程段（末段、终点=出发地）= 末日。
    晚数分配与酒店侧同源：出发地 1 晚 + 剩余天数在其后城市均分
    """
    from datetime import date as _date, timedelta as _timedelta
    req = state.get("user_requirement") or {}
    days = int(req.get("travel_days") or 0)
    try:
        start = _date.fromisoformat(str(req.get("departure_date") or "")[:10])
    except Exception:
        return ""
    if days <= 0 or not legs:
        return ""
    c = max(0, min(int(cursor), len(legs) - 1))
    from app.services.express_planning_service import _stay_nights, ordered_play_cities
    # 与住宿站点同源对齐——节点 = ordered_play_cities（目的地城市串，
    # 出发地仅当本身也在目的地串里才计入并置最前），晚数按**真实节点数**分配（此前按
    # legs+1 估，3 城以上与酒店侧错位）。出发地本身是游玩首节点时（北京→北京/天津），
    # 首段（北京→天津）发生在"北京住 1 晚之后"，偏移整体 +1 站
    dep = str(req.get("departure_city") or "").strip()
    dest = str(state.get("selected_destination") or "") or str(req.get("destination") or "")
    # ★ 返程段 = 末日：单独判定，不靠最后一行 min(offset, days - 1) 的截断碰巧落到末日
    if dep and c == len(legs) - 1 and str(legs[c]).rpartition("→")[2].strip() == dep:
        return (start + _timedelta(days=days - 1)).isoformat()
    nodes = ordered_play_cities(dep, dest)
    # ★ 与住宿步同一口径：首站 1 晚、其余均分
    nights = _stay_nights(days, len(nodes) or (len(legs) + 1))
    # ★ 出发地也在目的地里：第一站在本地玩，每段都往后挪一站
    shift = 1 if (dep and dep in nodes and nodes[0] == dep) else 0
    offset = sum(nights[:min(c + shift, len(nights))]) if nights else 0
    return (start + _timedelta(days=min(offset, days - 1))).isoformat()


# 本地步骤切换工具：调用即代表本步骤结束，进入下一步骤
_LOCAL_STEP_TOOLS = {
    "record_requirement_tool",
    "select_destination_tool",
    "select_transport_tool",
    "select_accommodation_tool",
    "select_accommodation_food_tool",
    "select_food_tool",
    "generate_itinerary_tool",
    "submit_itinerary_body_tool",
    "summarize_budget_tool",
}

# 无轮次上限步骤：允许模型完整跑完生成逻辑，等待用户交由prompt与清单门禁控制
_NO_ROUND_CAP_STEPS = {
    "requirement_collection",
    "itinerary_generation",
    "budget_summarization",
    "report_generation",
}

# 手动模式单次发言最多允许的数据查询轮数，超出则清空工具表收尾
_MANUAL_MAX_QUERY_ROUNDS = 2

from app.core.intent import detect_intent


def _is_confirm_reply(text: str) -> bool:
    """判断是否为纯确认语，仅简单肯定回复命中；带修改需求的回复不算确认"""
    return detect_intent(text).is_confirm_reply


# 手动模式各步骤对应的选择工具
_MANUAL_STEP_SELECT = {
    "destination_recommendation": "select_destination_tool",
    "transport_planning": "select_transport_tool",
    "accommodation_planning": "select_accommodation_tool",
    "food_planning": "select_food_tool",
}

# 手动确认模式：一轮一步 + 确认闸门规则
_MANUAL_STEP_MODE = (
    "【手动确认模式 - 一轮一步 + 确认闸门】本步骤严格按下面三种轮次之一作答，禁止跨步骤混写："
    "① 候选轮：只展示本步骤候选清单，结尾请用户挑选，本轮结束；严禁夹带后续步骤内容。"
    "② 详单轮：用户选定对象后，只展示该对象详单，结尾询问是否确认；本轮select_*工具被屏蔽，不要调用，不得标记已锁定确认。"
    "③ 确认轮：用户回复纯确认语时，调用对应select_*工具记录并推进，同轮展示下一步候选清单。"
    "**判断依据**：工具列表无select_*代表非确认轮，仅允许查询展示，不可声称完成选择或跳过确认。"
    "**重要**：无可用查询工具时，基于已有结果输出候选清单并结束本轮，禁止反复查询或报错；同一轮每个候选清单仅输出一次。"
)

# 自动确认模式规则
_AUTO_CONFIRM_MODE = (
    "【自动确认模式】AI自动选定推进，无需询问用户。"
    "**同一回合仅允许输出一次完整行程正文+一次预算明细表**：回合内多轮工具迭代时，中间轮只写一句话说明进展，"
    "禁止输出Day详情和预算表；仅最终收尾轮一次性输出最新版完整行程与预算。"
)

# 产出型步骤标识
_PRODUCE_STEPS = ("itinerary_generation", "budget_summarization")

# 手动模式产出步骤规则
_MANUAL_PRODUCE_MODE = (
    "【手动确认模式 - 产出步骤】本步骤无select_*工具，不等待候选挑选确认，按两类用户输入处理："
    "① 用户表示满意/确认：调用submit_itinerary_body_tool提交定稿落库；"
    "② 用户提出结构性变更：调用summarize_budget_tool重算预算，再提交新版完整结构，无需二次确认。"
    "两类场景同一轮完成「调预算 → 提交结构」，不要自行编写正文，正文预算由系统渲染。"
    "收尾固定措辞：「如需调整（天数/预算/目的地等），直接告诉我即可。」禁止额外确认反问。"
)


import re
_DAY_MARK = re.compile(r"第\s*(\d+|[一二三四五六七八九十]+)\s*天|Day\s*\d", re.IGNORECASE)
def _history_has_itinerary(msgs: list) -> bool:
    """判断本回合历史里是否已输出过逐日行程正文
    行程轮规则：先展示正文+预算征询、用户满意后才落库，确认轮的必要条件是
    历史里存在 Day X 正文；若没有（例如用户第一轮直接说"满意"），不能强制落库
    """
    for m in msgs:
        if getattr(m, "type", None) != "ai":
            continue
        content = getattr(m, "content", "") or ""
        if isinstance(content, str) and _DAY_MARK.search(content):
            return True
    return False
_TOOL_ABORTED_HINT = (
    "【系统提示】该工具调用未执行完成（回合内被中断），没有可用结果，请勿据此作答。"
)

def _repair_dangling_tool_calls(msgs: list) -> tuple[list, int, int]:
    """修复悬空 tool_calls / 孤立 tool 消息
    返回 (处理后的消息列表, 补入的 ToolMessage 条数, 丢弃的孤立 ToolMessage 条数)；
    无需修复时原样返回入参对象（零拷贝，不影响正常路径）
    """
    out: list = []
    inserted = dropped = 0
    i, n = 0, len(msgs)
    while i < n:
        m = msgs[i]
        mtype = getattr(m, "type", None)
        if mtype == "ai" and getattr(m, "tool_calls", None):
            out.append(m)
            # 记录本AI消息的tool_call_id，后续匹配已响应的工具消息
            pending = {
                tc.get("id"): tc.get("name")
                for tc in m.tool_calls if tc.get("id")
            }
            j = i + 1
            while j < n and getattr(msgs[j], "type", None) == "tool":
                pending.pop(getattr(msgs[j], "tool_call_id", None), None)
                out.append(msgs[j])
                j += 1
            # 对未得到响应的tool_call，补入占位ToolMessage
            for tid, tname in pending.items():
                out.append(ToolMessage(
                    content=_TOOL_ABORTED_HINT, tool_call_id=tid, name=tname or "tool"
                ))
                inserted += 1
            i = j
            continue
        # 没有对应AI tool_call的孤立tool消息，直接丢弃
        if mtype == "tool":
            dropped += 1
            i += 1
            continue
        out.append(m)
        i += 1
    if inserted or dropped:
        return out, inserted, dropped
    return msgs, 0, 0


# ============== 上下文窗口兜底（按"用户轮"边界丢弃最旧历史） ==============
# 仅裁剪发往模型的视图，checkpoint持久化历史完整保留；
# 切点只在HumanMessage边界，不切割AI-Tool消息配对，避免产生残缺工具历史
_WINDOW_TRIGGER = 40   # 消息数超过该阈值才执行裁剪
_WINDOW_KEEP = 24      # 目标最少保留消息条数

def _trim_window(msgs: list) -> list:
    """按用户轮边界丢弃最旧历史，找不到安全切点则原样返回"""
    if len(msgs) <= _WINDOW_TRIGGER:
        return msgs
    last_human = -1
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            last_human = i
            break
    if last_human <= 0:
        # 无更早可裁剪的用户轮
        return msgs
    # 寻找裁剪切点
    cut = min(len(msgs) - _WINDOW_KEEP, last_human - 1)
    for i in range(cut, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            kept_system = [m for m in msgs[:i] if getattr(m, "type", None) == "system"]
            return kept_system + msgs[i:]
    return msgs


class StepConfigMiddleware(AgentMiddleware):
    """
    步骤配置中间件 - 根据 current_step 动态配置 Agent
    """

    def __init__(self, step_config: dict):
        """
        初始化中间件

        Args:
            step_config: 提前加载好的步骤配置字典
        """
        self._step_config = step_config

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        """
        根据 current_step 动态配置 Agent
        """
        # 拿到状态
        state: TravelState = request.state
        # 判断state能不能转字典，能就转，不然直接用空字典逻辑
        state_dict = dict(state) if hasattr(state, "items") else {}
        # 读当前步骤和用户id；多选字段统一转列表，给模板渲染用
        current_step = state.get("current_step", "requirement_collection")
        user_id = state.get("user_id")

        # 兼容旧的检查点数据，老记录里可能没这几个多选字段
        # 模板渲染取不到值会报错，这里直接补默认空列表
        _req = state_dict.get("user_requirement")
        if isinstance(_req, dict):
            _req = dict(_req)
            for _k in ("transport_types", "food_preferences", "accommodation_types"):
                _req.setdefault(_k, [])
            state_dict["user_requirement"] = _req

        app_logger.info(f"📋 用户ID: {user_id}")
        app_logger.info(f"📍 当前步骤: {current_step}")

        # 配置里找不到这个步骤，直接抛错
        if current_step not in self._step_config:
            app_logger.error(f"❌ 未知步骤: {current_step}")
            raise ValueError(f"未知步骤: {current_step}")

        # 取出当前步骤的配置，还要校验前置依赖字段
        step_config = self._step_config[current_step]

        # ========== 校验依赖字段 ==========
        for required_field in step_config["requires"]:
            if required_field not in state or state[required_field] is None:
                error_msg = f"步骤 {current_step} 需要完整状态: {required_field} 未设置"
                app_logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)

        # ========== 加载用户长期记忆 ==========
        memory_prompt = ""
        if user_id:
            try:
                service = await get_user_memory_service()
                memory_prompt = await service.format_memory_for_prompt(user_id)
                if memory_prompt:
                    app_logger.info(f"💾 已加载用户长期记忆: {user_id}")
                else:
                    app_logger.info(f"📝 用户首次使用，暂无历史记忆: {user_id}")
            except Exception as e:
                app_logger.warning(f"⚠️ 加载长期记忆失败: {e}")

        # ========== 填充模板渲染变量 ==========
        try:
            state_dict["user_memory"] = memory_prompt  # 把记忆丢进模板变量里
            # auto_confirm 模式翻译成提示词里的约束文本
            # 之前只靠prompt判断不靠谱，模型经常乱选模式，改成状态驱动更稳
            if state.get("auto_confirm"):
                # 自动模式文案，约束同一回合只输出一次正文+预算表
                state_dict["auto_confirm_mode"] = _AUTO_CONFIRM_MODE
            elif current_step in _PRODUCE_STEPS:
                # 产出类步骤单独一套文案，这类步骤没有选择工具
                # 用通用文案会让模型输出完结果还反问确认，卡住流程
                state_dict["auto_confirm_mode"] = _MANUAL_PRODUCE_MODE
            else:
                # 普通手动模式，一轮一步，必须等用户确认才能往下走
                state_dict["auto_confirm_mode"] = _MANUAL_STEP_MODE

            # 多目的地交通段进度，告诉模型现在处理第几段
            # 不让模型自己记走到哪，游标交给代码控制
            leg_progress = ""
            if current_step == "transport_planning":
                from app.services.express_planning_service import _expected_legs
                _legs = _expected_legs(state)
                if _legs:
                    _cur = max(0, min(int(state.get("leg_cursor") or 0), len(_legs) - 1))
                    leg_progress = (
                        f"第 {_cur + 1}/{len(_legs)} 段：{_legs[_cur]}"
                        f"（共 {len(_legs)} 段，含返程；本轮只展示并确认这一段）"
                    )
            state_dict["leg_progress"] = leg_progress

            # 住宿多城进度，和交通段逻辑对称
            stay_progress = ""
            if current_step == "accommodation_planning":
                from app.services.express_planning_service import _multi_city_names
                _cities = _multi_city_names(state)
                if _cities:
                    _sc = max(0, min(int(state.get("stay_cursor") or 0), len(_cities) - 1))
                    stay_progress = (
                        f"第 {_sc + 1}/{len(_cities)} 城：{_cities[_sc]}"
                        f"（共 {len(_cities)} 城；本轮只查询并展示这一城的酒店）"
                    )
            state_dict["stay_progress"] = stay_progress

            template = Template(step_config["prompt"])
            system_prompt = template.render(**state_dict)
            # **state_dict 就是解包，把字典全部key-value丢给jinja渲染模板

            # 有记忆内容就拼在提示词后面
            if memory_prompt:
                system_prompt = f"{system_prompt}\n\n{memory_prompt}"

        except KeyError as e:
            app_logger.warning(f"⚠️ 提示词变量缺失: {e}, 使用原始模板")
            system_prompt = step_config["prompt"]

        # ========== 工具裁剪、强制工具选择逻辑 ==========
        # 只靠prompt拦不住模型乱跑，手动模式下很容易没等用户确认就自动选好交通酒店
        # 这里直接改可用工具列表，硬拦截
        tools = step_config["tools"]
        forced_tool_choice: Any | None = None

        # ========== 行程生成步骤强制落库正文 ==========
        # 踩过坑：模型只调用预算工具，不提交行程正文，清单页面出不来
        # 只要还没存itinerary_body，强制调用提交工具；已经调用过就不再重复推
        if current_step == "itinerary_generation" and not state.get("itinerary_body"):
            _submitted = False
            for _m in reversed(state.get("messages") or []):
                if getattr(_m, "type", None) == "human":
                    break
                if (getattr(_m, "type", None) == "tool"
                        and getattr(_m, "name", "") == "submit_itinerary_body_tool"):
                    _submitted = True
                    break
            if (not _submitted
                    and any(getattr(t, "name", "") == "submit_itinerary_body_tool"
                            for t in tools)):
                forced_tool_choice = "submit_itinerary_body_tool"
                app_logger.info("🔒 行程步：强制调用 submit_itinerary_body_tool 落库正文")

        # ========== 手动确认闸门核心逻辑 ==========
        if not state.get("auto_confirm"):
            msgs = state.get("messages") or []
            last_is_human = bool(msgs) and getattr(msgs[-1], "type", None) == "human"
            last_text = str(getattr(msgs[-1], "content", "") or "") if last_is_human else ""
            user_confirmed = _is_confirm_reply(last_text)

            # 默认不让选择类工具跑，只有用户明确发确认话术才放行
            allowed_select = set()
            if last_is_human and user_confirmed:
                allowed_select |= {
                    "select_destination_tool",
                    "select_transport_tool",
                    "select_accommodation_tool",
                    "select_food_tool",
                }

            # 用户在表单提前勾选了餐饮偏好，餐饮选择工具直接放行，不然会反复问
            if (state_dict.get("user_requirement") or {}).get("food_preferences"):
                allowed_select.add("select_food_tool")

            # select_accommodation_food_tool是自动模式专用组合工具，手动模式直接禁用
            kept = [
                t for t in tools
                if not getattr(t, "name", "").startswith("select_")
                or getattr(t, "name", "") in allowed_select
            ]

            # 查询轮次上限兜底，防止模型被拦了选择工具之后疯狂反复调用查询工具
            # 产出步骤不限制轮数，不然正文、预算生成会被打断
            if not last_is_human and current_step not in _NO_ROUND_CAP_STEPS:
                rounds = 0
                for m in reversed(msgs):
                    if getattr(m, "type", None) == "human":
                        break
                    if getattr(m, "type", None) == "ai" and getattr(m, "tool_calls", None):
                        names = {tc.get("name") for tc in m.tool_calls}
                        if names & _LOCAL_STEP_TOOLS:
                            break  # 碰到步骤切换工具，说明已经是上一轮了，计数重置
                        rounds += 1
                if rounds >= _MANUAL_MAX_QUERY_ROUNDS:
                    app_logger.info(
                        f"🔒 手动模式闸门：{current_step} 已调用 {rounds} 轮查询工具，"
                        f"清空工具表强制输出清单收尾"
                    )
                    kept = []

            if len(kept) != len(tools):
                app_logger.info(
                    f"🔒 手动模式闸门：用户尚未确认，最终可用 {len(kept)}/{len(tools)} 个工具，等待选择"
                )
            tools = kept

            # 用户确认之后，强制调用对应select工具推进状态机
            # 光靠prompt提醒经常失效，模型只回复文字不调用工具卡住
            forced_name = _MANUAL_STEP_SELECT.get(current_step)
            if (last_is_human and user_confirmed and forced_name
                    and any(getattr(t, "name", "") == forced_name for t in tools)):
                forced_tool_choice = forced_name
                app_logger.info(f"🔒 手动模式确认轮：强制调用 {forced_name} 推进到下一步")

            # 行程生成步用户说满意，强制调用生成清单工具落库
            # 之前踩坑：模型嘴上说生成好了，实际不调用工具，用户拿不到清单
            if (current_step == "itinerary_generation"
                    and last_is_human
                    and _is_confirm_reply(
                        str(getattr(msgs[-1], "content", "") or "")
                    )
                    and _history_has_itinerary(msgs)
                    and any(getattr(t, "name", "") == "generate_itinerary_tool"
                            for t in tools)):
                forced_tool_choice = "generate_itinerary_tool"
                app_logger.info("🔒 手动模式确认轮：强制调用 generate_itinerary_tool 落库")

        # ========== 交通步骤接管：高铁/航班/自驾卡片模式，模型不能自己查班次 ==========
        # 卡片模式下，车次航班路线由代码批量查好给前端，模型再去查会出现两套冲突数据
        if current_step == "transport_planning":
            from app.capabilities.train_multi_segment.train_flow import multi_leg_train
            from app.services.express_planning_service import _split_cities
            from app.services.express_planning_service import _expected_legs

            _dep = str(((state.get("user_requirement") or {}).get("departure_city")) or "").strip()
            _zero_leg = bool(
                _dep and _split_cities(state.get("selected_destination") or "")
                and not _expected_legs(state)
            )
            if multi_leg_train(state) or _zero_leg:
                _marks = ("train", "ticket", "railway") + (
                    ("flight", "driving") if _zero_leg else ()
                )
                _before = len(tools)
                tools = [
                    t for t in tools
                    if getattr(t, "name", "") != "select_transport_tool"
                    and not any(k in getattr(t, "name", "").lower() for k in _marks)
                ]
                # 如果要强制调用的工具刚刚被删掉了，取消强制，不然会报错
                if forced_tool_choice and forced_tool_choice not in {
                    getattr(t, "name", "") for t in tools
                }:
                    forced_tool_choice = None
                if len(tools) != _before:
                    _why = ("零段直通（出发地=目的地，无城际段）" if _zero_leg
                            else "多段高铁：班次由代码并行查询供给")
                    app_logger.info(
                        f"🚄 交通步：屏蔽模型自带查询/推进工具 {_before - len(tools)} 个（{_why}）"
                    )
            else:
                # 航班卡片模式接管
                from app.capabilities.flight_multi_segment.flight_flow import flight_card_mode
                if flight_card_mode(state):
                    _before = len(tools)
                    tools = [
                        t for t in tools
                        if getattr(t, "name", "") != "select_transport_tool"
                        and "flight" not in getattr(t, "name", "").lower()
                    ]
                    if forced_tool_choice and forced_tool_choice not in {
                        getattr(t, "name", "") for t in tools
                    }:
                        forced_tool_choice = None
                    if len(tools) != _before:
                        app_logger.info(
                            f"✈️ 交通步：屏蔽模型自带查询/推进工具 {_before - len(tools)}"
                            f"（多段航班：航班由代码并行查询供给）"
                        )
                else:
                    # 自驾卡片模式接管，优先级最低
                    from app.capabilities.driving_multi_segment.driving_flow import driving_card_mode
                    if driving_card_mode(state):
                        _before = len(tools)
                        _driving_marks = ("driving", "drivingroute")
                        tools = [
                            t for t in tools
                            if getattr(t, "name", "") != "select_transport_tool"
                            and not any(k in getattr(t, "name", "").lower()
                                        for k in _driving_marks)
                        ]
                        if forced_tool_choice and forced_tool_choice not in {
                            getattr(t, "name", "") for t in tools
                        }:
                            forced_tool_choice = None
                        if len(tools) != _before:
                            app_logger.info(
                                f"🚗 交通步：屏蔽模型自带查询/推进工具 {_before - len(tools)}"
                                f"（多段自驾：路线由代码并行查询供给）"
                            )

        # ========== 住宿卡片模式接管 ==========
        # 前端一次性选酒店卡片，模型不要再自己去查酒店，避免两套酒店数据打架
        if current_step == "accommodation_planning":
            from app.capabilities.hotel_multi_segment.hotel_flow import hotel_card_mode
            if hotel_card_mode(state):
                _before = len(tools)
                tools = [
                    t for t in tools
                    if getattr(t, "name", "") not in {
                        "select_accommodation_tool", "select_accommodation_food_tool",
                    }
                    and not any(k in getattr(t, "name", "").lower()
                                for k in ("hotel", "hotels"))
                ]
                if forced_tool_choice and forced_tool_choice not in {
                    getattr(t, "name", "") for t in tools
                }:
                    forced_tool_choice = None
                if len(tools) != _before:
                    app_logger.info(
                        f"🏨 多段住宿：屏蔽模型自带酒店查询/逐城推进工具 {_before - len(tools)}"
                        f"（候选由代码并行查询供给，前端卡片一次选完提交）"
                    )

        # ========== 修复残缺工具调用记录 + 裁剪上下文窗口 ==========
        # 有时候工具消息丢了会直接400报错，这里只修当前这次请求，不改动checkpoint
        req_messages = list(getattr(request, "messages", None) or [])
        rebuilt = False
        if req_messages:
            req_messages, patched_in, patched_out = _repair_dangling_tool_calls(req_messages)
            if patched_in or patched_out:
                app_logger.warning(
                    f"🩹 检测到残缺工具调用历史：补入 {patched_in} 条 ToolMessage、"
                    f"丢弃 {patched_out} 条孤立 ToolMessage（仅修本次请求，不改 checkpoint）"
                )
                rebuilt = True
            windowed = _trim_window(req_messages)
            if len(windowed) != len(req_messages):
                app_logger.info(
                    f"🪟 上下文窗口裁剪：丢弃最旧 {len(req_messages) - len(windowed)} 条消息"
                    f"（按用户轮边界对齐，保留 {len(windowed)} 条；仅改本次请求，checkpoint 不动）"
                )
                req_messages = windowed
                rebuilt = True
            if rebuilt:
                request = request.override(messages=req_messages)

        # ========== 把改好的提示词、工具、强制选择塞回请求 ==========
        modified_request = request.override(
            system_prompt=system_prompt,
            tools=tools,
            **({"tool_choice": forced_tool_choice} if forced_tool_choice else {})
        )

        app_logger.info(f"✅ 已注入步骤配置: {len(tools)} 个工具")

        # ========== 设置本轮上下文变量给工具层兜底回填参数 ==========
        # 模型经常漏传出发地、目的地、日期这些必填参数，工具层从这里读兜底
        from app.tools.mcp_tools import set_turn_context
        from app.services.express_planning_service import _expected_legs as _legs_of
        _treq = state.get("user_requirement") or {}
        _dest = str(state.get("selected_destination") or "")

        _leg_from = _leg_to = ""
        _all_legs = _legs_of(state)
        if current_step == "transport_planning" and _all_legs:
            _leg_cur = max(0, min(int(state.get("leg_cursor") or 0), len(_all_legs) - 1))
            _leg_from, _leg_to = _all_legs[_leg_cur].split("→")
        try:
            set_turn_context(
                departure_city=str(_treq.get("departure_city") or ""),
                destination=_dest.split("、")[0].split(",")[0].strip(),
                # 交通步骤按段拿日期，不是统一用出发日期
                date=(_leg_query_date(state, _all_legs, state.get("leg_cursor") or 0)
                      if current_step == "transport_planning" else "")
                or str(_treq.get("departure_date") or ""),
                multi_leg=len(_all_legs) > 1,
                leg_from=_leg_from,
                leg_to=_leg_to,
            )
        except Exception as _e:
            app_logger.warning(f"⚠️ 写入工具入参上下文失败（不影响主流程）: {_e}")

        return await handler(modified_request)


async def create_step_config_middleware() -> StepConfigMiddleware:
    """
    工厂函数：创建步骤配置中间件

    Returns:
        预加载配置的 StepConfigMiddleware 实例
    """
    from app.agents.handoffs.step_config import get_step_config

    step_config = await get_step_config()
    return StepConfigMiddleware(step_config)
