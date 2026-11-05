import json
import re
from urllib.parse import urlparse
import httpx
from .analysis import input_limit, message_length


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
        504: "模型服务或上游网关超时，请稍后重试。",
    }
    return f"API 请求失败（HTTP {status}）：" + reasons.get(status, "请检查服务商状态、配置及网络。")


def complete(config, key, messages, on_chunk=None):
    if message_length(messages) > input_limit(config):
        raise ValueError("请求文本超过此模型的最大输入长度，请调高上限或缩短问题/选区。")
    endpoint = config["endpoint"].strip().rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
        raise ValueError("API 必须使用 HTTPS，本机接口可使用 HTTP。")
    if not config["model"].strip():
        raise ValueError("请先设置模型名称。")
    headers = {"Authorization": "Bearer " + key} if key else {}
    payload = {"model": config["model"], "messages": messages}
    with httpx.Client(timeout=180) as client:
        if on_chunk is not None:
            payload["stream"] = True
            with client.stream("POST", endpoint + "/chat/completions", headers=headers, json=payload) as response:
                if response.is_error:
                    raise ValueError(api_error_message(response.status_code))
                pieces = []
                finished = False
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        finished = True
                        break
                    if not data:
                        continue
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
                        if choice.get("finish_reason") is not None:
                            if choice["finish_reason"] != "stop":
                                raise ValueError("模型输出未完整结束（长度限制或内容过滤），请重试或调整模型。")
                            finished = True
                if not finished:
                    raise ValueError("流式连接提前结束，已收到内容仅为部分结果。")
                text = "".join(pieces)
        else:
            response = client.post(endpoint + "/chat/completions", headers=headers, json=payload)
            if response.is_error:
                raise ValueError(api_error_message(response.status_code))
            text = response.json()["choices"][0]["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("模型没有返回文本。")
    return text
