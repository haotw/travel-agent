"""
第 04 章冒烟测试：Middleware 驱动的 8 步 Handoffs 流程
看点：
- 每一轮都打印 current_step
- 看它从 requirement_collection 一路推到 report_generation
- 观察每一步的 tools 数量（Middleware 只暴露 1-2 个）
"""
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Windows 事件循环兼容（见第 02 章 6.1）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import sys
import asyncio
import selectors

if sys.platform == "win32":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from app.core.checkpointer import checkpointer_lifespan
from app.core.store import store_lifespan
from app.agents.handoffs.travel_agent import create_travel_agent


THREAD_ID = "ch04_handoffs_thread_001"
USER_ID = "ch04_handoffs_user_001"


# 我们准备一段"走完全流程"的模拟对话
# 每条都是用户 turn。Agent 在中间轮次会问一些问题——我们让下一条覆盖式回答
USER_TURNS = [
    # === 步骤 1：需求收集 ===
    "我想在 10 月 1 日从北京出发，去武汉玩 4 天，两个人，预算大约每人 5000 元，喜欢文化探索和美食。",
    "确认，就按这个来。",

    # === 步骤 2：目的地推荐 ===
    # 用户已经指定了武汉，模型简单点评一下即可推进
    "确认，选武汉。",

    # === 步骤 3：交通规划 ===
    # 北京到武汉约 1100 km，模型应该给出建议；用户选高铁
    "选高铁吧。",

    # === 步骤 4：住宿规划 ===
    "选经济酒店。",

    # === 步骤 5：餐饮规划 ===
    "特色美食和本地小吃都要。",

    # === 步骤 6:行程生成 ===
    "帮我把每天安排排出来。",

    # === 步骤 7：预算汇总 ===
    "汇总下预算吧。",

    # === 步骤 8：报告生成（终点）===
    "给我一份完整的旅行报告。",
]


def _short(text: str, n: int = 200) -> str:
    if len(text) <= n:
        return text
    return text[:n] + "..."


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 04 章 · Middleware 驱动 8 步流程冒烟".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    async with checkpointer_lifespan():
        async with store_lifespan():
            agent = await create_travel_agent()

            config = {
                "configurable": {
                    "thread_id": THREAD_ID,
                    "user_id": USER_ID,
                }
            }

            print("\n开始对话，每一轮打印 current_step 变化...")

            prev_step = None
            for i, user_text in enumerate(USER_TURNS, start=1):
                print("\n" + "─" * 60)
                print(f"[第 {i} 轮]")
                print(f"  用户: {user_text}")

                # 只推新消息，历史交给 Checkpointer
                input_state = {"messages": [HumanMessage(content=user_text)]}

                try:
                    result = await agent.ainvoke(input_state, config=config)
                except Exception as e:
                    print(f"  ❌ 本轮出错: {type(e).__name__}: {e}")
                    break

                # 从 result 里挑 AI 最后一条可读回复
                last_msg = result["messages"][-1]
                if isinstance(last_msg, AIMessage):
                    text = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
                    print(f"  Agent: {_short(text)}")
                    if last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            print(f"    🔧 {tc['name']}({list(tc['args'].keys())})")
                elif isinstance(last_msg, ToolMessage):
                    print(f"  🛠️  {last_msg.content[:200]}")

                # 打印 current_step 变化
                cur_step = result.get("current_step")
                if cur_step != prev_step:
                    arrow = f"{prev_step or '(未开始)'} → {cur_step}"
                    print(f"  📌 步骤推进: {arrow}")
                else:
                    print(f"  📌 步骤保持: {cur_step}")
                prev_step = cur_step

                # 到达终点直接停
                if cur_step == "report_generation":
                    # 让最后一轮把报告写出来即可
                    if i >= len(USER_TURNS):
                        pass
                    elif isinstance(last_msg, AIMessage) and "旅行报告" in str(last_msg.content):
                        break

            # 结束后再拉一次 State 看总览
            print("\n" + "=" * 60)
            print(" 最终 State 概览")
            print("=" * 60)
            state = await agent.aget_state(config)
            values = state.values
            for k in [
                "current_step", "user_requirement", "selected_destination",
                "selected_transport", "selected_accommodation_types",
                "selected_food_types", "itinerary", "budget",
            ]:
                v = values.get(k)
                if v is None:
                    print(f"  {k}: (未填)")
                else:
                    s = str(v)
                    if len(s) > 200:
                        s = s[:200] + "..."
                    print(f"  {k}: {s}")

            print("\n" + "🎉" * 20)
            print("  第 04 章冒烟完成！")
            print("🎉" * 20 + "\n")


if __name__ == "__main__":
    asyncio.run(main())