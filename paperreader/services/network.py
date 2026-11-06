import asyncio
import json
import re
from urllib.parse import urlparse
from paperreader.services.lazy import httpx
from .analysis import AnalysisStopped, input_limit, message_length


def pdf_url(value):
    parsed = urlparse(value.strip())
    if parsed.scheme != "https":
        raise ValueError("论文链接必须使用 HTTPS。")
    if parsed.hostname in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
        identifier = re.sub(r"^/(abs|pdf)/", "", parsed.path).removesuffix(".pdf")
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?", identifier):
            raise ValueError("无法识别 arXiv 论文编号。")
        return "https://arxiv.org/pdf/" + identifier
    if parsed.path.lower().endswith(".pdf"):
        return value.strip()
    raise ValueError("首版支持 arXiv 摘要/PDF 链接及其他网站的直接 PDF 链接。")


def download(value):
    url = pdf_url(value)
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > 100 * 1024 * 1024:
                raise ValueError("文件超过首版 100 MB 下载上限。")
    return bytes(data)


def api_error_message(status):
    reasons = {
        400: "请求参数或模型名称不被服务支持，请核对模型配置。",
        401: "API 密钥无效或已失效，请在模型设置中检查密钥。",
        402: "模型服务账户余额不足，请检查服务商账户。",
        403: "当前账户没有访问权限，请检查模型权限。",
        404: "API 路径或模型不存在，请核对基础地址和模型名称。",
        429: "请求过于频繁或额度受限，请稍后重试。",
        500: "模型服务内部错误，请稍后重试。",
        502: "模型服务或上游网关异常，请稍后重试。",
        503: "模型服务暂不可用或繁忙。请稍后重试，或切换其他服务商/模型；此状态不能直接判定为密钥或余额错误。",
        504: "模型服务或网关超时，不能据此判断 API Key 无效。连接测试使用流式请求；请检查网关对 stream=true 的支持及其超时设置。",
    }
    return f"API 请求失败（HTTP {status}）：" + reasons.get(status, "请检查服务商状态、配置及网络。")


def client_options(url):
    # HTTP is used for user-configured local/LAN endpoints. Environment proxy
    # variables can route these requests through a gateway that returns 504.
    return {"timeout": 180, "trust_env": urlparse(url).scheme == "https"}


async def cancellable_stream(url, headers, payload, consume, cancel):
    async def read():
        async with httpx.AsyncClient(**client_options(url)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.is_error:
                    raise ValueError(api_error_message(response.status_code))
                async for line in response.aiter_lines():
                    if consume(line):
                        break

    async def wait_for_stop():
        while not cancel.is_set():
            await asyncio.sleep(.05)

    if cancel.is_set():
        raise AnalysisStopped()
    request = asyncio.create_task(read())
    stopping = asyncio.create_task(wait_for_stop())
    try:
        await asyncio.wait((request, stopping), return_when=asyncio.FIRST_COMPLETED)
        if cancel.is_set():
            raise AnalysisStopped()
        await request
    finally:
        request.cancel()
        stopping.cancel()
        await asyncio.gather(request, stopping, return_exceptions=True)


def complete(config, key, messages, on_chunk=None, *, cancel=None):
    if message_length(messages) > input_limit(config):
        raise ValueError("请求文本超过此模型的最大输入长度，请调高上限或缩短问题/选区。")
    endpoint = config["endpoint"].strip().rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("API 基础地址必须是有效的 HTTP 或 HTTPS 地址。")
    if not config["model"].strip():
        raise ValueError("请先设置模型名称。")
    headers = {"Authorization": "Bearer " + key} if key else {}
    payload = {"model": config["model"], "messages": messages}
    url = endpoint + "/chat/completions"
    if on_chunk is not None:
        payload["stream"] = True
        headers["Accept"] = "text/event-stream"
        pieces = []
        finished = False

        def consume(line):
            nonlocal finished
            if not line.startswith("data:"):
                return False
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                return True
            if not data:
                return False
            event = json.loads(data)
            if "error" in event:
                raise ValueError("模型流返回错误，请检查服务状态后重试。")
            for choice in event.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                text = choice.get("delta", {}).get("content")
                if isinstance(text, str) and text:
                    pieces.append(text)
                    on_chunk(text)
                reason = choice.get("finish_reason")
                if reason is not None:
                    if reason != "stop":
                        raise ValueError("模型输出未完整结束（长度限制或内容过滤），请重试或调整模型。")
                    finished = True
            return False

        if cancel is not None:
            asyncio.run(cancellable_stream(url, headers, payload, consume, cancel))
        else:
            with httpx.Client(**client_options(url)) as client, client.stream("POST", url, headers=headers, json=payload) as response:
                if response.is_error:
                    raise ValueError(api_error_message(response.status_code))
                for line in response.iter_lines():
                    if consume(line):
                        break
        if not finished:
            raise ValueError("流式连接提前结束，已收到内容仅为部分结果。")
        text = "".join(pieces)
    else:
        with httpx.Client(**client_options(url)) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.is_error:
                raise ValueError(api_error_message(response.status_code))
            text = response.json()["choices"][0]["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("模型没有返回文本。")
    return text
