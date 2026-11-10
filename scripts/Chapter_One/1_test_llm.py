"""
第 01 章冒烟测试：验证 LLM API Key 能通
跑完删掉这个文件即可
"""
from langchain_openai import ChatOpenAI
from app.config import settings

llm = ChatOpenAI(
    model=settings.qwen_model_name,
    base_url=settings.qwen_base_url,
    api_key=settings.dashscope_api_key,
    temperature=0.3,
)

response = llm.invoke("用一句话介绍杭州的西湖。")
print("=" * 60)
print(response.content)
print("=" * 60)