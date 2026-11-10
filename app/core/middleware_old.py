"""
StepConfigMiddleware（本章升级：注入长期记忆）
"""
from typing import Callable
from jinja2 import Template

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from app.core.state import TravelState
from app.core.store import get_user_memory_service   # ← 本章新增导入
from app.utils.logger import app_logger


class StepConfigMiddleware(AgentMiddleware):
    """
    步骤配置中间件

    职责（本章版本）：
      每一次 LLM 调用之前：
        1. 读 State.current_step
        2. 从 step_config 中查该步的 Prompt / Tools / Requires
        3. 前置依赖校验
        3.5 加载用户长期记忆（本章新增）
        4. 用 Jinja2 渲染 Prompt，把记忆和 State 一起塞进模板
        5. request.override(...) 注入 system_prompt + tools
    """

    def __init__(self, step_config: dict):
        self._step_config = step_config

    async def awrap_model_call(
            self,
            request: ModelRequest,
            handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        # ---------- 1. 读当前步骤 ----------
        state: TravelState = request.state
        state_dict = dict(state) if hasattr(state, "items") else {}
        current_step = state.get("current_step", "requirement_collection")
        user_id = state.get("user_id")

        app_logger.info(f"📋 用户 ID: {user_id}")
        app_logger.info(f"📍 当前步骤: {current_step}")

        # ---------- 2. 查 step_config ----------
        if current_step not in self._step_config:
            app_logger.error(f"❌ 未知步骤: {current_step}")
            raise ValueError(f"未知步骤: {current_step}")

        step_config = self._step_config[current_step]

        # ---------- 3. 前置依赖校验 ----------
        for required_field in step_config["requires"]:
            if required_field not in state or state[required_field] is None:
                error_msg = (
                    f"步骤 {current_step} 需要 State 中已存在字段: {required_field}"
                )
                app_logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)

        # ---------- 3.5 加载用户长期记忆（本章新增）----------
        memory_prompt = ""
        if user_id:
            try:
                service = await get_user_memory_service()
                memory_prompt = await service.format_memory_for_prompt(user_id)
                if memory_prompt:
                    app_logger.info(f"💾 已加载用户长期记忆: {user_id}")
                else:
                    app_logger.info(f"📝 用户首次使用，暂无历史记忆: {user_id}")
            except Exception as e:
                # 记忆加载失败不阻塞主流程——继续以"无记忆"状态往下走
                app_logger.warning(f"⚠️ 加载长期记忆失败: {e}")

        # ---------- 4. Jinja2 渲染 Prompt ----------
        # 把记忆作为模板变量塞进去，Prompt 里可以 {{ user_memory }} 引用
        state_dict["user_memory"] = memory_prompt

        try:
            template = Template(step_config["prompt"])
            system_prompt = template.render(**state_dict)
        except Exception as e:
            app_logger.warning(f"⚠️ 提示词渲染失败: {e}，回退到原始模板")
            system_prompt = step_config["prompt"]

        # 如果有记忆内容而 Prompt 模板里没有 {{ user_memory }} 占位符（老模板），
        # 就追加到 Prompt 末尾（渐进式兼容）
        if memory_prompt and "{{ user_memory }}" not in step_config["prompt"] \
                and "{{user_memory}}" not in step_config["prompt"]:
            system_prompt = f"{system_prompt}\n\n{memory_prompt}"

        # ---------- 5. 注入 request ----------
        tools = step_config["tools"]
        modified_request = request.override(
            system_prompt=system_prompt,
            tools=tools,
        )

        app_logger.info(f"✅ 已注入配置: {len(tools)} 个工具")

        # ---------- 6. 交给下一环 ----------
        return await handler(modified_request)




# ============== 工厂函数 ==============

async def create_step_config_middleware() -> StepConfigMiddleware:
    """
    工厂：从 step_config 模块加载配置并构造 Middleware。
    异步，因为 get_step_config() 是异步（后续章节要往里加 await get_mcp_tools() 之类）
    """
    from app.agents.handoffs.step_config import get_step_config

    step_config = await get_step_config()
    return StepConfigMiddleware(step_config)