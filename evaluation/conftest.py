"""评测公共配置

作用：
1. 把项目根目录加入 sys.path，evaluation/ 下的测试能直接 `from app.xxx import ...`；
2. 关掉 DeepEval 的遥测上报。
评测要的 DASHSCOPE_API_KEY 等不在这里读：被测模块一 import 就会加载 app.config.settings，它自己读项目根的 .env。

评测目录独立于业务代码（app/），跑法：`uv run pytest evaluation/ -v`
或 deepeval 集成跑法：`deepeval test run evaluation/test_router.py`。
"""
import os  # os：设置环境变量
import sys  # sys：改 sys.path
from pathlib import Path  # Path：算项目根

# 关闭 DeepEval 遥测上报（posthog 外网不可达时刷错误噪音）
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

# 项目根目录 = evaluation/ 的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 确保项目根在 sys.path 首位（优先导入本项目 app 包，避免同名包冲突）
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # 把项目根插进去，evaluation 才 import 得到 app