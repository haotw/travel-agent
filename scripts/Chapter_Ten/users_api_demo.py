"""用户接口：最小 app 只挂 users 路由，进程内发请求走一遍注册、登录、/me（需 PG）"""
import asyncio
import sys
import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import delete

from app.api.v1 import users
from app.models import User
from app.models.base import async_session_maker, engine

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = FastAPI()
app.include_router(users.router, prefix="/api/v1")        # 和 main.py 同样的挂法，只是不带 lifespan


async def main() -> None:
    sfx = uuid.uuid4().hex[:6]
    name, email = f"demo_{sfx}", f"demo_{sfx}@example.com"
    transport = httpx.ASGITransport(app=app)              # 不起服务，直接把请求交给 app
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/users/register", json={"username": name, "email": email, "password": "secret123"})
        body = r.json()
        token = body["access_token"]
        print("注册 →", r.status_code, "| token_type:", body["token_type"], "| 用户字段:", sorted(body["user"]))
        r = await c.post("/api/v1/users/register", json={"username": name, "email": f"x{email}", "password": "secret123"})
        print("同名再注册 →", r.status_code, r.json())
        r = await c.post("/api/v1/users/register", json={"username": f"x{name}", "email": email, "password": "secret123"})
        print("同邮箱换名 →", r.status_code, r.json())
        r = await c.post("/api/v1/users/register", json={"username": f"y{name}", "email": f"y{email}", "password": "123"})
        print("密码太短 →", r.status_code, r.json()["detail"][0]["type"])
        r = await c.post("/api/v1/users/login", json={"username": name, "password": "wrong-pass"})
        print("密码错 →", r.status_code, r.json())
        r = await c.post("/api/v1/users/login", json={"username": f"nobody_{sfx}", "password": "secret123"})
        print("用户不存在 →", r.status_code, r.json())
        r = await c.post("/api/v1/users/login", json={"username": name, "password": "secret123"})
        print("登录成功 →", r.status_code, "| 拿到新令牌:", bool(r.json()["access_token"]))
        r = await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        print("/me 带令牌 →", r.status_code, "| 是本人:", r.json()["username"] == name)
        r = await c.get("/api/v1/users/me")
        print("/me 不带令牌 →", r.status_code, r.json())
    async with async_session_maker() as db:                  # 清理测试用户
        await db.execute(delete(User).where(User.username.like(f"%{sfx}")))
        await db.commit()
    await engine.dispose()


asyncio.run(main())