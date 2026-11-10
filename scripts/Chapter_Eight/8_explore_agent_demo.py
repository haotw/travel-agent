"""演示 explore_agent_node：像图那样传分支 state 进去，拿回一条结果（需密钥 + 向量库）"""
import asyncio
from app.agents.routers.destination_router import explore_agent_node

async def main():
    branch_state = {"query": "西安有什么好玩的和好吃的", "destination": "西安"}  # Send 投喂的小 dict
    out = await explore_agent_node(branch_state)
    print(out["agent_results"][0]["result"])   # Agent 自主调工具后整合的回答

asyncio.run(main())