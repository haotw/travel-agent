"""第 9 章冒烟：四类 capability 的"查询 → 下发 → 提交校验"全链路，离线跑一遍（纯逻辑，无需密钥）"""
import asyncio
import json

from app.capabilities.driving_multi_segment import driving_agent_tool
from app.capabilities.driving_multi_segment.driving_agent_tool import build_driving_multi_segment_payload, validate_driving_submission
from app.capabilities.driving_multi_segment.driving_skill_schema import DrivingSubmitPayload
from app.capabilities.flight_multi_segment import flight_agent_tool
from app.capabilities.flight_multi_segment.flight_agent_tool import build_flight_multi_segment_payload, validate_flight_submission
from app.capabilities.flight_multi_segment.flight_skill_schema import FlightSubmitPayload
from app.capabilities.hotel_multi_segment import hotel_parser
from app.capabilities.hotel_multi_segment.hotel_agent_tool import build_hotel_multi_segment_payload, validate_hotel_multi_submission
from app.capabilities.hotel_multi_segment.hotel_skill_schema import HotelMultiSegmentSubmitPayload
from app.capabilities.train_multi_segment import train_agent_tool
from app.capabilities.train_multi_segment.train_agent_tool import build_train_multi_segment_payload, validate_train_submission
from app.capabilities.train_multi_segment.train_flow import _legs_with_dates, multi_leg_train
from app.capabilities.train_multi_segment.train_skill_schema import TrainSubmitPayload

TRAIN = {"北京": "G1 北京南(telecode:VNP) -> 天津(telecode:TJP) 08:30 -> 09:05 历时：00:35\n- 二等座: 有票 54.5元",
         "天津": "G101 天津西(telecode:TXP) -> 上海虹桥(telecode:AOH) 09:10 -> 14:02 历时：04:52\n- 二等座: 有 509.0元",
         "上海": "G2 上海虹桥(telecode:AOH) -> 北京南(telecode:VNP) 19:00 -> 23:18 历时：04:18\n- 二等座: 有 553.0元"}
FLIGHT = json.dumps([{"fcategory": "0", "FlightNo": "CA1501", "FlightCompany": "中国国际航空股份有限公司", "FlightDepAirport": "首都国际机场",
               "FlightArrAirport": "虹桥国际机场", "FlightDeptimePlanDate": "2026-10-03 08:00:00", "FlightArrtimePlanDate": "2026-10-03 10:10:00"}])
AMAP = json.dumps({"route": {"paths": [{"distance": "137000", "duration": "6120", "tolls": "65", "traffic_lights": "12"}]}})
HOTEL = json.dumps({"hotelInformationList": [{"name": "如家酒店(西湖店)", "price": {"message": "716CNY 共2晚 358CNY/晚", "lowestPrice": 358.0}, "starRating": 4.6}]})


class Fake:                  # 测试驱动：一个假工具顶四类数据源，按入参返回对应的原始文本
    name = "searchHotels"
    args_schema = {"properties": {"checkInParam": {}}}

    async def ainvoke(self, args: dict):
        if "fromStation" in args:
            return TRAIN[args["fromStation"]]
        if "dep" in args:
            return FLIGHT
        if "origin" in args:
            return AMAP
        return HOTEL


def check(name: str, ok: bool):
    print(("✅" if ok else "❌"), name)
    assert ok, name


async def main():
    fake = Fake()          # 测试驱动：四类查询工具都换成假的，其余全是真实代码
    train_agent_tool._QUERY_TOOL = flight_agent_tool._QUERY_TOOL = driving_agent_tool._QUERY_TOOL = hotel_parser._QUERY_TOOL = fake
    st = {"user_requirement": {"departure_city": "北京", "departure_date": "2026-10-01", "travel_days": 5, "transport_types": ["高铁"]},
          "selected_destination": "天津、上海"}
    legs = _legs_with_dates(st)
    check("1 路段与段日期：北京→天津 10-01、天津→上海 10-02、上海→北京 10-05",
          [(l.from_, l.to, l.travel_date) for l in legs] == [("北京", "天津", "2026-10-01"), ("天津", "上海", "2026-10-02"),
                                                             ("上海", "北京", "2026-10-05")])
    check("2 高铁路线判定：勾了高铁 + 三段 → 走代码卡片", multi_leg_train(st))
    p = await build_train_multi_segment_payload(legs, cache_key="c")
    picks = [{"segment_id": s.segment_id, "option_id": s.train_list[0].option_id} for s in p.segments]
    check("3 高铁：三段并行查到、提交校验通过", validate_train_submission(TrainSubmitPayload.model_validate({"segments": picks}), "c").ok)
    check("4 高铁：漏选一段 → INCOMPLETE",
          validate_train_submission(TrainSubmitPayload.model_validate({"segments": picks[:1]}), "c").code == "INCOMPLETE")
    p = await build_flight_multi_segment_payload([{"from": "北京", "to": "上海", "date": "2026-10-01"}], cache_key="c")
    pick = [{"segment_id": "s1", "option_id": p.segments[0].flight_list[0].option_id}]
    check("5 航班：机场码转换 + 提交校验通过", validate_flight_submission(FlightSubmitPayload.model_validate({"segments": pick}), "c").ok)
    p = await build_driving_multi_segment_payload([{"from": "北京", "to": "天津"}], cache_key="c")
    check("6 自驾：路线解析为 137km / 01:42", (p.segments[0].ok, p.segments[0].distance_km, p.segments[0].duration_text) == (True, 137.0, "01:42"))
    check("7 自驾：只读确认通过", validate_driving_submission(DrivingSubmitPayload.model_validate({"segments": [{"segment_id": "s1"}]}), "c").ok)
    p = await build_hotel_multi_segment_payload([{"city": "杭州", "checkInDate": "2026-10-01", "checkOutDate": "2026-10-03"}], cache_key="c")
    seg = p.segments[0]
    check("8 住宿：门店模式、每晚 358 / 总价 716", (seg.mode, seg.hotel_list[0].pricePerNight, seg.hotel_list[0].totalPrice) == ("hotel", 358, 716))
    bad = validate_hotel_multi_submission(HotelMultiSegmentSubmitPayload.model_validate(
        {"segments": [{"segment_id": seg.segment_id, "mode": "brand", "brand_id": "x"}]}), "c")
    check("9 住宿：提交模式与下发不一致 → MODE_MISMATCH", bad.code == "MODE_MISMATCH")
    print("🎉 第 9 章冒烟全部通过")


asyncio.run(main())