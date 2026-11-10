"""步骤配置终版：七个步骤各注册了哪些工具、依赖哪些字段，几条关键硬约束在不在（纯逻辑，不连 MCP、不调模型）"""
import asyncio
from types import SimpleNamespace

from app.agents.handoffs import step_config as sc

# 测试驱动：7 个 MCP 工具入口换成"只返回带名字的假工具"，不连 MCP 服务（名字和真实工具一致）
FAKE_MCP = {
    "get_hotel_tools": ["searchHotels"],
    "get_search_tools": ["search_travel_info"],
    "get_date_tools": ["get-current-date"],
    "get_weather_tools": ["get_weather_forecast"],
    "get_flight_tools": ["searchFlightsByDepArr"],
    "get_train_tools": ["get-tickets"],
    "get_driving_tools": ["maps_direction_driving"],
}
for func_name, tool_names in FAKE_MCP.items():
    async def fake(names=tool_names):
        return [SimpleNamespace(name=n) for n in names]
    setattr(sc, func_name, fake)          # step_config 顶部 from-import 了这 7 个函数，替换它模块里的名字


async def main() -> None:
    cfg = await sc.get_step_config()
    print("步骤：", list(cfg))
    for step, conf in cfg.items():
        names = [t.name for t in conf["tools"]]
        print(f"\n{step}（依赖 {conf['requires'] or '无'}）")
        print(f"  {len(names)} 把工具：{'、'.join(names)}")

    prompt = {step: conf["prompt"] for step, conf in cfg.items()}
    checks = {
        "目的地步：多城逐城输出「### {城市} 旅游信息」": "### {城市} 旅游信息" in prompt["destination_recommendation"],
        "目的地步：多城以顺序确认句收尾": "请确认是否按『出发地" in prompt["destination_recommendation"],
        "目的地步：天气不许模型自己写": "天气不要自己写" in prompt["destination_recommendation"],
        "交通步：多段只看系统给的当前段": "{{ leg_progress }}" in prompt["transport_planning"],
        "住宿步：多城只看系统给的当前城": "{{ stay_progress }}" in prompt["accommodation_planning"],
        "除需求收集外，6 个步骤都读确认模式": sum("{{ auto_confirm_mode }}" in p for p in prompt.values()) == 6,
        "行程步注册了本章的 submit_itinerary_body_tool":
            "submit_itinerary_body_tool" in [t.name for t in cfg["itinerary_generation"]["tools"]],
        "住宿步注册了本章的一站式工具":
            "select_accommodation_food_tool" in [t.name for t in cfg["accommodation_planning"]["tools"]],
        "订单步已移除，预算步是终点": "order_generation" not in cfg,
    }
    print()
    for name, ok in checks.items():
        print(f"{'✅' if ok else '❌'} {name}")


asyncio.run(main())