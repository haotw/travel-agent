"""统一的响应格式和全局异常处理

前端的 request.ts 靠这两点：
1. 返回内容统一是 {code, msg, data}
2. HTTP 状态码：200 成功 / 401 跳登录 / 422 参数不对 / 5xx 服务器出错
"""
from typing import Any  # Any：返回的数据什么类型都行
import json  # json：解析接口返回的 JSON
from pydantic import BaseModel  # BaseModel 定义统一响应的结构
from fastapi import Request, Response  # Request 当前请求；Response 重建响应要用
from fastapi.responses import JSONResponse  # JSONResponse 返回 JSON
from app.utils.logger import app_logger  # 全项目共用的日志对象


class ResponseModel(BaseModel):  # 统一响应的结构，前端永远按这个拆
    code: int = 200  # 状态码，默认 200
    msg: Any = "SUCCESS"  # 提示消息，默认 SUCCESS
    data: Any | None = None  # 数据，默认 None


def response(  # 造一个统一格式的响应
    data: Any = None,  # 返回的数据，什么类型都行，也可以是 None
    code: int = 200,  # 状态码，默认 200
    msg: Any = "SUCCESS",  # 提示消息，默认 "SUCCESS"
) -> JSONResponse:  # 返回 JSONResponse
    """统一的返回格式 {code, msg, data}，HTTP 状态码和 code 保持一致"""
    if data is None:  # 没数据也统一成空列表，前端不用判空
        data = []  # data 换成空列表
    payload = ResponseModel(code=code, msg=msg, data=data).model_dump()  # 套成 {code,msg,data}，再转成字典
    return JSONResponse(content=payload, status_code=code)  # HTTP 状态码和 code 保持一致

# 全局异常处理：没被接住的异常一律返回 500，不把原始报错堆栈直接丢给前端
async def global_http_middleware(request: Request, call_next: Any):
    try:  # 响应头说是 JSON，内容不一定真是，先试着解析
        return await call_next(request)  # 直接放行，原样返回
    except Exception as err:  # 没接住的异常都到这，错误存到 err
        app_logger.exception("全局异常")  # 完整的报错堆栈记进日志，查线上问题全靠它
        return response([], 500, str(err))  # 返回给前端的只有一句简短说明，不暴露文件路径和内部函数名


# 参数校验不通过（RequestValidationError）→ 返回 422 和中文提示
async def validation_exception_handler(request: Request, exc: Any):
    first_error = exc.errors()[0]  # 只取第一条校验错误，前端一次提示一个就够
    msg = first_error["msg"]  # 错误信息
    if msg in ["Field required"]:  # 缺必填参数时是这句英文
        msg = "缺少必传参数"  # 换成中文，前端能直接显示
    return response(code=422, msg=msg, data=[])  # 回 422 和提示


# 响应包装中间件：让所有返回 JSON 的接口都变成 {code, msg, data}
_SKIP_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/image")


def _rebuild(resp: Any, raw: bytes) -> Response:  # 把读完的字节重新包成响应
    """用已经读出来的原始字节重新建一个响应

    body_iterator 只能读一次，读完以后原来的 resp 就空了，不能再返回它；
    这里保留响应头重建一个，content-length 让框架按新内容重新算
    """
    headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}  # 抄一份原响应头，content-length 除外：内容变了，长度要让框架重算
    return Response(content=raw, status_code=resp.status_code, headers=headers)  # 响应头原样，内容还是原来的字节


def _wrapped(resp: Any, data: Any, code: int, msg: Any) -> JSONResponse:  # 包成 {code,msg,data} 再返回
    """包成 {code,msg,data} 返回，原来的响应头原样保留

    一定要保留响应头：CORSMiddleware 注册在最里面，Access-Control-Allow-Origin 这些跨域头是加在原响应上的。
    直接用 response() 新建一个的话这些头就丢了，浏览器马上报 "No 'Access-Control-Allow-Origin' header is present"
    """
    if data is None:  # 没数据也统一成空列表，前端不用判空
        data = []  # data 换成空列表
    payload = ResponseModel(code=code, msg=msg, data=data).model_dump()  # 套成 {code,msg,data}，再转成字典
    headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}  # 抄一份原响应头，content-length 除外：内容变了，长度要让框架重算
    return JSONResponse(content=payload, status_code=code, headers=headers)  # 连同原响应头一起返回，CORS 加的跨域头才不会丢


async def wrap_json_middleware(request: Request, call_next: Any):  # 响应包装中间件：所有 JSON 接口都经过它
    """把 JSON 响应包成 {code,msg,data}（前端 request() 只拆一层）

    下面三种情况直接放行，不包：
    1. 文档和静态资源路径（/docs、/redoc、/openapi.json、/image）
    2. content-type 不是 application/json（SSE 的 text/event-stream、文件下载）
    3. 已经是 {code,msg,data} 了（response() 返回的，免得包两层）
    出错的响应：HTTP 状态码不变（401 还是 401、422 还是 422），msg 用 FastAPI 给的 detail
    """
    # 规则 1：文档和静态资源直接放行
    if request.url.path.startswith(_SKIP_PATH_PREFIXES):
        return await call_next(request)  # 直接放行，原样返回

    resp = await call_next(request)  # 先让里层的中间件和接口跑完，拿到响应
    # 规则 2（流式接口全靠这一条）：text/event-stream 直接放行，不读内容、不包装
    if "application/json" not in resp.headers.get("content-type", ""):
        return resp  # SSE、纯文本原样放行

    # 注意：用 app.middleware("http") 注册以后，call_next 返回的是 _StreamingResponse，
    # 它没有 .body（不能像直接调 ASGI app 那样读 resp.body），
    # 要自己把 body_iterator 读完才能拿到原始的 JSON 字节。
    # body_iterator 只能读一次：读完以后原来的 resp 就空了，下面只能用读到的 raw 重新建一个
    raw = b"".join([chunk async for chunk in resp.body_iterator])
    try:  # 响应头说是 JSON，内容不一定真是，先试着解析
        payload = json.loads(raw)  # 解析成 Python 对象，后面才好判断要不要包
    except Exception:  # 解析不了也不能让请求失败
        return _rebuild(resp, raw)  # 用读出来的字节原样还回去，body_iterator 已经读空了

    # 规则 3：已经是 {code,msg,data} 的直接放行，免得包两层
    if isinstance(payload, dict) and "code" in payload and "data" in payload:
        return _rebuild(resp, raw)  # 包过的不再包，前端永远只拆一层

    if resp.status_code < 400:  # 状态码小于 400 算成功
        return _wrapped(resp, payload, resp.status_code, "SUCCESS")  # 成功：接口返回的内容放进 data

    msg = payload.get("detail") if isinstance(payload, dict) else None  # 失败：FastAPI 的错误信息在 detail 里，取出来当 msg
    return _wrapped(resp, [], resp.status_code, msg or "请求失败")  # 失败的 data 给空列表，状态码保持原样