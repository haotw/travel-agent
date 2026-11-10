"""
配置管理模块
用 pydantic-settings 读 .env 并做类型校验
"""
import os  # os：拼路径、读环境变量都靠它
from functools import lru_cache  # lru_cache 缓存函数结果，同样的调用只算一次
from pydantic import Field  # Field 给字段配默认值、别名和校验规则
from pydantic_settings import BaseSettings, SettingsConfigDict  # BaseSettings 自动读 .env 的配置基类

# 项目根目录（这个文件所在的 app/ 的上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):  # 定义配置类 Settings，字段从 .env 自动读进来
    """应用全局配置"""

    # ============== 应用基础 ==============
    app_env: str = Field(default="development", alias="APP_ENV")  # 对应 .env 的 APP_ENV，没配就用 「development」
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")  # 对应 .env 的 APP_HOST，没配就用 「0.0.0.0」
    app_port: int = Field(default=8000, alias="APP_PORT")  # 对应 .env 的 APP_PORT，没配就用 8000
    debug: bool = Field(default=False, alias="DEBUG")  # 对应 .env 的 DEBUG，没配就用 False

    # ============== JWT ==============
    jwt_secret_key: str = Field(  # 对应 .env 的 JWT_SECRET_KEY
        default="travel-jwt-secret-change-in-prod",  # 默认值：「travel-jwt-sec…」
        alias="JWT_SECRET_KEY"  # 对应外部的名字：「JWT_SECRET_KEY」
    )  # Field 的参数写完了

    # ============== LLM ==============
    dashscope_api_key: str = Field(alias="DASHSCOPE_API_KEY")  # 对应 .env 的 DASHSCOPE_API_KEY，必填，没有默认值
    qwen_model_name: str = Field(default="qwen-max", alias="QWEN_MODEL_NAME")  # 对应 .env 的 QWEN_MODEL_NAME，没配就用 「qwen-max」
    qwen_base_url: str = Field(  # 对应 .env 的 QWEN_BASE_URL
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 默认值：「https://dashsc…」
        alias="QWEN_BASE_URL"  # 对应外部的名字：「QWEN_BASE_URL」
    )  # Field 的参数写完了
    qwen_temperature: float = 0.7  # 字段 qwen_temperature：默认 0.7
    qwen_max_tokens: int = 8000  # 字段 qwen_max_tokens：默认 8000

    # ============== LangSmith ==============
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")  # 对应 .env 的 LANGSMITH_API_KEY，没配就用 空字符串
    langsmith_project: str = Field(default="travel-planner-dev", alias="LANGSMITH_PROJECT")  # 对应 .env 的 LANGSMITH_PROJECT
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")  # 对应 .env 的 LANGSMITH_TRACING，没配就用 False
    langsmith_endpoint: str = Field(  # 对应 .env 的 LANGSMITH_ENDPOINT
        default="https://api.smith.langchain.com",  # 默认值：「https://api.sm…」
        alias="LANGSMITH_ENDPOINT"  # 对应外部的名字：「LANGSMITH_ENDP…」
    )  # Field 的参数写完了

    # ============== 数据库 ==============
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")  # 对应 .env 的 POSTGRES_HOST，没配就用 「localhost」
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")  # 对应 .env 的 POSTGRES_PORT，没配就用 5432
    postgres_db: str = Field(alias="POSTGRES_DB")  # 对应 .env 的 POSTGRES_DB，必填，没有默认值
    postgres_user: str = Field(alias="POSTGRES_USER")  # 对应 .env 的 POSTGRES_USER，必填，没有默认值
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")  # 对应 .env 的 POSTGRES_PASSWORD，必填，没有默认值

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")  # 对应 .env 的 REDIS_HOST，没配就用 「localhost」
    redis_port: int = Field(default=6379, alias="REDIS_PORT")  # 对应 .env 的 REDIS_PORT，没配就用 6379
    redis_db: int = Field(default=0, alias="REDIS_DB")  # 对应 .env 的 REDIS_DB，没配就用 0
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")  # 对应 .env 的 REDIS_PASSWORD，没配就用 空字符串

    # ============== 外部服务 ==============
    amap_api_key: str = Field(default="", alias="AMAP_API_KEY")  # 对应 .env 的 AMAP_API_KEY，没配就用 空字符串
    # 高德每个接口每秒最多发几个请求。个人开发者额度不高，具体多少在高德控制台的流量限制里看；
    # 超了高德会返回 10021 CUQPS_HAS_EXCEEDED_THE_LIMIT。行程清单补坐标、补路线按这个数排队发
    amap_qps: float = Field(default=3.0, alias="AMAP_QPS")
    # 浏览器访问后端用的地址，比如 https://travel.example.com（末尾不带 /）。
    # 行程清单的地图封面图指向后端的 /api/v1/maps/static，由后端带着 key 去取，key 不出后端。
    # 不填就写相对路径：前后端同域、或者前端开发服务器把 /api 代理到后端时能用
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    # 规划类回复（行程、预算、卡片说明）是整段算好再发的，这两个决定发多快：每秒约多少字、再长的正文最多发几秒。
    # 前端自己做了打字效果的话，RENDER_CHARS_PER_SECOND 填 0（一次发完）
    render_chars_per_second: float = Field(default=80.0, alias="RENDER_CHARS_PER_SECOND")
    render_max_seconds: float = Field(default=20.0, alias="RENDER_MAX_SECONDS")  # 对应 .env 的 RENDER_MAX_SECONDS，没配就用 20.0
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")  # 对应 .env 的 TAVILY_API_KEY，没配就用 空字符串
    qq_map_key: str = Field(default="", alias="QQ_MAP_KEY")  # 对应 .env 的 QQ_MAP_KEY，没配就用 空字符串

    deepseek_api_key: str = Field(default="", alias="DEEP_SEEK_API_KEY")  # 对应 .env 的 DEEP_SEEK_API_KEY，没配就用 空字符串
    deepseek_base_url: str = Field(  # 对应 .env 的 DEEPSEEK_BASE_URL
        default="https://api.deepseek.com",  # 默认值：「https://api.de…」
        alias="DEEPSEEK_BASE_URL"  # 对应外部的名字：「DEEPSEEK_BASE_…」
    )  # Field 的参数写完了
    deepseek_model_name: str = Field(  # 对应 .env 的 DEEPSEEK_MODEL_NAME
        default="deepseek-v4-flash",  # 默认值：「deepseek-v4-fl…」
        alias="DEEPSEEK_MODEL_NAME"  # 对应外部的名字：「DEEPSEEK_MODEL…」
    )  # Field 的参数写完了

    # pydantic-settings 的元配置
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),  # 从哪个文件读配置：拼路径
        env_file_encoding="utf-8",  # 配置文件的编码：「utf-8」
        case_sensitive=False,  # 环境变量名区分大小写吗：False
        extra="ignore"  # 忽略 .env 里没定义的多余字段
    )  # SettingsConfigDict 的参数写完了

    @property  # 当属性用：不用加括号就能读
    def database_url(self) -> str:  # 定义方法 database_url：不用传参，返回 str
        """生成 PostgreSQL 连接字符串"""
        return (  # 返回 拼好的文字「postgres…」
            f"postgresql://{self.postgres_user}:{self.postgres_password}"  # 一项：拼好的文字「postgres…」
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"  # 文字接上一行（相邻字符串 Python 会自动拼起来）
        )  # 括号收尾

    @property  # 当属性用：不用加括号就能读
    def redis_url(self) -> str:  # 定义方法 redis_url：不用传参，返回 str
        """生成 Redis 连接字符串"""
        if self.redis_password:  # self.redis_password 有值就走这里
            return (  # 返回 拼好的文字「redis://…」
                f"redis://:{self.redis_password}"  # 一项：拼好的文字「redis://…」
                f"@{self.redis_host}:{self.redis_port}/{self.redis_db}"  # 文字接上一行（相邻字符串 Python 会自动拼起来）
            )  # 括号收尾
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"  # 返回 拼好的文字「redis://」


@lru_cache  # 缓存结果，整个进程只算一次
def get_settings() -> Settings:  # 定义函数 get_settings：不用传参，返回 Settings
    """获取配置单例（用 lru_cache 保证进程内只创建一次）"""
    return Settings()  # 建 Settings 对象返回


# 全局配置对象，其他模块直接 from app.config import settings 使用
settings = get_settings()