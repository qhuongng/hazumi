import httpx

from constants.config.llm import (
    LLM_CONNECT_TIMEOUT_SECONDS,
    LLM_READ_TIMEOUT_SECONDS,
    LLM_WRITE_TIMEOUT_SECONDS,
    LLM_POOL_TIMEOUT_SECONDS,
    LLM_API_KEY,
)


def build_http_timeout() -> httpx.Timeout:
    """Build HTTP timeout configuration for LLM requests."""
    return httpx.Timeout(
        connect=LLM_CONNECT_TIMEOUT_SECONDS,
        read=LLM_READ_TIMEOUT_SECONDS,
        write=LLM_WRITE_TIMEOUT_SECONDS,
        pool=LLM_POOL_TIMEOUT_SECONDS,
    )


def build_request_headers() -> dict:
    """Build HTTP headers for LLM API requests."""
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY.strip():
        headers["Authorization"] = f"Bearer {LLM_API_KEY.strip()}"
    return headers
