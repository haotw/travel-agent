"""数据契约：请求 schema 在进业务之前挡住非法输入，响应 schema 只吐白名单字段（纯逻辑，无需密钥）"""
import uuid
from datetime import datetime
from types import SimpleNamespace

from pydantic import ValidationError

from app.schemas.conversation import ConversationUpdate
from app.schemas.message import MessageSendRequest
from app.schemas.user import UserRegister, UserResponse

ok = UserRegister(username="alice", email="alice@example.com", password="secret123")
print("合法注册 →", ok.username, ok.email)
for bad in [{"username": "bob", "email": "not-an-email", "password": "secret123"},
            {"username": "bob", "email": "bob@example.com", "password": "123"},
            {"username": "", "email": "bob@example.com", "password": "secret123"}]:
    try:
        UserRegister(**bad)
    except ValidationError as exc:
        err = exc.errors()[0]
        print(f"拦下 → 字段 {err['loc'][0]}，原因 {err['type']}")

# 测试驱动：冒充一行 ORM 用户记录，多带一个绝不能外泄的 password_hash
orm_user = SimpleNamespace(id=uuid.uuid4(), username="alice", email="alice@example.com",
                           preferences={"theme": "dark"}, created_at=datetime(2026, 10, 1, 9, 0),
                           password_hash="$2b$12$never-leak")
dumped = UserResponse.model_validate(orm_user).model_dump()
print("响应字段 →", list(dumped))
print("password_hash 漏出去了吗？", "password_hash" in dumped)

patch = ConversationUpdate(title="五一去杭州")
print("PATCH 只传标题 →", patch.model_dump(), "| 真正传了的：", patch.model_dump(exclude_unset=True))
try:
    MessageSendRequest(conversation_id="abc", content="")
except ValidationError as exc:
    print("空消息 →", exc.errors()[0]["type"])
print("会话 id 的格式不在这一层查 →", MessageSendRequest(conversation_id="not-a-uuid", content="你好").conversation_id)