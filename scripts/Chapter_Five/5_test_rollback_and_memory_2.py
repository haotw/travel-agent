"""
第 05 章冒烟测试：回退 + 长期记忆 综合场景

用法：
    python -m scripts.Chapter_Five.5_test_rollback_and_memory_2

看点：
- 会话 1 中触发 go_back_to_destination + add_travel_record + update_dietary_restriction
- 观察级联清空：selected_transport / selected_accommodation_types 是否被清空
- 会话 2 中（新 thread_id）打开 Prompt，看 memory_prompt 里是否有偏好文本
"""
# Windows 事件循环兼容
import sys
import asyncio
import selectors

if sys.platform == "win32":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from app.core.checkpointer import checkpointer_lifespan, get_checkpointer
from app.core.store import store_lifespan, get_user_memory_service, get_store
from app.agents.handoffs.travel_agent import create_travel_agent


USER_ID = "ch05_smoke_user_001"
THREAD_1 = "ch05_smoke_thread_001"
THREAD_2 = "ch05_smoke_thread_002"


async def reset_test_data():
    """清理固定测试 ID 的旧数据，确保每次都从全新会话开始。"""
    checkpointer = await get_checkpointer()
    for thread_id in (THREAD_1, THREAD_2):
        await checkpointer.adelete_thread(thread_id)
        print(f"  🧹 已清理旧 checkpoint: {thread_id}")

    store = await get_store()
    await store.adelete(namespace=("user_profiles", USER_ID), key="profile")
    await store.adelete(namespace=("travel_history", USER_ID), key="history")
    print(f"  🧹 已清理旧长期记忆: {USER_ID}")


def _short(text: str, n: int = 220) -> str:
    if not isinstance(text, str):
        text = str(text)
    return text if len(text) <= n else text[:n] + "..."


def _print_turn(agent_result: dict, user_text: str, i: int):
    print("\n" + "─" * 60)
    print(f"[第 {i} 轮]")
    print(f"  用户: {user_text}")
    last_msg = agent_result["messages"][-1]
    if isinstance(last_msg, AIMessage):
        print(f"  Agent: {_short(last_msg.content)}")
        for tc in (last_msg.tool_calls or []):
            print(f"    🔧 {tc['name']}({list(tc['args'].keys())})")
    elif isinstance(last_msg, ToolMessage):
        print(f"  🛠️  {_short(last_msg.content)}")
    print(f"  📌 current_step = {agent_result.get('current_step')}")


async def session_1(agent):
    """会话 1：走一半 → 回退换目的地 → 说饮食禁忌 → 走完"""
    print("\n" + "=" * 60)
    print(" 会话 1：中途回退 + 沉淀偏好")
    print("=" * 60)

    config = {"configurable": {"thread_id": THREAD_1}}
    turns = [
        "我从北京出发 10 月 1 号，玩 4 天去武汉，两人 5000 预算，喜欢文化和美食。",
        "确认，按这个记录。",
        # 到 destination 步：用户说"去过武汉"并想换地方
        # 期待模型调 add_travel_record_tool + go_back_to_destination（或直接换成杭州）
        "我上个月刚去过武汉，换成杭州吧。",
        # 走完剩余流程
        "选杭州。",
        "高铁。",
        "民宿吧。",
        # 到 food 步说饮食禁忌
        "我不吃海鲜。特色美食和本地小吃都要。",
        "帮我把行程排出来。",
        "汇总下预算。",
        "给我一份完整的报告。",
    ]

    for i, text in enumerate(turns, start=1):
        input_state = {
            "messages": [HumanMessage(content=text)],
            # Middleware 和记忆工具从 State 读 user_id，
            # 放在 configurable 中不会自动进入 State。
            "user_id": USER_ID,
        }
        try:
            result = await agent.ainvoke(input_state, config=config)
        except Exception as e:
            print(f"  ❌ 出错: {type(e).__name__}: {e}")
            break
        _print_turn(result, text, i)


async def verify_rollback(agent):
    """核对：级联清空生效"""
    print("\n" + "=" * 60)
    print(" 校验 1：级联清空")
    print("=" * 60)

    config = {"configurable": {"thread_id": THREAD_1}}
    state = await agent.aget_state(config)
    values = state.values

    dest = values.get("selected_destination")
    print(f"  最终目的地: {dest}")
    if dest and "杭州" in dest:
        print("  ✅ 级联清空后成功切到杭州")
    else:
        print(f"  ⚠️ 目的地不是杭州（也可能是模型没执行回退）: {dest}")


async def verify_memory_written():
    """核对：饮食禁忌 & 去过武汉 是否写进 Store"""
    print("\n" + "=" * 60)
    print(" 校验 2：长期记忆已写入 Store")
    print("=" * 60)

    service = await get_user_memory_service()
    memory = await service.get_user_memory(USER_ID)

    print(f"  用户 ID: {USER_ID}")
    print(f"  travel_styles       = {memory.profile.travel_styles}")
    print(f"  dietary_restrictions = {memory.profile.dietary_restrictions}")
    print(f"  food_preferences    = {memory.profile.food_preferences}")
    print(f"  completed_trips     = "
          f"{[t.destination for t in memory.history.completed_trips]}")

    # 严格判定
    has_seafood_avoid = any("海鲜" in x for x in memory.profile.dietary_restrictions)
    has_wuhan_history = any("武汉" in t.destination for t in memory.history.completed_trips)

    print()
    print(f"  ✅ 海鲜禁忌已记录: {has_seafood_avoid}")
    print(f"  ✅ 武汉出行历史已记录: {has_wuhan_history}")


async def session_2(agent):
    """会话 2：新对话，看 Agent 是否会读到偏好"""
    print("\n" + "=" * 60)
    print(" 会话 2：新对话，验证记忆生效")
    print("=" * 60)
    print("  注意看第一轮 Agent 是否主动提及历史偏好")
    print("  （比如\"我看您之前喜欢文化探索\"或\"注意避开海鲜\"）")

    config = {"configurable": {"thread_id": THREAD_2}}
    turns = [
        "帮我规划一次成都之旅，就我一个人，5 天，预算 6000。",
        "10 月 15 日出发。",
        "确认。",
    ]

    for i, text in enumerate(turns, start=1):
        input_state = {
            "messages": [HumanMessage(content=text)],
            "user_id": USER_ID,
        }
        result = await agent.ainvoke(input_state, config=config)
        _print_turn(result, text, i)


async def cleanup():
    """清理测试数据（可选）"""
    store = await get_store()
    await store.adelete(namespace=("user_profiles", USER_ID), key="profile")
    await store.adelete(namespace=("travel_history", USER_ID), key="history")
    print(f"\n🧹 已清理 {USER_ID} 的长期记忆")


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 05 章 · 回退 + 记忆 综合冒烟".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    async with checkpointer_lifespan():
        async with store_lifespan():
            print("\n清理上次测试数据...")
            await reset_test_data()

            agent = await create_travel_agent()

            await session_1(agent)
            await verify_rollback(agent)
            await verify_memory_written()
            await session_2(agent)
            # 默认保留 Store 数据供手动查看；需要自动清理时取消下行注释。
            # await cleanup()
            print(f"\n💾 已保留 {USER_ID} 的长期记忆，可在数据库 store 表中查看")

    print("\n" + "🎉" * 20)
    print("  第 05 章冒烟完成！")
    print("🎉" * 20 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
