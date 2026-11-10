"""第 8 章综合冒烟：完整跑一遍目的地推荐子图（需 .env 密钥 + 已建向量库）"""
import asyncio
from app.agents.routers.destination_router import create_destination_router

async def main():
    router = create_destination_router()
    # 初始 state：只需给原始查询和目的地，中间字段图会自己填
    init_state = {
        "original_query": "帮我推荐一下西安怎么玩",
        "destination": "西安",
        "classifications": [],
        "agent_results": [],
        "final_report": "",
    }
    result = await router.ainvoke(init_state)   # 一把跑通：分类 → 扇出并行 → 扇入归并
    print("=" * 60)
    print(result["final_report"])              # 攻略段 + 天气段合并后的最终报告
    print("=" * 60)
    print("分类结果：", [(c["agent"], c["query"]) for c in result["classifications"]])

if __name__ == "__main__":
    asyncio.run(main())