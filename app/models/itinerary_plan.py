"""行程清单表

存结构化的行程 JSON，前端点"行程清单已生成，点击查看"时来这里取
"""
import uuid  # uuid：外键列的类型
from datetime import datetime  # 时间列的类型
from sqlalchemy import String, DateTime, JSON, ForeignKey, func  # 列类型、外键、取数据库当前时间
from sqlalchemy.orm import Mapped, mapped_column  # 声明列的工具
from sqlalchemy.dialects.postgresql import UUID  # PostgreSQL 的 UUID 类型
from app.models.base import Base  # 所有表模型的基类


class ItineraryPlan(Base):  # 行程清单表
    """行程清单表"""

    __tablename__ = "itinerary_plans"  # 表名写复数，和上面的会话表不一样，外键要照实写

    # plan_id 是业务代码生成的 UUID 字符串，前端从 itinerary_plans 帧里拿到它再来查
    # 由业务代码 str(uuid4()) 自己生成：存进数据库以后要马上返回给前端
    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)

    # 属于哪个会话（就是前端说的 sessionId，也是 LangGraph 的 thread_id）
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),  # UUID 类型
        ForeignKey("conversation.id", ondelete="CASCADE"),  # 外键指向 conversation 表，会话删了清单跟着删
        index=True,  # 按会话查最新清单要用，建索引
    )  # 这一列写完了

    # 完整的行程数据（前端的 TravelItinerary：title + itinerary_list，带经纬度和图片）
    plan_data: Mapped[dict] = mapped_column(JSON)

    # 生成状态：1 成功，2 失败
    status: Mapped[int] = mapped_column(default=1)

    # 创建时间，带时区
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())