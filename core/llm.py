"""OpenAI 兼容 chat/completions 统一调用（analyze / summarize 共用）。"""
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
