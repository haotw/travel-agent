"""快速通道服务。本章先放四个路段助手（拆多城、排游玩顺序、造交通段、分配住宿晚数），第 12 章整份重写本文件"""
import re

# 目的地支持逗号分隔多城（"杭州,深圳"），全链路真查每段交通 + 每城酒店/天气。
# 串联语义：出发地 → city0 → city1 → ... → 返程（返程终点=出发地）。
# 原本把整串"杭州,深圳"当单个城市塞进所有查询（toStation/arrcity/place/city），
# 导致交通全查空 + LLM 自行扩天数为 5 天。
_CITY_DELIMS = "，,、"

def _split_cities(destination: str) -> list[str]:
    """把 destination 按中/英逗号、顿号切分为城市列表（去空去重保序）"""
    if not destination:
        return []
    flat = destination
    for ch in _CITY_DELIMS:
        flat = flat.replace(ch, " ")
    out: list[str] = []
    for city in flat.split():
        if city not in out:
            out.append(city)
    return out


def ordered_play_cities(departure: str, destination: str) -> list[str]:
    """游玩/住宿节点城市序列（去重保序）：**出发地仅当本身也在目的地串里才计入**，且置于最前。

 （用户规格）：住宿站点 = 目的地城市序列。北京→上海 = [上海]（不再多查北京），
    北京→天津/上海 = [天津,上海]，北京→北京 = [北京]；目的地含出发地（北京→北京/天津）时
    出发地是"第一游玩地"（先本地玩再走），故置于最前 → [北京,天津]
    """
    cities = _split_cities(destination)
    dep = (departure or "").strip()
    # ★ 出发地也在目的地里：先在出发地玩
    ordered = (([dep] if dep and dep in cities else []) + cities)
    out: list[str] = []
    for c in ordered:
        if c and c not in out:
            out.append(c)
    return out



def _build_legs(departure: str, cities: list[str]) -> list[tuple[str, str]]:
    """构造交通路段序列：出发→首城、城际转场、末城→出发地返程。

    剔除"自身段"——当目的地含出发地（如出发+目的地都是北京）时，
    route 会出现"北京→北京"，本无意义；剔除后行程正确保留北京本地游玩。
    节点列表 = 出发地 + 目的地序列 + 出发地（返程），相邻节点城市不同才生成段：
    北京→上海 = 2 段、北京→天津→上海 = 3 段、北京→北京 = 0 段；出发地缺失时不补返程
    """
    if not cities:
        return []
    route = [departure] + cities + ([departure] if departure else [])
    # ★ 相邻打包成段；a == b 的自身段跳过；末尾补回的出发地让最后一段成为返程
    return [(a, b) for a, b in zip(route[:-1], route[1:]) if a != b]


def _stay_nights(days: int, stations: int) -> list[int]:
    """住宿晚数分配：**出发地固定 1 晚**，剩余天数在其后城市均分（前几城多担 1 天）

 （用户规格）：酒店段覆盖全部节点城市（含出发地）。天数不够分时
    每站仍按 1 晚顺排（不替用户删城），与 _stay_windows 原口径一致
    """
    if stations <= 0 or days <= 0:
        return []
    if stations == 1:
        return [days]
    rest = max(1, days - 1)
    per, rem = divmod(rest, stations - 1)
    # ★ 首站 1 晚，剩下的天数在后面几站均分，除不尽的前几站多担
    return [1] + [per + (1 if i < rem else 0) for i in range(stations - 1)]



def _multi_city_names(state) -> list[str]:
    """多目的地城市列表（按游览顺序）；单目的地返回空列表（调用方跳过校验）

    单城返回空列表是刻意设计：单目的地流程保持完全不变，不引入任何新校验
    """
    from app.services.express_planning_service import _split_cities
    cities = _split_cities(state.get("selected_destination") or "")
    return cities if len(cities) > 1 else []


def _expected_legs(state) -> list[str]:
    """应有的交通段：出发地→第一城 + 城际转场 + 末城→出发地返程（节点相邻城市不同才生成）。

 单目的地同样纳入段级校验（此前单城返回空列表跳过校验）。
 （用户规格）：按 _build_legs 口径——末城→出发地返程段一并计入，
    北京→上海 = 2 段、北京→天津→上海 = 3 段、北京→北京 = 0 段；出发地缺失时返回空列表
    """
    from app.services.express_planning_service import _build_legs, _split_cities
    departure = ((state.get("user_requirement") or {}).get("departure_city") or "").strip()
    if not departure:
        return []
    cities = _split_cities(state.get("selected_destination") or "")
    # ★ "应有几段"的唯一口径：交通卡片、段日期、中间件都认它
    return [f"{a}→{b}" for a, b in _build_legs(departure, cities)]