"""运行指标（Prometheus）：清理规则、行程补位、高德调用、天气块各发生了多少次

以前想知道一条清理规则还有没有用，要线上跑两周再 grep 日志；现在每命中一次记一个数，
Prometheus 定时拉 /metrics，Grafana 上直接看曲线。日志照样打，查单次细节还是看日志。

指标名统一以 knowgo_ 开头，标签取值都是下面注释里列出的固定几个，不放用户输入（防止标签爆炸）。
/metrics 不带登录校验（Prometheus 拉取不带 token），上线时在 Nginx 只放内网访问
"""
from prometheus_client import Counter, Histogram  # Counter 只增不减的计数器；Histogram 统计分布

# rule：protocol_leak 协议标记/工具痕迹；model_weather 目的地步模型自己写的天气
REPLY_CLEANED = Counter(
    "knowgo_reply_cleaned_total", "模型回复被清理规则改动的次数", ["rule"])  # 指标名、说明、标签；标签只放固定取值，防止指标爆炸

# kind：slot 补时段；return 补返程；tips 补小贴士；day 补整天；city 补城市；dropped 丢掉越界/重复的天或在路上的条目；
#       leg 交通日的班次条目被换成代码写的那条
ITINERARY_FIXES = Counter(
    "knowgo_itinerary_fixes_total", "模型交的行程结构被代码补位的处数", ["kind"])  # 按补位类型统计

# api：place_text 地点搜索；driving 驾车路线；staticmap 静态地图
# result：ok 成功；rejected 高德拒绝（key 无效、参数错等）；throttled 被限流；error 网络错误
AMAP_REQUESTS = Counter(
    "knowgo_amap_requests_total", "后端直接调高德 Web 服务的次数", ["api", "result"])  # 按接口和结果统计

# round：entry 进入目的地步那一轮；followup 目的地步追问轮
# result：rendered 补上了；empty 天气没查到，没补（不编）
WEATHER_BLOCK = Counter(
    "knowgo_weather_block_total", "目的地步由代码补天气块的次数", ["round", "result"])  # 按进入轮或追问轮、有没有数据统计

# tool：哪个 MCP 工具的返回和录的样本格式不一样，走了兼容解析（目前只有 searchHotels）
MCP_PARSE_FALLBACK = Counter(
    # 按工具统计
    "knowgo_mcp_parse_fallback_total", "MCP 返回和样本格式不同、走了兼容解析的次数", ["tool"])

# result：complete 每座城都有介绍；missing 至少一座城没写介绍（只统计多城、手动确认、进入目的地步那一轮）
DESTINATION_INTRO = Counter(
    # 按写全了没有统计
    "knowgo_destination_intro_total", "目的地步多城推荐的回复里城市介绍写全了没有", ["result"])

# result：updated 还没选交通，只改了天数；rescheduled 已选过交通，回到交通步重新查；refused 天数不合法或低于多城下限，没改；
#         error 写状态失败
TRAVEL_DAYS_CHANGES = Counter(
    # 按结果统计
    "knowgo_travel_days_changes_total", "用户改行程天数的次数（days_change_service）", ["result"])

# 模型交上来的每条行程写了多少字（代码补位之前）。提示词要求 50~100 字，看分布就知道模型有没有照做
ITINERARY_ITEM_CHARS = Histogram(
    # 按字数分桶，看模型写得够不够具体
    "knowgo_itinerary_item_chars", "模型交的行程条目字数", buckets=(15, 30, 50, 80, 100, 150))

# reason：gaps 有时段没安排；short 条目写得太短；off_route 写到了路线外的城市。本轮第一次提交时退回模型重写的次数（第二次不再退）
ITINERARY_REWRITE_ASKS = Counter(
    "knowgo_itinerary_rewrite_asks_total", "行程第一次提交被退回重写的次数", ["reason"])  # 按退回原因统计