"""按类取工具演示：连上 MCP，看每一类拿到哪些工具（需 `.env` 配好 MCP 相关密钥）"""
import asyncio

from app.tools.mcp_tools import (get_all_mcp_tools, get_date_tools, get_driving_tools, get_flight_tools, get_hotel_tools,
                                 get_search_tools, get_train_tools, get_weather_tools)


async def main():
    print("全部：", len(await get_all_mcp_tools()), "个")
    for name, getter in [("高铁", get_train_tools), ("航班", get_flight_tools), ("自驾", get_driving_tools), ("酒店", get_hotel_tools),
                         ("天气", get_weather_tools), ("搜索", get_search_tools), ("日期", get_date_tools)]:
        print(f"{name}：", [t.name for t in await getter()])


asyncio.run(main())