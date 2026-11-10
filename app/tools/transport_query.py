"""
交通查询工具（占位）
实际实现在第五章
"""
from langchain.tools import tool


@tool
def query_flight_info(
    origin: str,
    destination: str,
    departure_date: str
) -> str:
    """
    查询航班信息
    
    调用航班 Subagent，返回可选航班列表
    """
    # TODO: 第五章实现 Subagent 逻辑
    return f"✈️ 航班信息加载中...（Subagent 功能待实现）"


@tool
def query_train_info(
    origin: str,
    destination: str,
    departure_date: str
) -> str:
    """查询高铁信息"""
    # TODO: 第五章实现
    return f"🚄 高铁信息加载中...（Subagent 功能待实现）"


@tool
def query_driving_route(
    origin: str,
    destination: str
) -> str:
    """查询自驾路线"""
    # TODO: 第五章实现
    return f"🚗 自驾路线加载中...（Subagent 功能待实现）"