"""
FastAPI 应用入口
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # ★ 本章新增

from app.config import settings
from app.utils.logger import app_logger
from app.api.v1 import users, cities, conversations  # ★ 本章新增


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    启动顺序：Checkpointer → Store → MCP
    关闭顺序：反过来（Python 上下文管理器自然保证）
    """
    import asyncio

    loop = asyncio.get_running_loop()
    app_logger.info(f"FastAPI 使用的事件循环: {type(loop).__name__}")

    # 延迟 import：Checkpointer/Store/MCP 会创建 psycopg 连接池或 stdio 子进程，
    # 必须在事件循环切换到 SelectorEventLoop 之后再 import
    from app.core.checkpointer import checkpointer_lifespan
    from app.core.store import store_lifespan
    from app.mcp_core.client import MCPClientManager

    app_logger.info("🚀 启动应用...")

    async with checkpointer_lifespan():
        app_logger.info("✅ Checkpointer 已就绪")

        async with store_lifespan():
            app_logger.info("✅ Store 已就绪")

            # 初始化 MCP（第 6 章加的）
            mcp = await MCPClientManager.get_instance()
            app_logger.info("✅ MCP 服务初始化成功")

            yield  # ← FastAPI 在这里处理请求

            # 关闭流程（反序）
            await mcp.close()
            app_logger.info("MCP 服务已关闭")

    app_logger.info("应用已关闭")


app = FastAPI(
    title="LangGraph 旅行规划系统",
    description="企业级 Agent 旅行规划服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ★ 本章新增：全部接口统一收编到 /api/v1（资源式扁平命名）
app.include_router(users.router, prefix="/api/v1")
app.include_router(cities.router, prefix="/api/v1")  # 全国城市（出发地单选/目的地多选）
app.include_router(conversations.router, prefix="/api/v1")

# ★ 本章新增：项目根的 image/ 目录挂成静态资源，浏览器可直接访问 /image/xxx
image_folder = os.path.join(os.getcwd(), "image")
os.makedirs(image_folder, exist_ok=True)
app.mount("/image", StaticFiles(directory=image_folder))


@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "LangGraph Travel Planner",
        "version": "1.0.0",
        "docs": "/docs",
    }