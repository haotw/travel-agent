"""
第 03 章冒烟测试：单步骤 + 单工具 Agent

前置：
- 第 01 章的 PostgreSQL / Redis Docker 容器已运行
- .env 里配好 DASHSCOPE_API_KEY
"""
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚠️ 必须最先做：切 SelectorEventLoop
# 见第 02 章第 6.1 节的解释
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import sys
import asyncio
import selectors

if sys.platform == "win32":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 事件循环调好后再 import 依赖 psycopg 的东西
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from app.core.checkpointer import CheckpointerManager, checkpointer_lifespan
from app.core.store import StoreManager, store_lifespan
from app.agents.handoffs.travel_agent import create_travel_agent


THREAD_ID = "ch03_smoke_thread_001"
USER_ID = "ch03_smoke_user_001"

# 测试脚本，四轮对话
USER_TURNS = [
    "我想安排一次旅行。",
    "从北京出发，10 月 1 号，玩 5 天。",
    "两个人，预算大概两万左右，喜欢文化探索和美食。",
    "确认，就按这个来。",
]


def _print_ai_reply(reply):
    """把 AIMessage 的可读部分打出来"""
    if isinstance(reply.content, str):
        text = reply.content
    else:
        # 部分模型返回 list[ContentBlock] 结构
        text = "".join(
            b.get("text", "") for b in reply.content if isinstance(b, dict)
        )
    print(f"     Agent 回复: {text[:200]}{'...' if len(text) > 200 else ''}")


def _print_tool_call(reply):
    """如果这一轮 LLM 调了工具，打印工具名和参数"""
    if not reply.tool_calls:
        return
    for tc in reply.tool_calls:
        print(f"     🔧 调用工具: {tc['name']}")
        print(f"        参数: {tc['args']}")


async def run_conversation():
    """跑完四轮对话"""
    print("\n" + "=" * 60)
    print(" 阶段 1  开始四轮对话")
    print("=" * 60)

    agent = await create_travel_agent()
    config = {
        "configurable": {
            "thread_id": THREAD_ID,
            "user_id": USER_ID,
        }
    }

    for i, user_text in enumerate(USER_TURNS, start=1):
        print(f"\n  [第 {i} 轮]")
        print(f"     用户: {user_text}")

        # 每一轮只往图里推**用户这一条新消息**
        # Checkpointer 会自动带回历史，无需手动拼
        input_state = {"messages": [HumanMessage(content=user_text)]}

        result = await agent.ainvoke(input_state, config=config)

        # 最后一条 message 一般是 AIMessage
        last_msg = result["messages"][-1]

        if isinstance(last_msg, AIMessage):
            _print_ai_reply(last_msg)
            _print_tool_call(last_msg)
        elif isinstance(last_msg, ToolMessage):
            # 工具刚执行完，图会继续回到 Model 节点再吐一条 AIMessage
            print(f"     🛠️ 工具返回: {last_msg.content[:200]}")

        # 打印 State 里的 current_step / user_requirement 变化
        cs = result.get("current_step")
        ur = result.get("user_requirement")
        if cs:
            print(f"     📌 current_step = {cs}")
        if ur:
            print(f"     📌 user_requirement = {ur}")


async def verify_state():
    """阶段 2：从 Checkpointer 读回最终 State，核对字段"""
    print("\n" + "=" * 60)
    print(" 阶段 2  从 Checkpointer 核对最终 State")
    print("=" * 60)

    agent = await create_travel_agent()
    config = {"configurable": {"thread_id": THREAD_ID}}

    # 直接从 Agent 的 State 拉当前值
    state = await agent.aget_state(config)

    values = state.values
    ur = values.get("user_requirement")
    cs = values.get("current_step")
    msgs = values.get("messages", [])

    print(f"  📖 current_step: {cs}")
    print(f"  📖 消息总数: {len(msgs)}")
    if ur:
        print(f"  📖 user_requirement 详情:")
        for k, v in ur.items():
            print(f"     - {k}: {v}")

    # 校验：跑完对话后 user_requirement 应当已就绪
    if ur is None:
        print("  ⚠️  user_requirement 还没填上——可能是模型没决定调工具")
        print("      重跑一次或改用更明确的第 3 轮说法（比如把预算 & 风格写清楚）")
        return False

    assert ur.get("departure_city") == "北京", "❌ 出发地不对"
    assert ur.get("travel_days") == 5, "❌ 天数不对"
    assert "culture" in (ur.get("travel_styles") or []) or \
           "food" in (ur.get("travel_styles") or []), "❌ 风格未记录"
    print("\n  ✅ 关键字段核对通过")
    return True


async def verify_persistence():
    """阶段 3：重置单例（模拟"进程重启"），再从 Checkpointer 读回"""
    print("\n" + "=" * 60)
    print(" 阶段 3  跨重启读回验证")
    print("=" * 60)

    # 关掉现有池并清空单例
    if CheckpointerManager._instance:
        await CheckpointerManager._instance.close()
    if StoreManager._instance:
        await StoreManager._instance.close()
    CheckpointerManager._instance = None
    StoreManager._instance = None
    print("  🔄 单例已清空，等效于重启进程")

    # 全新创建 Agent
    agent = await create_travel_agent()
    config = {"configurable": {"thread_id": THREAD_ID}}
    state = await agent.aget_state(config)
    values = state.values

    ur = values.get("user_requirement")
    msgs = values.get("messages", [])

    print(f"  📖 重启后消息数: {len(msgs)}")
    print(f"  📖 重启后 user_requirement: {ur}")

    assert ur is not None, "❌ 重启后 user_requirement 丢了"
    assert len(msgs) >= 4, "❌ 重启后消息数少了"
    print("  ✅ 会话状态跨重启读回一致")


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 03 章 · 需求收集 Agent 冒烟测试".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    # 用嵌套 lifespan 拉起 Checkpointer + Store
    async with checkpointer_lifespan():
        async with store_lifespan():
            await run_conversation()
            ok = await verify_state()
            if ok:
                await verify_persistence()
                print("\n" + "🎉" * 20)
                print("  第 03 章冒烟通过！Agent 已经可以真正对话了。")
                print("🎉" * 20 + "\n")


if __name__ == "__main__":
    asyncio.run(main())