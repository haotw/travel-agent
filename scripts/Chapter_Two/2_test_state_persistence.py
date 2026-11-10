"""
State 持久化冒烟测试
验证：Checkpointer / Store 是否真的把数据写进了 PostgreSQL

设计要点：
- Checkpointer 是**给 LangGraph 图用的**，不是我们直接调它的 aput——
  aput 期望一个 LangGraph 内部构造的完整 checkpoint 结构
  （含 channel_versions / versions_seen / checkpoint_ns 等内部字段），
  手工构造几乎必然缺东西（会报 KeyError: 'checkpoint_ns'）。
- 正确做法：造一个**最简 StateGraph**，用 graph.ainvoke() 触发写入。
  LangGraph 会自动写正确的 checkpoint；跨"进程重启"后用 graph.aget_state() 读回。
"""
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚠️ 关键：以下 5 行必须放在最顶部！
# 必须在 import 任何 psycopg / langgraph.checkpoint.postgres 相关模块之前
# 完成事件循环策略切换，否则 Windows 会报 ProactorEventLoop 不兼容错误。
# macOS / Linux 上 sys.platform 判断会自动跳过。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import sys
import asyncio
import selectors

if sys.platform == "win32":
    # 创建 Selector
    selector = selectors.SelectSelector()
    # 创建基于 Selector 的事件循环
    loop = asyncio.SelectorEventLoop(selector)
    # 设置为当前事件循环
    asyncio.set_event_loop(loop)
    # 设置策略（防止后续代码创建 ProactorEventLoop）
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 现在可以安全地 import 依赖 psycopg 的模块了
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from app.core.checkpointer import (
    CheckpointerManager,
    get_checkpointer,
)
from app.core.store import (
    StoreManager,
    get_user_memory_service,
)
from app.core.memory_models import UserProfile


TEST_USER_ID = "smoke_test_user_001"
TEST_THREAD_ID = "smoke_test_thread_001"


# ============ 造一个最简单的 StateGraph 用来触发 Checkpointer ============
# 这里我们不引入完整的 TravelState（那会依赖后续章节的中间件等），
# 只用一个"够用就好"的最小 State：messages + current_step

class SimpleChatState(TypedDict):
    """演示用 State，只含 messages 和一个流程标记"""
    messages: Annotated[list[BaseMessage], add_messages]
    current_step: str


async def echo_node(state: SimpleChatState) -> dict:
    """回声节点：把用户最后一条消息复读回去，并写一个 current_step 标记"""
    last = state["messages"][-1]
    return {
        "messages": [AIMessage(content=f"好的！请问预算大概是多少？（针对：{last.content}）")],
        "current_step": "requirement_collection",
    }


async def build_test_graph(checkpointer):
    """把一个最简 Graph 编译出来，Checkpointer 挂在编译参数上"""
    builder = StateGraph(SimpleChatState)
    builder.add_node("echo", echo_node)
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    return builder.compile(checkpointer=checkpointer)


async def _cleanup_test_thread(thread_id: str):
    """
    清掉某 thread_id 的历史 checkpoint —— 让本测试脚本可反复跑

    为什么需要这个：
    ─────────────────────────────────────────────────────────
    LangGraph 的 Checkpointer 会把每一步的 checkpoint 存进 PostgreSQL。
    如果 PostgreSQL 里之前留了同 thread_id 的残缺记录（比如上一次运行崩在半路），
    这次 graph.ainvoke() 会尝试从残缺 checkpoint 恢复 state 而报 KeyError:
        - KeyError: 'checkpoint_ns'（读旧数据时缺 checkpoint_ns 字段）
        - KeyError: 'step'（metadata 里缺 step 字段）
    统一在 stage_1_write 开头清一次，测试脚本就能反复跑，行为一致
    """
    checkpointer = await get_checkpointer()

    # 方案 A：优先用高层 API（LangGraph 1.x 推荐做法）
    if hasattr(checkpointer, "adelete_thread"):
        try:
            await checkpointer.adelete_thread(thread_id)
            print(f"  🧹 已清理旧 checkpoint（via adelete_thread）：{thread_id}")
            return
        except Exception as e:
            print(f"  ⚠️ adelete_thread 失败，降级用 SQL：{e}")

    # 方案 B：直接 SQL 清理（不依赖 API 版本）
    mgr = await CheckpointerManager.get_instance()
    if mgr.pool is None:
        return
    async with mgr.pool.connection() as conn:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            try:
                await conn.execute(
                    f"DELETE FROM {table} WHERE thread_id = %s",
                    (thread_id,),
                )
            except Exception:
                pass  # 表可能不存在（首次跑），忽略即可
    print(f"  🧹 已清理旧 checkpoint（via SQL）：{thread_id}")


