"""第 10 章冒烟：服务起着的情况下，走真实 HTTP 把 9 个接口串一遍（需服务已启动 + PG）"""
import uuid

import httpx

BASE = "http://localhost:8000"
sfx = uuid.uuid4().hex[:6]


def check(name: str, ok: bool) -> None:
    print(f"{'✅' if ok else '❌'} {name}")
    assert ok, name


with httpx.Client(base_url=BASE, timeout=30) as c:
    check("健康检查 GET /", c.get("/").json().get("status") == "healthy")
    paths = c.get("/openapi.json").json()["paths"]
    check("/docs 里能看到 users / conversations / cities 三组接口",
          {"/api/v1/users/register", "/api/v1/conversations", "/api/v1/cities"} <= set(paths))

    r = c.post("/api/v1/users/register",
               json={"username": f"smoke_{sfx}", "email": f"smoke_{sfx}@example.com", "password": "secret123"})
    check("注册即登录：拿到令牌", r.status_code == 200 and bool(r.json()["access_token"]))
    alice = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = c.post("/api/v1/users/login", json={"username": f"smoke_{sfx}", "password": "secret123"})
    check("登录成功", r.status_code == 200)
    check("/me 返回本人", c.get("/api/v1/users/me", headers=alice).json()["username"] == f"smoke_{sfx}")
    check("不带令牌 → 401", c.get("/api/v1/users/me").status_code == 401)

    conv = c.post("/api/v1/conversations", json={"title": "冒烟会话"}, headers=alice).json()
    check("建会话", conv["title"] == "冒烟会话" and conv["status"] == "active")
    check("列会话能看到它", any(x["id"] == conv["id"] for x in c.get("/api/v1/conversations", headers=alice).json()))
    r = c.patch(f"/api/v1/conversations/{conv['id']}", json={"title": "改过的标题"}, headers=alice)
    check("改标题", r.json()["title"] == "改过的标题")

    r = c.post("/api/v1/users/register",
               json={"username": f"smoke_b_{sfx}", "email": f"smoke_b_{sfx}@example.com", "password": "secret123"})
    bob = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("越权：bob 查 alice 的会话 → 404", c.get(f"/api/v1/conversations/{conv['id']}", headers=bob).status_code == 404)

    check("软删", c.delete(f"/api/v1/conversations/{conv['id']}", headers=alice).status_code == 200)
    check("软删后列表里没有了", all(x["id"] != conv["id"] for x in c.get("/api/v1/conversations", headers=alice).json()))
    check("城市接口不用登录：全量 342 个", len(c.get("/api/v1/cities").json()) == 342)
    check("城市接口按省份过滤", len(c.get("/api/v1/cities", params={"q": "福建"}).json()) == 9)
print("冒烟通过：用户、会话、城市三组接口全部走通")