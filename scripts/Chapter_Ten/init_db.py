"""建表脚本（幂等，可反复跑）：

把 users / conversation / message 三张表建出来。
create_all 只补缺的表，已存在的表原样不动（需 PG）。
"""
import os
import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ★ 从 app.models 顶层 import 会触发 models/__init__.py，把三张表注册进 Base.metadata
from app.models import User, Conversation, Message  # noqa: F401
from app.models.base import Base, engine, init_db


async def main():
    print("[init_db] 开始建表...")
    await init_db()
    print("[init_db] 完成：", "、".join(sorted(Base.metadata.tables)))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())