async def stage_1_write():
    """阶段 1：写入 Store 和 Checkpointer"""
    print("\n" + "=" * 60)
    print(" 阶段 1  写入数据")
    print("=" * 60)

    # 关键：先清历史 checkpoint，防止上次残留导致 KeyError
    await _cleanup_test_thread(TEST_THREAD_ID)

    # ---- 写 Store：用户画像 ----
    service = await get_user_memory_service()
    profile = UserProfile(
        travel_styles=["culture", "food"],
        dietary_restrictions=["海鲜过敏"],
        food_preferences=["辣"],
    )
    await service.save_user_profile(TEST_USER_ID, profile)
    print(f"  ✅ Store 写入完成：user_id={TEST_USER_ID}")

    # ---- 写 Checkpointer：让 LangGraph 图跑一次，自动写入 checkpoint ----
    # Checkpointer 是给 Graph 用的——不要自己调 aput 手工构造 checkpoint 结构，
    # 那些内部字段（channel_versions / versions_seen / checkpoint_ns 等）
    # 由 LangGraph 自己维护，缺一个就会 KeyError。
    checkpointer = await get_checkpointer()
    graph = await build_test_graph(checkpointer)

    config = {"configurable": {"thread_id": TEST_THREAD_ID}}
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="我想去云南玩7天")]},
        config=config,
    )
    print(f"  ✅ Checkpointer 写入完成：thread_id={TEST_THREAD_ID}")
    print(f"     此时 messages 条数 = {len(result['messages'])}，"
          f"current_step = {result.get('current_step')}")


async def stage_2_reset():
    """阶段 2：重置单例，模拟"进程重启"""
    print("\n" + "=" * 60)
    print(" 阶段 2  重置单例（模拟进程重启）")
    print("=" * 60)

    # 关掉现有池
    if CheckpointerManager._instance:
        await CheckpointerManager._instance.close()
    if StoreManager._instance:
        await StoreManager._instance.close()

    # 清空单例引用
    CheckpointerManager._instance = None
    StoreManager._instance = None
    print("  ✅ Checkpointer 单例已清空")
    print("  ✅ Store 单例已清空")
    print("  ℹ️ 相当于你重启了 Python 进程；数据应仍在 PostgreSQL 里")


async def stage_3_read_back():
    """阶段 3：从全新的单例读回数据"""
    print("\n" + "=" * 60)
    print(" 阶段 3  读回验证")
    print("=" * 60)

    # ---- 读 Store：用户画像 ----
    service = await get_user_memory_service()
    profile = await service.get_user_profile(TEST_USER_ID)

    print(f"  📖 读回用户画像：")
    print(f"      travel_styles       = {profile.travel_styles}")
    print(f"      dietary_restrictions = {profile.dietary_restrictions}")
    print(f"      food_preferences    = {profile.food_preferences}")

    assert "culture" in profile.travel_styles, "❌ travel_styles 丢失"
    assert "海鲜过敏" in profile.dietary_restrictions, "❌ dietary_restrictions 丢失"
    assert "辣" in profile.food_preferences, "❌ food_preferences 丢失"
    print("  ✅ 用户画像跨重启读回一致")

    # ---- 读 Checkpointer：用同 thread_id 重新编译 Graph 读回 State ----
    # 关键：新的 checkpointer 单例 + 新的 graph 对象，但 thread_id 相同——
    # 如果能读回上一次的 messages，就证明数据真的从 PostgreSQL 走了一遭
    checkpointer = await get_checkpointer()
    graph = await build_test_graph(checkpointer)
    config = {"configurable": {"thread_id": TEST_THREAD_ID}}

    state = await graph.aget_state(config)
    assert state is not None, "❌ checkpoint 丢失"

    values = state.values
    messages = values.get("messages", [])
    current_step = values.get("current_step")

    print(f"  📖 读回会话状态：")
    print(f"      thread_id     = {TEST_THREAD_ID}")
    print(f"      current_step  = {current_step}")
    print(f"      messages 条数 = {len(messages)}")
    for m in messages:
        preview = m.content if len(m.content) <= 60 else m.content[:60] + "..."
        print(f"        - [{m.type}] {preview}")

    assert len(messages) >= 2, "❌ messages 条数不对（至少 human + ai 各一条）"
    assert current_step == "requirement_collection", "❌ current_step 不对"
    print("  ✅ 会话状态跨\"重启\"读回一致")


async def cleanup():
    """清理测试数据（可选）"""
    print("\n" + "=" * 60)
    print(" 阶段 4  清理测试数据")
    print("=" * 60)

    service = await get_user_memory_service()
    await service.store.adelete(
        namespace=("user_profiles", TEST_USER_ID),
        key="profile",
    )
    print(f"  🧹 已删除测试用户画像：{TEST_USER_ID}")


async def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " State 持久化冒烟测试".center(58) + "║")
    print("╚" + "═" * 58 + "╝")


    loop = asyncio.get_running_loop()
    print(f"\n  当前事件循环：{type(loop).__name__}")
    if sys.platform == "win32":
        assert "Selector" in type(loop).__name__, "❌ Windows 事件循环未切换成 Selector"
        print("  ✅ Windows 已成功切到 SelectorEventLoop")

    try:
        await stage_1_write()
        await stage_2_reset()
        await stage_3_read_back()
        await cleanup()
        print("\n" + "🎉" * 20)
        print("  全部测试通过！Checkpointer 和 Store 都正常工作。")
        print("🎉" * 20 + "\n")
    except AssertionError as e:
        print(f"\n❌ 测试失败：{e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错：{type(e).__name__}: {e}\n")
        raise


if __name__ == "__main__":
    asyncio.run(main())