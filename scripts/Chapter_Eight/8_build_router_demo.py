"""演示 create_destination_router：编译出子图并打印它的节点/边结构（纯结构，无需密钥）"""
from app.agents.routers.destination_router import create_destination_router

router = create_destination_router()           # 拿到编译好的子图
graph = router.get_graph()
print("节点：", list(graph.nodes))              # classifier / explore / weather / synthesizer …
print("边：")
for e in graph.edges:
    print(f"   {e.source} → {e.target}")        # 看清扇出扇入的走向