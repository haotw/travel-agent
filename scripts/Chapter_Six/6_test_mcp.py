"""
第 06 章冒烟测试：MCP 集成

用法：
    uv run python scripts/test_ch06_mcp.py

前置：
- .env 里配好 AMAP_API_KEY / TAVILY_API_KEY（其他外部服务可选）
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

from app.core.checkpointer import checkpointer_lifespan
from app.core.store import store_lifespan
from app.mcp_core.client import MCPClientManager, get_mcp_client
from app.tools.mcp_tools import get_weather_tools, get_search_tools
from app.agents.handoffs.travel_agent import create_travel_agent


def _short(text, n=250):
    if not isinstance(text, str):
        text = str(text)
    return text if len(text) <= n else text[:n] + "..."


async def scenario_1_direct_mcp():
    """场景 1：直接调 MCP 工具"""
    print("\n" + "=" * 60)
    print(" 场景 1：直接调用 MCP 工具")
    print("=" * 60)

    # 加载 MCP
    await get_mcp_client()

    # ---- 直接调天气 ----
    weather_tools = await get_weather_tools()
    if not weather_tools:
        print("  ⚠️ 天气工具未加载（可能 AMAP_API_KEY 未配置）")
    else:
        tool = weather_tools[0]
        print(f"\n  📍 调用 {tool.name}(city='武汉')")
        result = await tool.ainvoke({"city": "武汉"})
        print(f"  返回: {_short(result, 400)}")

    # ---- 直接调搜索 ----
    search_tools = await get_search_tools()
    if not search_tools:
        print("\n  ⚠️ 搜索工具未加载（可能 TAVILY_API_KEY 未配置）")
    else:
        tool = search_tools[0]
        print(f"\n  📍 调用 {tool.name}(query='武汉黄鹤楼', max_results=3)")
        result = await tool.ainvoke({"query": "武汉黄鹤楼", "max_results": 3})
        print(f"  返回: {_short(result, 400)}")


async def scenario_2_agent_integration():
    """场景 2：Agent 主动调 MCP 工具"""
    print("\n" + "=" * 60)
    print(" 场景 2：Agent 集成 MCP")
    print("=" * 60)

    agent = await create_travel_agent()

    config = {
        "configurable": {
            "thread_id": "ch06_mcp_test",
            "user_id": "ch06_user_001",
        }
    }

    turns = [
        # 需求收集：Agent 应当自然完成，暂不需要 MCP
        "从北京 10 月 15 号出发，去武汉玩 3 天，两个人，预算 4000 一人，喜欢文化和美食。",
        "确认。",
        # 目的地推荐：**期待 Agent 调 get_weather_forecast 查武汉天气**
        "武汉这几天天气怎么样？合不合适去？",
    ]

    for i, text in enumerate(turns, start=1):
        print("\n" + "─" * 60)
        print(f"[第 {i} 轮]")
        print(f"  用户: {text}")

        input_state = {"messages": [HumanMessage(content=text)]}
        try:
            result = await agent.ainvoke(input_state, config=config)
        except Exception as e:
            print(f"  ❌ 本轮出错: {type(e).__name__}: {e}")
            break

        last_msg = result["messages"][-1]
        if isinstance(last_msg, AIMessage):
            print(f"  Agent: {_short(last_msg.content)}")
            for tc in (last_msg.tool_calls or []):
                print(f"    🔧 {tc['name']}")
        elif isinstance(last_msg, ToolMessage):
            print(f"  🛠️  {_short(last_msg.content)}")

        cur_step = result.get("current_step")
        print(f"  📌 current_step = {cur_step}")


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 06 章 · MCP 集成 冒烟测试".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    async with checkpointer_lifespan():
        async with store_lifespan():
            await scenario_1_direct_mcp()
            await scenario_2_agent_integration()

    print("\n" + "🎉" * 20)
    print("  第 06 章 冒烟完成！")
    print("🎉" * 20 + "\n")


if __name__ == "__main__":
    asyncio.run(main())