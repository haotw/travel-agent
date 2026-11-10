"""
第 07 章冒烟测试：Advanced RAG 检索

用法：
    uv run python scripts/Chapter_Seven/7_test_rag.py

前置：
- 已经跑过 scripts/Chapter_Seven/7_build_vectorstore.py（Chroma 里有数据）
- .env 里配好 DASHSCOPE_API_KEY
- Redis Docker 已启动（否则会自动降级为无缓存）

看点：
- 场景 1：直接调 Pipeline，看 5 层各层耗时
- 场景 2：同查询二次调用，看缓存命中
- 场景 3：Agent 集成，看模型主动调 query_destination_info
"""
# Windows 事件循环兼容
import sys
import asyncio
import selectors
import time

if sys.platform == "win32":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from app.core.checkpointer import checkpointer_lifespan
from app.core.store import store_lifespan
from app.rag.pipeline import get_rag_pipeline
from app.agents.handoffs.travel_agent import create_travel_agent


def _short(text, n=250):
    if not isinstance(text, str):
        text = str(text)
    return text if len(text) <= n else text[:n] + "..."


def scenario_1_direct_retrieve():
    """场景 1：直接调 Pipeline，看 5 层日志"""
    print("\n" + "=" * 60)
    print(" 场景 1：直接调用 Pipeline")
    print("=" * 60)

    pipeline = get_rag_pipeline()

    queries = [
        "西安 兵马俑值不值得去",
        "西安 最佳旅游季节",
        "哪里适合亲子游",  # 目的地不明确，测试语义泛化
    ]

    for q in queries:
        print(f"\n  🔎 查询：{q}")
        t0 = time.perf_counter()
        docs = pipeline.retrieve(q)
        elapsed = time.perf_counter() - t0
        print(f"  ⏱️  总耗时 {elapsed:.2f} s，返回 {len(docs)} 个片段")
        for i, doc in enumerate(docs, start=1):
            preview = doc.page_content[:120].replace("\n", " ")
            print(f"    [{i}] {preview}...")


def scenario_2_cache_hit():
    """场景 2：重复调用同一查询，看缓存命中"""
    print("\n" + "=" * 60)
    print(" 场景 2：缓存命中验证")
    print("=" * 60)

    pipeline = get_rag_pipeline()
    q = "西安美食有哪些推荐"

    # 第 1 次：未命中缓存
    t0 = time.perf_counter()
    docs1 = pipeline.retrieve(q)
    t1 = time.perf_counter() - t0
    print(f"  第 1 次：{t1:.2f} s（应走完整 5 层）")

    # 第 2 次：命中缓存
    t0 = time.perf_counter()
    docs2 = pipeline.retrieve(q)
    t2 = time.perf_counter() - t0
    print(f"  第 2 次：{t2:.2f} s（应命中缓存，接近 0 s）")

    if t2 < t1 / 5:
        print("  ✅ 缓存生效")
    else:
        print("  ⚠️ 缓存似乎没生效，检查 Redis 是否运行")


async def scenario_3_agent_integration():
    """场景 3：Agent 主动调 query_destination_info"""
    print("\n" + "=" * 60)
    print(" 场景 3：Agent 集成 RAG")
    print("=" * 60)

    agent = await create_travel_agent()
    config = {
        "configurable": {
            "thread_id": "ch07_rag_test",
            "user_id": "ch07_user_001",
        }
    }

    turns = [
        # 需求收集
        "从上海 10 月 25 日出发，去西安玩 4 天，两个人，预算 6000 每人，喜欢文化和美食。",
        "确认。",
        # 目的地推荐：期待 Agent 调 query_destination_info
        "帮我介绍下西安有哪些必去景点，我很感兴趣。",
    ]

    for i, text in enumerate(turns, start=1):
        print("\n" + "─" * 60)
        print(f"[第 {i} 轮]")
        print(f"  用户：{text}")

        input_state = {"messages": [HumanMessage(content=text)]}
        try:
            result = await agent.ainvoke(input_state, config=config)
        except Exception as e:
            print(f"  ❌ 出错: {type(e).__name__}: {e}")
            break

        last_msg = result["messages"][-1]
        if isinstance(last_msg, AIMessage):
            print(f"  Agent：{_short(last_msg.content)}")
            for tc in (last_msg.tool_calls or []):
                print(f"    🔧 {tc['name']}")
        elif isinstance(last_msg, ToolMessage):
            print(f"  🛠️  {_short(last_msg.content)}")

        cur_step = result.get("current_step")
        print(f"  📌 current_step = {cur_step}")


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 07 章 · Advanced RAG 冒烟".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    # 场景 1 和 2 不涉及 Checkpointer/Store，直接跑
    scenario_1_direct_retrieve()
    scenario_2_cache_hit()

    # 场景 3 需要完整环境
    async with checkpointer_lifespan():
        async with store_lifespan():
            await scenario_3_agent_integration()

    print("\n" + "🎉" * 20)
    print("  第 07 章冒烟完成！")
    print("🎉" * 20 + "\n")


if __name__ == "__main__":
    asyncio.run(main())