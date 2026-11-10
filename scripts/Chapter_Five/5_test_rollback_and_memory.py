"""
第 05 章交互测试：回退 + 长期记忆综合场景

运行后由用户在终端逐轮输入，实时观察：
- Agent 的自然语言回复
- 模型发起的工具调用及参数
- 工具执行结果
- current_step 的变化
- 新会话是否能读取同一用户的长期记忆

终端命令：
- /new     切换到第二个全新会话，验证跨会话长期记忆
- /state   查看当前 LangGraph State 摘要
- /memory  查看 PostgreSQL Store 中的长期记忆
- /reset   清空当前会话 checkpoint，从需求收集重新开始
- /quit    退出
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
from app.core.store import store_lifespan, get_user_memory_service
from app.agents.handoffs.travel_agent import create_travel_agent


USER_ID = "ch05_smoke_user_001"
THREAD_1 = "ch05_smoke_thread_001"
THREAD_2 = "ch05_smoke_thread_002"


async def reset_test_threads():
    """清理旧测试会话，确保每次冒烟测试都从全新 checkpoint 开始。"""
    checkpointer = await get_checkpointer()

    for thread_id in (THREAD_1, THREAD_2):
        await checkpointer.adelete_thread(thread_id)
        print(f"  🧹 已清理旧 checkpoint: {thread_id}")


def _short(text: str, n: int = 220) -> str:
    if not isinstance(text, str):
        text = str(text)
    return text if len(text) <= n else text[:n] + "..."


def _print_message(message):
    """把本轮新增的 AI / Tool 消息打印到终端。"""
    if isinstance(message, AIMessage):
        if message.content:
            print(f"\nAgent > {_short(message.content, 1000)}")

        for tool_call in message.tool_calls or []:
            print(f"\n🔧 工具调用: {tool_call['name']}")
            print(f"   参数: {tool_call.get('args', {})}")

    elif isinstance(message, ToolMessage):
        tool_name = message.name or "unknown_tool"
        print(f"\n🛠️ 工具结果 [{tool_name}]: {_short(message.content, 1000)}")


async def run_turn(agent, thread_id: str, user_text: str):
    """运行一轮对话，并实时展示模型、工具和步骤变化。"""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent.aget_state(config)
    previous_values = snapshot.values or {}
    displayed_message_count = len(previous_values.get("messages", []))
    previous_step = previous_values.get("current_step")

    input_state = {
        "messages": [HumanMessage(content=user_text)],
        # user_id 必须进入 State；只放 configurable 中，Middleware 读取不到。
        "user_id": USER_ID,
    }

    async for values in agent.astream(
            input_state,
            config=config,
            stream_mode="values",
    ):
        messages = values.get("messages", [])
        for message in messages[displayed_message_count:]:
            if not isinstance(message, HumanMessage):
                _print_message(message)
        displayed_message_count = len(messages)

        current_step = values.get("current_step")
        if current_step and current_step != previous_step:
            print(f"\n📌 步骤变化: {previous_step or '未初始化'} → {current_step}")
            previous_step = current_step


async def show_state(agent, thread_id: str):
    """打印当前会话的关键 State。"""
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values or {}
    fields = (
        "user_id", "current_step", "user_requirement",
        "selected_destination", "selected_transport",
        "selected_accommodation_types", "selected_food_types",
        "itinerary", "budget", "report",
    )

    print("\n📦 当前 State：")
    print(f"  messages: {len(values.get('messages', []))} 条")
    for field in fields:
        if field in values:
            print(f"  {field}: {_short(values[field], 500)}")


async def show_memory():
    """打印当前测试用户在 Store 中的长期记忆。"""
    service = await get_user_memory_service()
    memory = await service.get_user_memory(USER_ID)
    print(f"\n💾 用户长期记忆: {USER_ID}")
    print(f"  travel_styles: {memory.profile.travel_styles}")
    print(f"  dietary_restrictions: {memory.profile.dietary_restrictions}")
    print(f"  food_preferences: {memory.profile.food_preferences}")
    print(f"  completed_trips: {[t.destination for t in memory.history.completed_trips]}")


async def interactive_chat(agent):
    """在命令行中持续读取用户输入，直到用户主动退出。"""
    current_thread = THREAD_1

    print("\n" + "=" * 60)
    print(" 交互模式已启动")
    print("=" * 60)
    print(f"  用户 ID: {USER_ID}")
    print(f"  当前会话: {current_thread}")
    print("  直接输入旅行需求即可；可用命令：")
    print("  /new  /state  /memory  /reset  /quit")

    while True:
        try:
            user_text = input(f"\n你 [{current_thread}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 已结束交互。")
            break

        if not user_text:
            continue

        command = user_text.lower()
        if command in {"/quit", "quit", "exit", "q"}:
            print("\n👋 已结束交互。")
            break

        if command == "/new":
            if current_thread == THREAD_1:
                current_thread = THREAD_2
                print(f"\n🆕 已切换到全新会话: {current_thread}")
                print("   user_id 保持不变，可以验证长期记忆是否跨会话生效。")
            else:
                print(f"\nℹ️ 当前已经是第二个会话: {current_thread}")
            continue

        if command == "/state":
            await show_state(agent, current_thread)
            continue

        if command == "/memory":
            await show_memory()
            continue

        if command == "/reset":
            checkpointer = await get_checkpointer()
            await checkpointer.adelete_thread(current_thread)
            print(f"\n🧹 已清空当前会话: {current_thread}")
            continue

        try:
            await run_turn(agent, current_thread, user_text)
        except Exception as exc:
            print(f"\n❌ 本轮出错: {type(exc).__name__}: {exc}")
            print("   会话仍然保留，你可以检查 /state 后继续输入或使用 /reset。")


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 05 章 · 回退 + 记忆 交互测试".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    async with checkpointer_lifespan():
        async with store_lifespan():
            await reset_test_threads()

            agent = await create_travel_agent()
            await interactive_chat(agent)


if __name__ == "__main__":
    asyncio.run(main())
