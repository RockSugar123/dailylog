"""OpenAI 兼容 chat/completions 统一调用（analyze / summarize / ask 共用）。"""
import json
import time

import requests

# 共享会话：trust_env=False 彻底忽略环境/系统代理（残留环境代理会导致国内端点全部调用失败）
_SESSION = requests.Session()
_SESSION.trust_env = False

# base_url → 系统代理重试是否成功（进程内记忆，避免每次调用都白等一次直连超时）
_PROXY_OK: dict = {}


def _proxied_post(url: str, headers: dict, body: dict, timeout, stream: bool = False) -> requests.Response:
    proxied = requests.Session()
    proxied.trust_env = True  # 读环境/系统代理（Windows 注册表），本机代理工具即由此生效
    return proxied.post(url, headers=headers, json=body, timeout=timeout, stream=stream)


def _post_endpoint(url: str, api_key: str, body: dict, timeout,
                   stream: bool = False) -> requests.Response:
    """直连优先；仅当连接级失败（超时/拒绝/SSL）时经系统代理重试一次。

    国内端点直连最快也最稳；NIM 等海外端点直连不通，首次连接失败自动
    走系统代理并按端点记忆，后续调用直接走代理，不再白等直连超时。
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    if _PROXY_OK.get(url) is True:
        return _proxied_post(url, headers, body, timeout, stream)
    try:
        return _SESSION.post(url, headers=headers, json=body, timeout=timeout, stream=stream)
    except requests.RequestException:
        if _PROXY_OK.get(url) is False:
            raise
        try:
            resp = _proxied_post(url, headers, body, timeout, stream)
            _PROXY_OK[url] = True
            return resp
        except requests.RequestException:
            _PROXY_OK[url] = False
            raise


def _post_chat(base_url: str, api_key: str, body: dict, timeout) -> requests.Response:
    return _post_endpoint(f"{base_url}/chat/completions", api_key, body, timeout)


def call_chat(base_url: str, api_key: str, model: str, messages: list,
              label: str, **overrides) -> str:
    """调 OpenAI 兼容端点 /chat/completions，返回模型回复 content；失败抛异常。

    overrides 里的键（temperature、max_tokens 等）直接进请求体。
    label 用于报错信息区分通道（如"截图分析"/"DeepSeek"）。
    """
    body = {"model": model, "messages": messages}
    body.update(overrides)
    resp = _post_chat(base_url, api_key, body, timeout=(30, 180))
    if resp.status_code != 200:
        # 带响应体抛出，否则日志里只有 "400 Bad Request" 无法定位
        raise RuntimeError(f"{label} API HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


def call_chat_stream(base_url: str, api_key: str, model: str, messages: list,
                     label: str, on_delta, **overrides) -> str:
    """流式调 /chat/completions（SSE），每收到一段增量文本就回调 on_delta(text)。

    返回拼接后的完整 content。on_delta 内抛异常会中断流（用于窗口关闭时止损）。
    """
    body = {"model": model, "messages": messages, "stream": True}
    body.update(overrides)
    resp = _post_endpoint(f"{base_url}/chat/completions", api_key, body,
                          timeout=(30, 180), stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"{label} API HTTP {resp.status_code}: {resp.text[:300]}")
    parts = []
    for raw in resp.iter_lines(decode_unicode=True):
        line = (raw or "").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except ValueError:
            continue  # 注释行/残包跳过，不让一帧脏数据打断整条流
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        text = delta.get("content")
        if text:
            parts.append(text)
            on_delta(text)
    return "".join(parts)


def embed_texts(base_url: str, api_key: str, model: str, texts: list,
                label: str = "向量化") -> list:
    """调 OpenAI 兼容端点 /embeddings，按输入顺序返回向量列表；失败抛异常。"""
    resp = _post_endpoint(f"{base_url}/embeddings", api_key,
                          {"model": model, "input": texts}, timeout=(30, 120))
    if resp.status_code != 200:
        # 带响应体抛出，否则日志里只有 "400 Bad Request" 无法定位
        raise RuntimeError(f"{label} API HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json().get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError(f"{label} API 响应缺少向量数据")
    data.sort(key=lambda item: item.get("index", 0))
    return [item["embedding"] for item in data]


def test_embedding(base_url: str, api_key: str, model: str) -> dict:
    """连通性测试：向量化一条极短文本（设置页"测试连接"用），返回向量维度。

    错误信息面向普通用户（401/403 直接说 Key 无效），与 test_chat 同风格。
    """
    try:
        vecs = embed_texts(base_url, api_key, model, ["连接测试"])
    except requests.Timeout:
        return {"ok": False, "error": "连接超时，请检查网络后重试（海外端点需系统代理可用）"}
    except requests.RequestException as e:
        return {"ok": False, "error": f"无法连接到服务器：{e.__class__.__name__}"}
    except RuntimeError as e:
        msg = str(e)
        if "HTTP 401" in msg or "HTTP 403" in msg:
            return {"ok": False, "error": "Key 无效或无权限，请检查是否复制完整"}
        if "HTTP 429" in msg:
            return {"ok": False, "error": "请求过于频繁被限流，请稍等片刻再试"}
        return {"ok": False, "error": msg[:200]}
    return {"ok": True, "dim": len(vecs[0]) if vecs else 0}


def test_chat(base_url: str, api_key: str, model: str) -> dict:
    """连通性测试：发一条极短消息验证 key / 网络 / 模型可用（设置页"测试连接"用）。

    不走 call_chat —— 那里的 180s 读超时对交互式测试太长。返回结构 JSON 友好，
    错误信息面向普通用户（不暴露 HTTP 细节，401/403 直接说 Key 无效）。
    """
    started = time.monotonic()
    try:
        resp = _post_chat(base_url, api_key,
                          {"model": model, "messages": [{"role": "user", "content": "回复OK"}],
                           "max_tokens": 8},
                          timeout=(10, 30))
    except requests.Timeout:
        return {"ok": False, "error": "连接超时，请检查网络后重试（海外端点需系统代理可用）"}
    except requests.RequestException as e:
        return {"ok": False, "error": f"无法连接到服务器：{e.__class__.__name__}"}
    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "Key 无效或无权限，请检查是否复制完整"}
    if resp.status_code == 429:
        return {"ok": False, "error": "请求过于频繁被限流，请稍等片刻再试"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"服务返回 HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        resp.json()["choices"]
    except (KeyError, ValueError):
        return {"ok": False, "error": "服务响应格式异常，请稍后重试"}
    return {"ok": True, "latency_ms": latency_ms}
