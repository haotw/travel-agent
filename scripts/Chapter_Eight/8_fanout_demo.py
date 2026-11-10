"""演示 route_to_agents：扇出 + 去重（纯函数，可直接跑）"""
from app.agents.routers.destination_router import route_to_agents

state = {
    "destination": "苏州",
    "classifications": [
        {"agent": "explore", "query": "苏州文化探索"},
        {"agent": "explore", "query": "苏州文化探索"},   # 故意重复，应被去掉
        {"agent": "weather", "query": "苏州 天气"},
    ],
}
for s in route_to_agents(state):                # 3 条 → 去重成 2 条 Send
    print(f"扇出到节点 {s.node}，携带查询：{s.arg['query']}")