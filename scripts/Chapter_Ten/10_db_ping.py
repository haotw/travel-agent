"""连库自检：asyncpg 驱动装好了没有、.env 里的 PG 连不连得上（需 PG）"""
import asyncio
import sys

from sqlalchemy import text

from app.models.base import async_session_maker, engine

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main() -> None:
    print("连接串里的驱动：", engine.url.drivername)
    async with async_session_maker() as db:
        one = (await db.execute(text("SELECT 1"))).scalar()
        version = (await db.execute(text("SHOW server_version"))).scalar()
    print("SELECT 1 →", one)
    print("PG 主版本 ≥ 12：", int(version.split(".")[0]) >= 12)
    await engine.dispose()           # 脚本退出前把连接池关掉，免得退出时报"事件循环已关闭"


asyncio.run(main())