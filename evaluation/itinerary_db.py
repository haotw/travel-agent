"""线上行程质检数据源：从 ItineraryPlans 表拉取真实落库行程

替代静态样本的线上质检模式：
- 每份落库行程（status=1）反序列化回"行程正文"，title（含目的地/天数/交通/
  酒店/餐饮档次的出发信息）作为需求清单 input——title 由需求生成，最忠实；
- 三维度 GEval 全部按 positive=True 断言：线上产出的每份行程都必须达标。
"""
import json  # json：plan_data 可能是字符串

from sqlalchemy import select, desc  # 拼查询语句，倒序

from app.models.base import async_session_maker  # 自己开数据库会话
from app.models.itinerary_plan import ItineraryPlan  # 清单表
from app.services.quality_check_service import plan_to_text  # 复用业务服务实现

async def _fetch(limit: int) -> list[dict]:  # 从库里取最近几份清单
    """查询最近落库成功的行程，转换为评测用例（同 itinerary_cases 结构）"""
    async with async_session_maker() as db:  # 开一个数据库会话
        result = await db.execute(  # 执行查询
            select(ItineraryPlan)  # 查清单表
            .where(ItineraryPlan.status == 1)  # 只取落库成功的行程
            .order_by(desc(ItineraryPlan.created_at))  # 最新的排前面
            .limit(limit)  # 最多取几份
        )  # 查询写完了
        rows = result.scalars().all()  # 取出全部结果
        cases = []  # 用例放这
        for row in rows:  # 每一份
            # 可能是字典，也可能是 JSON 文本
            plan_data = row.plan_data if isinstance(row.plan_data, dict) else json.loads(row.plan_data)
            cases.append({  # 加一条用例
                # title 含"目的地+天数+出发信息"，作为需求清单输入
                "input": plan_data.get("title", ""),
                "actual_output": plan_to_text(plan_data),  # 实际输出：清单转成的文字
                "note": f"线上质检:{str(row.plan_id)[:8]}",  # 备注：清单 id 前 8 位
                "positive": True,  # 线上产出行程必须三维度达标
            })  # 这一条写完了
        return cases  # 交回用例

def fetch_itinerary_cases(limit: int = 3) -> list[dict]:  # 同步入口，pytest 收集用例时调
    """同步包装（pytest 参数化在收集期同步执行）"""
    import asyncio  # 放函数里 import
    return asyncio.run(_fetch(limit))  # 跑异步查询