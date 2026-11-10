"""record_requirement_tool 演示：模型把天数读成 3，表单写的是 4——入库的以表单为准（直接调真实工具，纯逻辑，无需密钥）"""
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage

from app.tools.state_transition import record_requirement_tool

FORM = ("我想去天津、上海旅游\n- 出发地：北京\n- 出发日期：2026-10-01\n- 旅行天数：4 天\n"
        "- 出行人数：2 成人 0 儿童\n- 人均预算：3000 元\n- 全程交给 AI 自动确认，无需逐步询问")
state = {"messages": [HumanMessage(content=FORM)], "current_step": "requirement_collection"}
runtime = ToolRuntime(state=state, context=None, config={}, stream_writer=None, tool_call_id="call_1", store=None)

cmd = record_requirement_tool.func(          # 模拟模型的一次工具调用：它把天数读成了 3，也没传目的地
    departure_city="北京", departure_date="2026-10-01", travel_days=3, budget_min=2000, budget_max=3000,
    travel_styles=["culture"], adult_count=2, auto_confirm=True, runtime=runtime)
up = cmd.update
req = up["user_requirement"]
print("写进 state 的键：", [k for k in up if k != "messages"])
print("travel_days  →", req["travel_days"], "（模型传 3，表单是 4）")
print("destination  →", req.get("destination"), "（模型没传，从表单 head 抠出来）")
print("budget_level →", req.get("budget_level"), "（按预算区间由代码算）")
print("auto_confirm →", up.get("auto_confirm"), "| current_step →", up["current_step"])
print("回给模型的话：", up["messages"][0].content[:60], "…")