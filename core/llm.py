"""OpenAI 兼容 chat/completions 统一调用（analyze / summarize 共用）。"""
import time

import requests

# 共享会话：trust_env=False 彻底忽略环境/系统代理（用户代理工具关闭时 env 代理会导致全部调用失败）
_SESSION = requests.Session()
_SESSION.trust_env = False


def call_chat(base_url: str, api_key: str, model: str, messages: list,
              label: str, **overrides) -> str:
    """调 OpenAI 兼容端点 /chat/completions，返回模型回复 content；失败抛异常。

    overrides 里的键（temperature、max_tokens 等）直接进请求体。
    label 用于报错信息区分通道（如"截图分析"/"DeepSeek"）。
    """
    body = {"model": model, "messages": messages}
    body.update(overrides)
    resp = _SESSION.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=(30, 180),  # 连接 30s 快速失败重试；读取 180s（推理模型，响应可能较慢）
    )
    if resp.status_code != 200:
        # 带响应体抛出，否则日志里只有 "400 Bad Request" 无法定位
        raise RuntimeError(f"{label} API HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


def test_chat(base_url: str, api_key: str, model: str) -> dict:
    """连通性测试：发一条极短消息验证 key / 网络 / 模型可用（设置页"测试连接"用）。

    不走 call_chat —— 那里的 180s 读超时对交互式测试太长。返回结构 JSON 友好，
    错误信息面向普通用户（不暴露 HTTP 细节，401/403 直接说 Key 无效）。
    """
    started = time.monotonic()
    try:
        resp = _SESSION.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": "回复OK"}],
                  "max_tokens": 8},
            timeout=(10, 30),
        )
    except requests.Timeout:
        return {"ok": False, "error": "连接超时，请检查网络后重试"}
    except requests.RequestException as e:
        return {"ok": False, "error": f"无法连接到服务器：{e.__class__.__name__}"}
    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "Key 无效或无权限，请检查是否复制完整"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"服务返回 HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        resp.json()["choices"]
    except (KeyError, ValueError):
        return {"ok": False, "error": "服务响应格式异常，请稍后重试"}
    return {"ok": True, "latency_ms": latency_ms}
