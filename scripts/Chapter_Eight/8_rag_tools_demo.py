"""演示 rag_tools：设城市 → 拿工具 → 直接 ainvoke 一把（需密钥 + 已建向量库）"""
import asyncio
from app.tools.rag_tools import get_rag_tools, set_rag_city

async def main():
    set_rag_city("西安")                        # 先注入目标城市（决定检索按谁过滤）
    tools = get_rag_tools()
    print("挂载的工具：", [t.name for t in tools])            # 四把工具的名字
    guide = next(t for t in tools if t.name == "search_destination_guide")
    print(await guide.ainvoke({"query": "西安兵马俑门票和游玩建议"}))  # @tool 用 .ainvoke({参数名: 值}) 调

asyncio.run(main())